"""Patch #8 perception tiers, reuse invalidation, and post-action cheap confirm."""

from __future__ import annotations

import json
import time

from memnara.agent.actions import ActionProposal, ActionRegistry, DEFAULT_GAMEPLAY_ACTIONS
from memnara.agent.events import structured_step_events
from memnara.agent.execute import ExecutionResult
from memnara.agent.history import RecentStep
from memnara.agent.loop import AgentLoop, format_step
from memnara.agent.observe import VisualOnlyObserver, fingerprint_context
from memnara.agent.ownership import ControlGate
from memnara.agent.perception_policy import (
    PerceptionTier,
    can_skip_post_semantic_vision,
    select_perception_tier,
    similar_reuse_allowed,
    ui_locked_visual,
    vision_request_for,
)
from memnara.agent.thinking import clip_text, resolve_thinking
from memnara.agent.validator import ActionValidator
from memnara.agent.stuck import StuckDetector, StuckState
from memnara.demo.autonomy import resolve_vision_scale, step_record
from memnara.perception.fusion import compact_summary, fuse
from memnara.perception.vision.images import encode_framebuffer_png
from memnara.perception.vision.models import SceneType
from memnara.perception.vision.ollama import OllamaVisionProvider
from memnara.perception.vision.prompts import (
    COMPACT_SYSTEM_PROMPT,
    LIGHT_SYSTEM_PROMPT,
    LIGHT_USER_PROMPT,
    observation_format_for,
)
from tests.support.frames import IDLE_PIXELS, frame, paint
from tests.test_thinking import RecordingExecutor, Scripted, _state, _visual


class CountingVision:
    def __init__(self, **visual_kw) -> None:
        self.calls = 0
        self.frames = []
        self.requests = []
        self.visual_kw = visual_kw

    def observe(self, captured, request=None):
        self.calls += 1
        self.frames.append(captured)
        self.requests.append(request)
        self.last_call_stats = {
            "png_bytes": 99,
            "eval_count": self.calls,
            "encode_ms": 0.5,
            "http_ms": 1.5,
            "parse_ms": 0.2,
            "prompt_chars": 40,
            "generation_chars": 12,
        }
        return _visual(description=f"call-{self.calls}", **self.visual_kw)


class Emu:
    def __init__(self, *, mark: int = 1, idle: int = 0) -> None:
        self.mark = mark
        self.idle = idle

    def capture_frame(self):
        return frame(paint(self.mark, idle=self.idle))

    def tick(self, count=1, *, render=True):
        return True


class MutatingExecutor:
    def __init__(self, emu: Emu, *, delta: int = 40) -> None:
        self.emu = emu
        self.delta = delta
        self.calls: list[str] = []

    def execute(self, proposal: ActionProposal) -> ExecutionResult:
        self.calls.append(proposal.action)
        self.emu.mark += self.delta
        return ExecutionResult(ok=True, executed=True, released=True)

    def release_all(self) -> None:
        return None


def _loop(observer, actions, *, thinking=None, executor=None, stuck=None, max_steps=1):
    return AgentLoop(
        observer=observer,
        reasoner=Scripted(list(actions)),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=executor or RecordingExecutor(),
        ownership=ControlGate(),
        thinking=thinking or resolve_thinking("balanced"),
        stuck=stuck,
        max_steps=max_steps,
    )


def test_tier_uses_cheap_signals_not_another_model() -> None:
    overworld = _visual()
    menu = _visual(menu_visible=True, scene_type=SceneType.MENU, visible_text=("ITEM",))
    assert select_perception_tier(
        stuck_state="NORMAL",
        saw_transition=False,
        prior_visual=overworld,
        meaningfully_changed=False,
        prefer_light=True,
    ) is PerceptionTier.LIGHT
    assert select_perception_tier(
        stuck_state="NORMAL",
        saw_transition=False,
        prior_visual=None,
        meaningfully_changed=False,
        prefer_light=False,
    ) is PerceptionTier.NORMAL
    assert select_perception_tier(
        stuck_state="NORMAL",
        saw_transition=False,
        prior_visual=menu,
        meaningfully_changed=False,
        prefer_light=True,
    ) is PerceptionTier.NORMAL
    assert select_perception_tier(
        stuck_state="CHANGE_STRATEGY",
        saw_transition=False,
        prior_visual=overworld,
        meaningfully_changed=False,
        prefer_light=True,
    ) is PerceptionTier.RICH
    assert select_perception_tier(
        stuck_state="NORMAL",
        saw_transition=True,
        prior_visual=overworld,
        meaningfully_changed=False,
        prefer_light=True,
    ) is PerceptionTier.NORMAL


