"""Perception observer contract. Implementations fuse through M4."""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256

from memnara.agent.movement import MovementOutcome, SceneSignature, frame_signature, read_navigation_token
from memnara.agent.readiness import frames_meaningfully_changed
from memnara.agent.thinking import REUSE_SIMILAR
from memnara.agent.transition import SceneStability, frame_stability
from memnara.perception.context import PerceptionContext
from memnara.perception.fusion import compact_summary, fuse

# Quoted in-game captions. Not title-specific. Ignores free-form visual prose.
_QUOTE_RE = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{1,240})[\"'“”‘’]")


@dataclass(frozen=True)
class ObservedState:
    context: PerceptionContext
    fingerprint: str
    progress_token: str | None
    screen_digest: str
    perception_ms: float
    summary: str
    scene: SceneSignature | None = None
    navigation_token: str | None = None
    scene_stability: str = "STABLE"
    perception_reused: bool = False
    vision_ms: float = 0.0
    observation_id: str = ""
    observed_at: float = 0.0
    runtime_frame: int = 0


def quoted_caption_text(description: str) -> str:
    """Join quoted spans from a VLM description. Empty if none."""
    parts = [item.strip() for item in _QUOTE_RE.findall(description or "") if item.strip()]
    return "\x1f".join(parts)


def caption_from_description(description: str) -> str:
    """Bounded caption when visible_text is missing. Quotes first; else a short tail after ':'."""
    quoted = quoted_caption_text(description)
    if quoted:
        return quoted
    text = (description or "").strip()
    if ":" not in text:
        return ""
    tail = text.rsplit(":", 1)[-1].strip()
    tail = re.sub(r"\s+", " ", tail)
    if len(tail) < 2 or len(tail) > 240:
        return ""
    return tail


def semantic_visual_key(context: PerceptionContext) -> str:
    """Flags plus on-screen text. Raw pixels and free-form overworld prose are excluded."""
    visual = context.visual
    if visual is None:
        return "VISUAL_ABSENT"
    visible = "\x1f".join(visual.visible_text)
    caption = ""
    if not visible and (visual.dialogue_visible or visual.menu_visible):
        caption = caption_from_description(visual.description)
    return (
        f"{visual.scene_type.value}|{visual.menu_visible}|"
        f"{visual.dialogue_visible}|{visual.battle_visible}|{visible}|{caption}"
    )


def fingerprint_context(
    context: PerceptionContext,
    progress_token: str | None = None,
) -> str:
    """Stable semantic fingerprint. Free-form description and raw pixels are excluded.

    Includes scene flags, visible text, a dialogue/menu caption when visible text
    is empty, and an optional structured progress token. Coordinates are never
    required. Two observations of the same flags and token share a fingerprint
    even if the model rephrases the description.
    """
    vis = semantic_visual_key(context)
    token = progress_token or ""
    raw = f"{vis}||{token}"
    return sha256(raw.encode("utf-8")).hexdigest()[:16]


def _visual_description(context: PerceptionContext) -> str:
    if context.visual is None:
        return ""
    return context.visual.description


def _stable_interaction_changed(before: ObservedState, after: ObservedState) -> bool:
    """Menu, dialogue, battle, visible text, or structured token. Not caption wording."""
    from memnara.agent.interaction import interaction_signature

    return interaction_signature(before) != interaction_signature(after)


def meaningful_progress(
    before: ObservedState,
    after: ObservedState,
    *,
    movement: MovementOutcome,
    interaction=None,
) -> bool:
    """Whether the step made gameplay progress.

    Menu, dialogue, and battle flags, visible text, and a structured token
    count even if the framebuffer is unchanged. A quoted caption or scene-type
    label that changes while those fields and the framebuffer stay the same
    does not. Locomotion progress follows movement outcome: MOVED counts,
    BLOCKED and UNCERTAIN do not. A non-movement NO_EFFECT does not. Free-form
    description wording counts only together with a framebuffer change.
    """
    from memnara.agent.interaction import InteractionOutcome

    if _stable_interaction_changed(before, after):
        return True
    if movement is MovementOutcome.MOVED:
        return True
    if movement is MovementOutcome.BLOCKED or movement is MovementOutcome.UNCERTAIN:
        return False
    if interaction is InteractionOutcome.NO_EFFECT:
        return False
    screen_changed = bool(after.screen_digest) and after.screen_digest != before.screen_digest
    if not screen_changed:
        return False
    return _visual_description(before.context) != _visual_description(after.context)


def digest_pixels(pixels: bytes) -> str:
    if not pixels:
        return ""
    return sha256(pixels).hexdigest()[:16]


class PerceptionObserver(ABC):
    @abstractmethod
    def observe(self) -> ObservedState:
        """Return fused M4 context plus optional progress token."""

    def confirm_execution(self, prior: ObservedState) -> ObservedState:
        """Cheap pre-execute check. Default keeps the reasoned observation.

        Must not call a vision model, capture a frame, or treat pixel animation
        as an interaction-mode change. The loop compares battle mode itself.
        """
        return prior


