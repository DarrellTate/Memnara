"""Post-M6 interaction outcome and perception reuse. Synthetic frames only."""

from __future__ import annotations

import time

from memnara.agent.actions import ActionRegistry, DEFAULT_GAMEPLAY_ACTIONS
from memnara.agent.exceptions import MalformedProposalError
from memnara.agent.execute import ExecutionResult
from memnara.agent.interaction import InteractionOutcome, classify_interaction
from memnara.agent.loop import AgentLoop, format_step
from memnara.agent.movement import MovementOutcome
from memnara.agent.observe import ObservedState, VisualOnlyObserver, fingerprint_context
from memnara.agent.ownership import ControlGate, ControlOwner
from memnara.agent.reasoning import SYSTEM_PROMPT
from memnara.agent.stuck import StuckConfig, StuckDetector
from memnara.agent.validator import ActionValidator
from memnara.demo.autonomy import build_parser, step_record
from memnara.emulators.base import Framebuffer
from memnara.perception.fusion import compact_summary, fuse
from memnara.perception.vision.images import encode_framebuffer_png
from memnara.perception.vision.models import SceneType, VisualObservation


def _visual(**overrides) -> VisualObservation:
    data = dict(
        scene_type=SceneType.OVERWORLD,
        description="A generic menu.",
        visible_text=(),
        entities=(),
        menu_visible=True,
        dialogue_visible=False,
        battle_visible=False,
        confidence=0.9,
        notable_changes="",
        source="VISUAL",
        model="qwen3-vl:8b",
    )
    data.update(overrides)
    return VisualObservation(**data)


def _state(digest: str = "same", **visual_kw) -> ObservedState:
    visual = _visual(**visual_kw)
    context = fuse(visual=visual)
    return ObservedState(
        context=context,
        fingerprint=fingerprint_context(context, None),
        progress_token=visual_kw.get("token"),
        screen_digest=digest,
        perception_ms=1.0,
        summary=compact_summary(context),
        scene_stability="STABLE",
    )


class SequenceObserver:
    def __init__(self, states: list[ObservedState]) -> None:
        self.states = states
        self.calls = 0

    def observe(self) -> ObservedState:
        idx = min(self.calls, len(self.states) - 1)
        self.calls += 1
        return self.states[idx]


class Scripted:
    def __init__(self, actions: list) -> None:
        self.actions = list(actions)
        self.lines: list[tuple[str, ...]] = []

    def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
        self.lines.append(tuple(history_lines))
        raw = self.actions.pop(0) if self.actions else {"action": "WAIT", "reason": "fallback"}
        if isinstance(raw, Exception):
            raise raw
        return validator.parse_and_validate(raw)


class Exec:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def execute(self, proposal):
        self.actions.append(proposal.action)
        return ExecutionResult(ok=True, executed=True, released=True)

    def release_all(self) -> None:
        return None


def _loop(states, actions, **kwargs) -> AgentLoop:
    return AgentLoop(
        observer=kwargs.pop("observer", SequenceObserver(states)),
        reasoner=Scripted(actions),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=kwargs.pop("executor", Exec()),
        ownership=kwargs.pop("ownership", ControlGate()),
        stuck=kwargs.pop("stuck", None),
        max_steps=kwargs.pop("max_steps", 1),
        goal="Explore",
    )


def test_identical_stable_press_is_no_effect_and_not_progress() -> None:
    before = _state("same", description="Menu: FIGHT is highlighted. B confirms.")
    after = _state("same", description="The B button cancels this menu.")
    outcome = classify_interaction(action="PRESS_B", executed=True, before=before, after=after, transient=False)
    assert outcome is InteractionOutcome.NO_EFFECT
    step = _loop([before, after], [{"action": "PRESS_B", "reason": "confirm"}]).run().steps[0]
    assert step.screen_changed is False
    assert step.state_changed is False
    assert step.movement_outcome == MovementOutcome.NOT_APPLICABLE.value
    assert step.interaction_outcome == "NO_EFFECT"
    assert step.progress is False
    rendered = format_step(step)
    assert "movement=NOT_APPLICABLE" in rendered
    assert "interaction=NO_EFFECT" in rendered
    assert "progress=False" in rendered
    assert step_record(step)["interaction_outcome"] == "NO_EFFECT"


def test_menu_text_change_is_advanced() -> None:
    before = _state("same", visible_text=("FIGHT",), description="FIGHT")
    after = _state("same", visible_text=("ITEM",), description="ITEM")
    step = _loop([before, after], [{"action": "PRESS_A", "reason": "choose"}]).run().steps[0]
    assert step.interaction_outcome == "ADVANCED"
    assert step.progress is True