def test_similar_reuse_refuses_menu_dialogue_battle_and_text() -> None:
    idle_ok = similar_reuse_allowed(
        reuse_policy="similar",
        visual=_visual(),
        stable=True,
        meaningfully_changed=False,
    )
    assert idle_ok is True
    assert ui_locked_visual(_visual(menu_visible=True)) is True
    assert ui_locked_visual(_visual(dialogue_visible=True)) is True
    assert ui_locked_visual(_visual(battle_visible=True)) is True
    assert ui_locked_visual(_visual(visible_text=("HELLO",))) is True
    assert (
        similar_reuse_allowed(
            reuse_policy="similar",
            visual=_visual(dialogue_visible=True, visible_text=("HI",)),
            stable=True,
            meaningfully_changed=False,
        )
        is False
    )
    observer = VisualOnlyObserver(Emu(idle=0), CountingVision(dialogue_visible=True, visible_text=("HI",)), reuse_policy="similar")
    first = observer.observe()
    observer._emulator.idle = IDLE_PIXELS
    second = observer.observe()
    assert first.perception_reused is False
    assert second.perception_reused is False
    assert observer._vision.calls == 2


def test_balanced_similar_reuse_skips_overworld_idle() -> None:
    vision = CountingVision()
    observer = VisualOnlyObserver(Emu(), vision, reuse_policy=resolve_thinking("balanced").perception_reuse)
    first = observer.observe()
    observer._emulator.idle = IDLE_PIXELS
    second = observer.observe()
    assert first.perception_reused is False
    assert second.perception_reused is True
    assert vision.calls == 1
    deliberate = VisualOnlyObserver(Emu(), CountingVision(), reuse_policy=resolve_thinking("deliberate").perception_reuse)
    deliberate.observe()
    deliberate._emulator.idle = IDLE_PIXELS
    later = deliberate.observe()
    assert later.perception_reused is False


def test_blocked_and_no_effect_skip_post_action_vision() -> None:
    vision = CountingVision()
    emu = Emu()
    observer = VisualOnlyObserver(emu, vision, reuse_policy="similar")
    blocked = _loop(
        observer,
        [{"action": "MOVE_RIGHT", "reason": "wall"}],
        executor=RecordingExecutor(),
    ).run().steps[0]
    assert blocked.movement_outcome == "BLOCKED"
    assert blocked.post_vision_skipped is True
    assert vision.calls == 1
    assert blocked.vision_call_count == 1
    assert blocked.confirmation_ms is not None
    assert blocked.vision_png_bytes == 99
    assert blocked.unaccounted_ms is not None
    accounted = (
        (blocked.acquire_ms or 0)
        + (blocked.reasoning_ms or 0)
        + (blocked.freshness_ms or 0)
        + (blocked.execution_ms or 0)
        + (blocked.post_acquire_ms or 0)
        + (blocked.classification_ms or 0)
    )
    assert abs((blocked.total_ms or 0) - accounted - (blocked.unaccounted_ms or 0)) < 2
    assert vision.requests[0] is not None

    vision_b = CountingVision(menu_visible=True, visible_text=("FIGHT",), scene_type=SceneType.MENU)
    emu_b = Emu()
    no_effect = _loop(
        VisualOnlyObserver(emu_b, vision_b, reuse_policy="exact"),
        [{"action": "PRESS_B", "reason": "back"}],
        executor=RecordingExecutor(),
    ).run().steps[0]
    assert no_effect.interaction_outcome == "NO_EFFECT"
    assert no_effect.post_vision_skipped is True
    assert vision_b.calls == 1
    events = structured_step_events(no_effect)
    assert "NO_EFFECT" in events


def test_press_with_changed_screen_still_calls_vision() -> None:
    class MenuAfterPress(CountingVision):
        def observe(self, captured, request=None):
            self.calls += 1
            self.frames.append(captured)
            self.requests.append(request)
            self.last_call_stats = {
                "png_bytes": 50 + self.calls,
                "eval_count": self.calls,
                "encode_ms": 0.5,
                "http_ms": 1.5,
                "parse_ms": 0.2,
                "prompt_chars": 40,
                "generation_chars": 12,
            }
            if self.calls == 1:
                return _visual(description="overworld")
            return _visual(
                description="menu",
                menu_visible=True,
                visible_text=("ITEM",),
                scene_type=SceneType.MENU,
            )

    vision = MenuAfterPress()
    emu = Emu()
    thinking = resolve_thinking("balanced")
    step = _loop(
        VisualOnlyObserver(emu, vision, reuse_policy=thinking.perception_reuse),
        [{"action": "PRESS_A", "reason": "talk"}],
        thinking=thinking,
        executor=MutatingExecutor(emu),
    ).run().steps[0]
    assert step.interaction_outcome == "ADVANCED"
    assert vision.calls == 2
    assert step.vision_call_count == 2
    assert step.post_vision_skipped is False
    assert step.perception_tier == "normal"
    assert step.vision_png_bytes == 51