@dataclass(frozen=True)
class _PublishedIdentity:
    """What a continuous runtime already knows about the frame it handed over.

    Absent values stay empty or zero rather than being replaced by a live
    reading, so a frame-stepped runtime is distinguishable from frame 0 of a
    continuous one.
    """

    observation_id: str = ""
    digest: str = ""
    runtime_frame: int = 0
    captured_at: float = 0.0


def _published_identity(source) -> _PublishedIdentity:
    if not hasattr(source, "last_observation_id"):
        return _PublishedIdentity()
    return _PublishedIdentity(
        observation_id=str(getattr(source, "last_observation_id", "") or ""),
        digest=str(getattr(source, "last_digest", "") or ""),
        runtime_frame=int(getattr(source, "last_runtime_frame", 0) or 0),
        captured_at=float(getattr(source, "last_captured_at", 0.0) or 0.0),
    )


class VisualOnlyObserver(PerceptionObserver):
    """Generic VISION + INPUT observer. No structured game-state adapter."""

    def __init__(self, emulator, vision, *, reuse_policy: str = "exact") -> None:
        self._emulator = emulator
        self._vision = vision
        self._reuse_policy = reuse_policy
        self._reuse_digest: str | None = None
        self._reuse_visual = None
        self._reuse_frame = None
        self._observation_seq = 0

    def observe(self) -> ObservedState:
        return self.observe_frame(self.peek_frame())

    def peek_frame(self):
        """Capture the current framebuffer. Does not tick and does not call vision."""
        return self._emulator.capture_frame()

    def passive_advance(self, frames: int):
        """Advance frames with no button held, then capture.

        Returns the frame and whether the runtime actually advanced. A continuous
        runtime reports False when the frames did not arrive, so the caller does
        not count progress that never happened. Not a gameplay action.
        """
        if frames < 1:
            raise ValueError("frames must be >= 1")
        advanced = self._emulator.tick(frames, render=True)
        return self._emulator.capture_frame(), advanced is not False

    def probe_stability(self) -> str:
        """Pixel stability of the current frame. Does not call vision."""
        frame = self.peek_frame()
        return frame_stability(frame.pixels, frame.width, frame.height, frame.pixel_format).value

    def invalidate_perception_reuse(self) -> None:
        """Drop a cached reading after a fade. The next stable frame is read again."""
        self._reuse_visual = None
        self._reuse_digest = None
        self._reuse_frame = None

    def observe_frame(self, frame) -> ObservedState:
        """Run one vision call, or reuse a still-equivalent stable reading.

        Exact reuse matches the framebuffer digest. Similar reuse, when enabled,
        also accepts idle animation below the pixel-change threshold. A fade or
        a material scene change calls the vision model again.
        """
        started = time.perf_counter()
        # Identity belongs to the frame, so it is read before the vision call. A
        # continuous runtime already named, timed, and hashed the frame it
        # published; reuse that rather than running a parallel count that drifts
        # by one model call and a second hash of the same pixels.
        published = _published_identity(self._emulator)
        digest = published.digest or digest_pixels(frame.pixels)
        stability = frame_stability(frame.pixels, frame.width, frame.height, frame.pixel_format)
        self._observation_seq += 1
        observation_id = published.observation_id or f"{self._observation_seq}:{digest}"
        runtime_frame = published.runtime_frame
        observed_at = published.captured_at or time.time()
        reused = False
        vision_started = time.perf_counter()
        similar = (
            self._reuse_policy == REUSE_SIMILAR
            and stability is SceneStability.STABLE
            and self._reuse_visual is not None
            and self._reuse_frame is not None
            and not frames_meaningfully_changed(self._reuse_frame, frame)
        )
        if (
            stability is SceneStability.STABLE
            and self._reuse_visual is not None
            and digest
            and (digest == self._reuse_digest or similar)
        ):
            visual = self._reuse_visual
            reused = True
        else:
            visual = self._vision.observe(frame)
            if stability is SceneStability.STABLE and digest:
                self._reuse_visual = visual
                self._reuse_digest = digest
                self._reuse_frame = frame
            else:
                self._reuse_visual = None
                self._reuse_digest = None
                self._reuse_frame = None
        vision_ms = 0.0 if reused else (time.perf_counter() - vision_started) * 1000
        if reused:
            self._reuse_frame = frame
            self._reuse_digest = digest
        context = fuse(visual=visual)
        fingerprint = fingerprint_context(context, None)
        elapsed = (time.perf_counter() - started) * 1000
        return ObservedState(
            context=context,
            fingerprint=fingerprint,
            progress_token=None,
            screen_digest=digest,
            perception_ms=elapsed,
            summary=compact_summary(context),
            scene=frame_signature(frame.pixels, frame.width, frame.height, frame.pixel_format),
            navigation_token=read_navigation_token(context),
            scene_stability=stability.value,
            perception_reused=reused,
            vision_ms=vision_ms,
            observation_id=observation_id,
            observed_at=observed_at,
            runtime_frame=runtime_frame,
        )

    @property
    def runtime_frame(self) -> int:
        """Frames the runtime has advanced right now. Zero when it cannot say."""
        return int(getattr(self._emulator, "frames_advanced", 0) or 0)