def test_battle_menu_change_is_advanced() -> None:
    before = _state("menu", battle_visible=True, menu_visible=True, visible_text=("FIGHT",))
    after = _state("menu", battle_visible=True, menu_visible=True, visible_text=("FIGHT", "BAG"))
    step = _loop([before, after], [{"action": "PRESS_A", "reason": "open"}]).run().steps[0]
    assert step.interaction_mode == "BATTLE_ACTIVE"
    assert step.interaction_outcome == "ADVANCED"
    assert step.progress is True


def test_pixel_change_without_semantic_change_is_changed_not_progress() -> None:
    before = _state("one", visible_text=("FIGHT",), description="The same menu.")
    after = _state("two", visible_text=("FIGHT",), description="The same menu.")
    step = _loop([before, after], [{"action": "PRESS_B", "reason": "nudge"}]).run().steps[0]
    assert step.screen_changed is True
    assert step.interaction_outcome == "CHANGED"
    assert step.progress is False


def test_repeated_no_effect_is_in_history_and_can_escalate_stuck() -> None:
    states = [_state("same", description=f"wording {i}") for i in range(8)]
    actions = [{"action": "PRESS_B", "reason": "again"} for _ in range(6)]
    stuck = StuckDetector(StuckConfig(unchanged_limit=99, same_action_limit=3, max_recovery_attempts=3))
    reasoner = Scripted(actions)
    loop = _loop(states, actions, reasoner=reasoner, stuck=stuck, max_steps=4)
    loop.reasoner = reasoner
    result = loop.run()
    assert result.steps[0].interaction_outcome == "NO_EFFECT"
    assert result.steps[0].progress is False
    assert any("PRESS_B → NO_EFFECT" in line for line in reasoner.lines[2])
    assert result.steps[2].stuck_state == "SUSPECTED_STUCK"
    assert "NO_EFFECT" in SYSTEM_PROMPT


def test_successful_interaction_clears_stuck() -> None:
    fight = dict(visible_text=("FIGHT",))
    done = dict(visible_text=("FIGHT", "DONE"))
    states = [_state("same", **fight) for _ in range(6)]
    states.append(_state("same", **fight))
    states.append(_state("next", **done))
    actions = [{"action": "PRESS_B", "reason": "no"} for _ in range(3)]
    actions.append({"action": "PRESS_A", "reason": "yes"})
    stuck = StuckDetector(StuckConfig(unchanged_limit=99, same_action_limit=3, max_recovery_attempts=3))
    result = _loop(states, actions, stuck=stuck, max_steps=4).run()
    assert result.steps[2].stuck_state == "SUSPECTED_STUCK"
    assert result.steps[3].interaction_outcome == "ADVANCED"
    assert result.steps[3].progress is True
    assert result.steps[3].stuck_state == "NORMAL"


def test_dialogue_text_continuation_is_still_progress() -> None:
    before = _state("dlg", dialogue_visible=True, menu_visible=False, visible_text=("Hello",), description="Hello")
    after = _state("dlg", dialogue_visible=True, menu_visible=False, visible_text=("Hello there",), description="Hello there")
    step = _loop([before, after], [{"action": "PRESS_A", "reason": "read"}]).run().steps[0]
    assert step.interaction_outcome == "ADVANCED"
    assert step.progress is True
    assert step.screen_changed is False


def test_move_outcome_is_separate_from_interaction() -> None:
    before = _state("a")
    after = _state("b")
    assert classify_interaction(action="MOVE_RIGHT", executed=True, before=before, after=after, transient=False) is InteractionOutcome.NOT_APPLICABLE
    step = _loop([before, after], [{"action": "MOVE_RIGHT", "reason": "walk"}]).run().steps[0]
    assert step.movement_outcome == MovementOutcome.UNCERTAIN.value
    assert step.interaction_outcome == "NOT_APPLICABLE"


def test_transition_press_is_uncertain_not_no_effect() -> None:
    before = _state("plain")
    after = _state("plain")
    after = ObservedState(
        context=after.context,
        fingerprint=after.fingerprint,
        progress_token=after.progress_token,
        screen_digest=after.screen_digest,
        perception_ms=after.perception_ms,
        summary=after.summary,
        scene_stability="TRANSIENT",
    )
    outcome = classify_interaction(action="PRESS_A", executed=True, before=before, after=after, transient=True)
    assert outcome is InteractionOutcome.UNCERTAIN