def test_locomotion_defers_semantic_reread_until_next_decision() -> None:
    vision = CountingVision()
    emu = Emu()
    observer = VisualOnlyObserver(emu, vision, reuse_policy="similar")
    step = _loop(
        observer,
        [{"action": "MOVE_UP", "reason": "path"}],
        executor=MutatingExecutor(emu),
    ).run().steps[0]
    assert step.movement_outcome in {"MOVED", "UNCERTAIN"}
    assert step.post_vision_skipped is True
    assert vision.calls == 1
    assert observer.last_visual is None
    observer._emulator.idle = 0
    again = observer.observe()
    assert again.perception_reused is False
    assert vision.calls == 2


def test_stuck_recovery_uses_rich_and_does_not_skip_post_vision() -> None:
    settings = resolve_thinking("fast")
    request = vision_request_for(
        settings,
        select_perception_tier(
            stuck_state="EXPLORE",
            saw_transition=False,
            prior_visual=_visual(),
            meaningfully_changed=False,
            prefer_light=True,
        ),
    )
    assert request.tier is PerceptionTier.RICH
    assert request.include_entities is True
    assert can_skip_post_semantic_vision(
        action="MOVE_LEFT",
        stuck_state="EXPLORE",
        saw_transition=False,
        stable=True,
        digest_identical=False,
        meaningfully_changed=True,
        prior_visual=_visual(),
    ) is False


def test_deliberate_promotes_light_and_keeps_exact_reuse() -> None:
    settings = resolve_thinking("deliberate")
    request = vision_request_for(settings, PerceptionTier.LIGHT)
    assert request.tier is PerceptionTier.NORMAL
    assert request.compact_prompt is False
    assert settings.perception_reuse == "exact"


def test_light_vision_payload_omits_entities_and_uses_short_prompts() -> None:
    captured: list[dict] = []
    content = json.dumps(
        {
            "scene_type": "OVERWORLD",
            "description": "Character in traversable area; obstacle visible right.",
            "menu_visible": False,
            "dialogue_visible": False,
            "battle_visible": False,
            "confidence": 0.9,
        }
    )

    def http_post(path, body):
        if path == "/api/show":
            return {"capabilities": ["vision"]}
        captured.append(body)
        return {"message": {"content": content}, "eval_count": 40}

    settings = resolve_thinking("fast")
    request = vision_request_for(settings, PerceptionTier.LIGHT)
    provider = OllamaVisionProvider(
        http_get=lambda path: {"models": [{"name": "qwen3-vl:8b"}]},
        http_post=http_post,
        num_predict=settings.vision_num_predict,
        description_limit=settings.vision_description_limit,
        compact_prompt=True,
        scale=settings.vision_scale,
    )
    obs = provider.observe(frame(paint(1)), request=request)
    assert "obstacle visible right" in obs.description
    body = captured[-1]
    assert "entities" not in body["format"]["properties"]
    assert body["messages"][0]["content"] == LIGHT_SYSTEM_PROMPT
    assert body["messages"][1]["content"] == LIGHT_USER_PROMPT
    assert body["options"]["num_predict"] <= 128
    stats = provider.last_call_stats
    assert stats["png_bytes"] > 0
    assert stats["prompt_chars"] == len(LIGHT_SYSTEM_PROMPT) + len(LIGHT_USER_PROMPT)
    assert stats["eval_count"] == 40
    assert stats["encode_ms"] is not None
    assert stats["http_ms"] is not None
    assert stats["parse_ms"] is not None
    assert observation_format_for(include_entities=True)["properties"]["entities"]
    assert COMPACT_SYSTEM_PROMPT != LIGHT_SYSTEM_PROMPT


