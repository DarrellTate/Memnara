"""Perception observer contract. Implementations fuse through M4."""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256

from memnara.agent.movement import MovementOutcome, SceneSignature, frame_signature, read_navigation_token
from memnara.agent.transition import frame_stability
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


def meaningful_progress(
    before: ObservedState,
    after: ObservedState,
    *,
    movement: MovementOutcome,
) -> bool:
    """Whether the step made gameplay progress.

    Flag, text, caption, and structured-token changes count even if the
    framebuffer is unchanged. Locomotion progress follows movement outcome:
    MOVED counts, BLOCKED and UNCERTAIN do not. Free-form description wording
    counts only for a non-movement action, and only together with a framebuffer
    change and no progress token. The same pixels rephrased by the model are
    not progress.
    """
    if semantic_visual_key(before.context) != semantic_visual_key(after.context):
        return True
    if (before.progress_token or "") != (after.progress_token or ""):
        return True
    if movement is MovementOutcome.MOVED:
        return True
    if movement is MovementOutcome.BLOCKED or movement is MovementOutcome.UNCERTAIN:
        return False
    if before.progress_token or after.progress_token:
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


class VisualOnlyObserver(PerceptionObserver):
    """Generic VISION + INPUT observer. No structured game-state adapter."""

    def __init__(self, emulator, vision) -> None:
        self._emulator = emulator
        self._vision = vision

    def observe(self) -> ObservedState:
        return self.observe_frame(self.peek_frame())

    def peek_frame(self):
        """Capture the current framebuffer. Does not tick and does not call vision."""
        return self._emulator.capture_frame()

    def passive_advance(self, frames: int):
        """Advance frames with no button held, then capture. Not a gameplay action."""
        if frames < 1:
            raise ValueError("frames must be >= 1")
        self._emulator.tick(frames, render=True)
        return self._emulator.capture_frame()

    def probe_stability(self) -> str:
        """Pixel stability of the current frame. Does not call vision."""
        frame = self.peek_frame()
        return frame_stability(frame.pixels, frame.width, frame.height, frame.pixel_format).value

    def observe_frame(self, frame) -> ObservedState:
        """Run one vision call on a frame the caller already captured."""
        started = time.perf_counter()
        visual = self._vision.observe(frame)
        context = fuse(visual=visual)
        digest = digest_pixels(frame.pixels)
        fingerprint = fingerprint_context(context, None)
        elapsed = (time.perf_counter() - started) * 1000
        stability = frame_stability(frame.pixels, frame.width, frame.height, frame.pixel_format)
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
        )