def test_failed_confirmation_is_uncertain() -> None:
    class Boom(SequenceObserver):
        def observe(self) -> ObservedState:
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("capture failed")
            return self.states[0]

    step = _loop(
        [_state("same")],
        [{"action": "PRESS_A", "reason": "confirm"}],
        observer=Boom([_state("same")]),
    ).run().steps[0]
    assert step.executed is True
    assert "PerceptionFailedError" in step.error
    assert step.interaction_outcome == "UNCERTAIN"
    assert step.progress is False


def test_ownership_still_blocks_the_press() -> None:
    executor = Exec()
    step = _loop(
        [_state("same"), _state("same")],
        [{"action": "PRESS_B", "reason": "try"}],
        executor=executor,
        ownership=ControlGate(ControlOwner.PAUSED),
    ).run().steps[0]
    assert executor.actions == []
    assert step.executed is False
    assert "OwnershipDeniedError" in step.error


def test_malformed_action_still_fails_closed() -> None:
    executor = Exec()
    step = _loop(
        [_state("same")],
        [MalformedProposalError("bad")],
        executor=executor,
    ).run().steps[0]
    assert executor.actions == []
    assert "MalformedProposalError" in step.error


def test_perception_reuse_skips_vlm_only_when_pixels_match() -> None:
    class Emu:
        def __init__(self, frames: list[bytes]) -> None:
            self.frames = frames
            self.index = 0

        def capture_frame(self):
            pixels = self.frames[min(self.index, len(self.frames) - 1)]
            return Framebuffer(8, 8, "RGB", pixels, "synthetic")

        def tick(self, count=1, *, render=True):
            self.index = min(self.index + count, len(self.frames) - 1)
            return True

    class Vision:
        def __init__(self) -> None:
            self.calls = 0

        def observe(self, frame):
            self.calls += 1
            battle = frame.pixels[0] == 80
            return _visual(
                description="reading",
                battle_visible=battle,
                menu_visible=not battle,
                visible_text=("FIGHT",) if not battle else ("GO",),
            )

    def paint(mark: int) -> bytes:
        raw = bytearray()
        for y in range(8):
            for x in range(8):
                value = (x * 20 + y * 7 + mark) % 256
                raw.extend((value, value, value))
        return bytes(raw)

    same = paint(1)
    changed = paint(80)
    black = bytes([0, 0, 0]) * 64
    emu = Emu([same, same, changed, black])
    vision = Vision()
    observer = VisualOnlyObserver(emu, vision)
    first = observer.observe()
    second = observer.observe()
    assert vision.calls == 1
    assert second.perception_reused is True
    assert first.context.visual.visible_text == second.context.visual.visible_text
    emu.index = 2
    third = observer.observe()
    assert vision.calls == 2
    assert third.perception_reused is False
    assert third.context.visual.battle_visible is True
    emu.index = 3
    fourth = observer.observe()
    assert fourth.scene_stability == "TRANSIENT"
    assert fourth.perception_reused is False
    assert vision.calls == 3


def test_reuse_does_not_hide_a_return_to_a_different_stable_scene() -> None:
    class Emu:
        def __init__(self) -> None:
            raw = bytearray()
            for y in range(8):
                for x in range(8):
                    raw.extend(((x * 15 + 4) % 256, (y * 9 + 4) % 256, 40))
            self.pixels = bytes(raw)

        def capture_frame(self):
            return Framebuffer(8, 8, "RGB", self.pixels, "synthetic")

    class Vision:
        def __init__(self) -> None:
            self.calls = 0

        def observe(self, frame):
            self.calls += 1
            return _visual(visible_text=(str(self.calls),))

    emu = Emu()
    vision = Vision()
    observer = VisualOnlyObserver(emu, vision)
    observer.observe()
    observer.observe()
    assert vision.calls == 1
    raw = bytearray()
    for y in range(8):
        for x in range(8):
            raw.extend(((x * 12 + 80) % 256, (y * 6 + 50) % 256, 10))
    emu.pixels = bytes(raw)
    fresh = observer.observe()
    assert vision.calls == 2
    assert fresh.perception_reused is False