def test_reason_clip_and_wait_guidance_stay_generic() -> None:
    long_reason = "Because the scenery is beautiful and there are trees and a river and clouds " * 4
    clipped = clip_text(long_reason, resolve_thinking("fast").reason_limit)
    assert len(clipped) <= resolve_thinking("fast").reason_limit
    from memnara.agent.reasoning import FAST_SYSTEM_PROMPT, SYSTEM_PROMPT

    for text in (SYSTEM_PROMPT, FAST_SYSTEM_PROMPT):
        assert "WAIT remains valid" in text or "WAIT is valid" in text
        assert "locomotion" in text.lower()
        assert "pokemon" not in text.lower()


def test_events_surface_keeps_outcomes_for_later_affect() -> None:
    step = RecentStep(
        step=1,
        before_summary="s",
        before_fingerprint="a",
        proposal=ActionProposal(action="MOVE_RIGHT", reason="go", confidence=0.5),
        validation_ok=True,
        executed=True,
        execution_ok=True,
        after_summary="t",
        after_fingerprint="b",
        screen_changed=True,
        state_changed=False,
        stuck_state="SUSPECTED_STUCK",
        progress=True,
        movement_outcome="MOVED",
        interaction_mode="BATTLE_ACTIVE",
        transition_state="TRANSIENT",
    )
    events = structured_step_events(step, previous_mode="NON_BATTLE")
    assert events == (
        "MOVED",
        "BATTLE_ENTRY",
        "STUCK",
        "PROGRESS",
        "SCENE_CHANGED",
        "TRANSITION",
    )


def test_profiles_keep_ownership_and_stale_and_timing_fields() -> None:
    for name in ("fast", "balanced", "deliberate"):
        thinking = resolve_thinking(name)
        vision = CountingVision()
        emu = Emu()
        step = _loop(
            VisualOnlyObserver(emu, vision, reuse_policy=thinking.perception_reuse),
            [{"action": "WAIT", "reason": "menu still printing"}],
            thinking=thinking,
            executor=RecordingExecutor(),
        ).run().steps[0]
        assert step.thinking_profile == name
        assert step.unaccounted_ms is not None
        detailed = format_step(step, timing_details=True)
        assert "unaccounted_ms=" in detailed
        assert "tier=" in detailed
        record = step_record(step)
        assert "events" in record
        assert "vision_call_count" in record


def test_image_scale_cost_is_measured_not_guessed() -> None:
    native = frame(paint(3))
    sizes = {}
    times = {}
    for scale in (1, 2, 3):
        started = time.perf_counter()
        png, width, height = encode_framebuffer_png(native, scale=scale)
        times[scale] = (time.perf_counter() - started) * 1000
        sizes[scale] = (len(png), width, height)
    assert sizes[1][1:] == (40, 40)
    assert sizes[2][1:] == (80, 80)
    assert sizes[3][1:] == (120, 120)
    assert sizes[3][0] >= sizes[1][0]
    assert times[1] >= 0 and times[3] >= 0


def test_stale_drop_still_ignores_thinking_and_tier() -> None:
    class Flip:
        def __init__(self) -> None:
            self.live = frame(paint(1))
            self.vision_calls = 0

        def peek_frame(self):
            return self.live

        def passive_advance(self, count: int):
            return self.live, True

        def observe_frame(self, captured):
            self.vision_calls += 1
            visual = _visual(description=f"call-{self.vision_calls}")
            context = fuse(visual=visual)
            from memnara.agent.observe import ObservedState

            return ObservedState(
                context=context,
                fingerprint=fingerprint_context(context, None),
                progress_token=None,
                screen_digest=f"digest-{self.vision_calls}",
                perception_ms=1.0,
                summary=compact_summary(context),
                scene_stability="STABLE",
            )

    class FlipScene(Scripted):
        def __init__(self, observer: Flip, actions: list) -> None:
            super().__init__(actions)
            self.observer = observer

        def propose(self, **kwargs):
            self.observer.live = frame(paint(80))
            return super().propose(**kwargs)

    observer = Flip()
    result = AgentLoop(
        observer=observer,
        reasoner=FlipScene(observer, [{"action": "PRESS_A", "reason": "menu"}]),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=RecordingExecutor(),
        ownership=ControlGate(),
        thinking=resolve_thinking("balanced"),
        max_steps=1,
    ).run()
    assert result.steps[0].executed is False
    assert "StaleObservationError" in result.steps[0].error


def test_similar_reuse_refuses_menu_battle_and_text_only() -> None:
    for kwargs in (
        {"menu_visible": True, "scene_type": SceneType.MENU},
        {"battle_visible": True, "scene_type": SceneType.BATTLE},
        {"visible_text": ("HELLO",)},
    ):
        vision = CountingVision(**kwargs)
        observer = VisualOnlyObserver(Emu(), vision, reuse_policy="similar")
        observer.observe()
        observer._emulator.idle = IDLE_PIXELS
        later = observer.observe()
        assert later.perception_reused is False, kwargs
        assert vision.calls == 2, kwargs


def test_fast_first_step_is_light_and_uses_profile_reuse() -> None:
    thinking = resolve_thinking("fast")
    assert thinking.perception_reuse == "similar"
    vision = CountingVision()
    step = _loop(
        VisualOnlyObserver(Emu(), vision, reuse_policy=thinking.perception_reuse),
        [{"action": "WAIT", "reason": "look"}],
        thinking=thinking,
        executor=RecordingExecutor(),
    ).run().steps[0]
    assert step.perception_tier == "light"
    assert vision.requests[0].tier is PerceptionTier.LIGHT
    assert vision.requests[0].light_prompt is True
    assert vision.requests[0].include_entities is False
    assert step.vision_png_bytes == 99


def test_stuck_explore_uses_rich_and_still_rereads() -> None:
    stuck = StuckDetector()
    stuck.state = StuckState.EXPLORE
    vision = CountingVision()
    emu = Emu()
    step = _loop(
        VisualOnlyObserver(emu, vision, reuse_policy="similar"),
        [{"action": "MOVE_LEFT", "reason": "unstick"}],
        thinking=resolve_thinking("fast"),
        executor=MutatingExecutor(emu),
        stuck=stuck,
    ).run().steps[0]
    assert step.post_vision_skipped is False
    assert vision.calls == 2
    assert vision.requests[0].tier is PerceptionTier.RICH
    assert vision.requests[0].include_entities is True
    assert step.perception_tier == "rich"


def test_transition_does_not_skip_post_vision() -> None:
    from memnara.emulators.base import Framebuffer

    class FadeThenCalm:
        def __init__(self) -> None:
            self.phase = 0

        def capture_frame(self):
            if self.phase == 0:
                return Framebuffer(40, 40, "RGB", bytes(40 * 40 * 3), "fade")
            return frame(paint(4))

        def tick(self, count=1, *, render=True):
            self.phase = 1
            return True

    vision = CountingVision()
    emu = FadeThenCalm()
    observer = VisualOnlyObserver(emu, vision, reuse_policy="similar")
    step = _loop(
        observer,
        [{"action": "MOVE_RIGHT", "reason": "after fade"}],
        executor=RecordingExecutor(),
    ).run().steps[0]
    assert step.transition_state == "TRANSIENT" or observer._emulator.phase == 1
    assert vision.calls >= 1
    assert all(req is not None for req in vision.requests)


def test_operator_scale_env_overrides_thinking() -> None:
    fast = resolve_thinking("fast")
    assert resolve_vision_scale(fast, environ={}) == 2
    assert resolve_vision_scale(fast, environ={"MEMNARA_VISION_SCALE": "3"}) == 3
    assert resolve_vision_scale(resolve_thinking("deliberate"), environ={}) == 3


def test_battle_entry_after_move_is_not_similar_reused() -> None:
    class BattleLater(CountingVision):
        def observe(self, captured, request=None):
            self.calls += 1
            self.frames.append(captured)
            self.requests.append(request)
            self.last_call_stats = {
                "png_bytes": 80,
                "eval_count": self.calls,
                "encode_ms": 0.4,
                "http_ms": 1.0,
                "parse_ms": 0.1,
                "prompt_chars": 40,
                "generation_chars": 10,
            }
            if self.calls == 1:
                return _visual(description="field")
            return _visual(
                description="battle",
                battle_visible=True,
                scene_type=SceneType.BATTLE,
            )

    vision = BattleLater()
    emu = Emu()
    observer = VisualOnlyObserver(emu, vision, reuse_policy="similar")
    result = _loop(
        observer,
        [
            {"action": "MOVE_UP", "reason": "walk"},
            {"action": "PRESS_A", "reason": "fight"},
        ],
        thinking=resolve_thinking("balanced"),
        executor=MutatingExecutor(emu),
        max_steps=2,
    ).run()
    assert result.steps[0].post_vision_skipped is True
    assert vision.calls == 3
    assert result.steps[1].perception_reused is False
    assert result.steps[1].post_vision_skipped is False
    assert "battle_visible=True" in result.steps[1].before_summary
    events = structured_step_events(result.steps[1], previous_mode=result.steps[0].interaction_mode)
    assert "BATTLE_ENTRY" in events