def test_same_pixels_after_a_transition_are_not_reused() -> None:
    """A fade must drop the cached reading even when the landing pixels match."""

    def paint(mark: int) -> bytes:
        raw = bytearray()
        for y in range(8):
            for x in range(8):
                value = (x * 20 + y * 7 + mark) % 256
                raw.extend((value, value, value))
        return bytes(raw)

    stable = paint(1)
    black = bytes([0, 0, 0]) * 64

    class Emu:
        def __init__(self) -> None:
            self.frames = [stable, black, black, stable]
            self.index = 0

        def capture_frame(self):
            pixels = self.frames[min(self.index, len(self.frames) - 1)]
            return Framebuffer(8, 8, "RGB", pixels, "synthetic")

        def tick(self, count=1, *, render=True):
            self.index = min(self.index + count, len(self.frames) - 1)
            return True

    class Vision:
        def __init__(self) -> None:
            self.calls = 0

        def observe(self, frame):
            self.calls += 1
            text = ("FIGHT",) if self.calls == 1 else ("FIGHT", "BAG")
            return _visual(visible_text=text, description="menu", battle_visible=self.calls > 1)

    class TickExec:
        def __init__(self, emu: Emu) -> None:
            self.emu = emu

        def execute(self, proposal):
            self.emu.tick(1, render=True)
            return ExecutionResult(ok=True, executed=True, released=True)

        def release_all(self) -> None:
            return None

    emu = Emu()
    vision = Vision()
    result = AgentLoop(
        observer=VisualOnlyObserver(emu, vision),
        reasoner=Scripted([{"action": "PRESS_A", "reason": "leave the fade"}]),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=TickExec(emu),
        ownership=ControlGate(),
        max_steps=1,
        transition_grace_frames=8,
        transition_chunk_frames=1,
        passive_budget_frames=0,
    ).run()
    step = result.steps[0]
    assert vision.calls == 2
    assert step.perception_reused is False
    assert step.scene_stability == "STABLE"
    assert step.interaction_outcome == "ADVANCED"
    assert step.progress is True
    assert step.movement_outcome == "NOT_APPLICABLE"


def test_timing_flag_is_optional_and_help_lists_it() -> None:
    parser = build_parser()
    assert parser.parse_args([]).timing_details is False
    assert parser.parse_args(["--timing-details"]).timing_details is True
    step = _loop([_state("same"), _state("same")], [{"action": "PRESS_B", "reason": "try"}]).run().steps[0]
    quiet = format_step(step)
    detailed = format_step(step, timing_details=True)
    assert "TIMING reused=" not in quiet
    assert f"TIMING reused={step.perception_reused}" in detailed
    record = step_record(step)
    assert record["interaction_outcome"] == step.interaction_outcome
    assert record["perception_reused"] is step.perception_reused
    assert "vision_ms" in record["timings"]
    assert "confirmation_ms" in record["timings"]


def test_native_framebuffer_scale_cost_is_measured() -> None:
    pixels = bytes([index % 256 for index in range(160 * 144 * 4)])
    frame = Framebuffer(160, 144, "RGBA", pixels, "synthetic")
    native, native_w, native_h = encode_framebuffer_png(frame, scale=1)
    scaled, scaled_w, scaled_h = encode_framebuffer_png(frame, scale=3)
    assert (native_w, native_h) == (160, 144)
    assert (scaled_w, scaled_h) == (480, 432)
    assert len(scaled) > len(native)


def test_repeated_no_effect_steps_skip_repeat_vision_calls() -> None:
    class Emu:
        def __init__(self) -> None:
            self.ticks = 0

        def capture_frame(self):
            raw = bytearray()
            for y in range(8):
                for x in range(8):
                    raw.extend(((x * 18 + 30) % 256, (y * 11 + 20) % 256, 90))
            return Framebuffer(8, 8, "RGB", bytes(raw), "synthetic")

        def tick(self, count=1, *, render=True):
            self.ticks += count
            return True

    class Vision:
        def __init__(self) -> None:
            self.calls = 0

        def observe(self, frame):
            self.calls += 1
            time.sleep(0.01)
            return _visual(visible_text=("FIGHT",), description="stable menu")

    class Reasoner:
        def __init__(self) -> None:
            self.calls = 0

        def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
            self.calls += 1
            time.sleep(0.01)
            return validator.parse_and_validate({"action": "PRESS_B", "reason": "try the highlighted choice"})

    emu = Emu()
    vision = Vision()
    reasoner = Reasoner()
    started = time.perf_counter()
    result = AgentLoop(
        observer=VisualOnlyObserver(emu, vision),
        reasoner=reasoner,
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=Exec(),
        ownership=ControlGate(),
        max_steps=3,
    ).run()
    elapsed = time.perf_counter() - started
    assert vision.calls == 1
    assert reasoner.calls == 3
    assert all(step.interaction_outcome == "NO_EFFECT" for step in result.steps)
    assert all(step.progress is False for step in result.steps)
    assert result.steps[0].perception_reused is False
    assert result.steps[1].perception_reused is True
    assert elapsed < 0.2
