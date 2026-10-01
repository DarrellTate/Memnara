"""Post-M6 transition recovery. Synthetic frames only. No second vision call per pumped frame."""

from __future__ import annotations

import time

import pytest

from memnara.agent.actions import ActionRegistry, DEFAULT_GAMEPLAY_ACTIONS
from memnara.agent.battle import BATTLE_PROMPT_BLOCK, InteractionMode, derive_battle_view
from memnara.agent.exceptions import InvalidActionError
from memnara.agent.execute import ExecutionResult
from memnara.agent.loop import AgentLoop, format_step
from memnara.agent.movement import MovementOutcome, classify_movement, frame_signature
from memnara.agent.observe import ObservedState, VisualOnlyObserver, digest_pixels, fingerprint_context
from memnara.agent.ownership import ControlGate, ControlOwner
from memnara.agent.reasoning import SYSTEM_PROMPT, build_user_prompt
from memnara.agent.stuck import StuckConfig, StuckDetector
from memnara.agent.transition import (
    TRANSITION_GUIDANCE,
    SceneStability,
    frame_stability,
)
from memnara.agent.validator import ActionValidator
from memnara.demo.autonomy import build_parser, controlled_window, step_record, wire_controlled_runtime
from memnara.emulators.base import Framebuffer
from memnara.emulators.pyboy_adapter import VISIBLE_PYBOY_WINDOW, PyBoyAdapter
from memnara.perception.fusion import compact_summary, fuse
from memnara.perception.vision.models import SceneType, VisualObservation

W = 16
H = 16
SHIFT_W = 24
SHIFT_H = 16


def _visual(**overrides) -> VisualObservation:
    data = dict(
        scene_type=SceneType.OVERWORLD,
        description="A generic field.",
        visible_text=(),
        entities=(),
        menu_visible=False,
        dialogue_visible=False,
        battle_visible=False,
        confidence=0.9,
        notable_changes="",
        source="VISUAL",
        model="qwen3-vl:8b",
    )
    data.update(overrides)
    return VisualObservation(**data)


def _rgb(width: int, height: int, paint) -> bytes:
    raw = bytearray()
    for y in range(height):
        for x in range(width):
            value = paint(x, y) & 255
            raw.extend((value, value, value))
    return bytes(raw)


def _solid(width: int, height: int, value: int) -> bytes:
    return _rgb(width, height, lambda _x, _y: value)


def _structured(width: int, height: int, *, scale: int = 17) -> bytes:
    return _rgb(width, height, lambda x, y: (x * scale + y * 9) % 256)


def _dark_stable(width: int, height: int) -> bytes:
    return _rgb(width, height, lambda x, _y: 30 if x < width // 2 else 160)


def _partial(width: int, height: int) -> bytes:
    return _rgb(width, height, lambda x, y: 0 if y < height // 2 else 90 + (x * 8) % 140)


def _ramp(width: int, height: int) -> bytes:
    return _rgb(width, height, lambda x, _y: x * 10)


def _shifted(width: int, height: int, dx: int) -> bytes:
    def paint(x, _y):
        source = x - dx
        if source < 0 or source >= width:
            return 0
        return source * 10

    return _rgb(width, height, paint)


def _state(stability: str = "STABLE", *, digest: str = "dig", scene=None, **visual_kw) -> ObservedState:
    visual = _visual(**visual_kw)
    context = fuse(visual=visual)
    return ObservedState(
        context=context,
        fingerprint=fingerprint_context(context, None),
        progress_token=None,
        screen_digest=digest,
        perception_ms=1.0,
        summary=compact_summary(context),
        scene=scene,
        scene_stability=stability,
    )


class SequenceObserver:
    def __init__(self, states: list[ObservedState]) -> None:
        self.states = states
        self.calls = 0

    def observe(self) -> ObservedState:
        idx = min(self.calls, len(self.states) - 1)
        self.calls += 1
        return self.states[idx]


class ChooseReasoner:
    def __init__(self, choose=None, *, delay_s: float = 0.0) -> None:
        self.calls = 0
        self.lines: list[tuple[str, ...]] = []
        self.contexts = []
        self.choose = choose or _choose
        self.delay_s = delay_s

    def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
        if self.delay_s:
            time.sleep(self.delay_s)
        self.calls += 1
        self.lines.append(tuple(history_lines))
        self.contexts.append(context)
        raw = self.choose(context, history_lines)
        if isinstance(raw, Exception):
            raise raw
        return validator.parse_and_validate(raw)


def _choose(context, history_lines):
    if any(TRANSITION_GUIDANCE in line for line in history_lines):
        return {"action": "WAIT", "parameters": {"frames": 30}, "reason": "scene is changing"}
    if derive_battle_view(context).mode is InteractionMode.BATTLE_ACTIVE:
        return {"action": "PRESS_A", "reason": "battle is visible"}
    return {"action": "MOVE_RIGHT", "reason": "explore the field"}


class RecordingExecutor:
    def __init__(self, runtime=None, *, tick_on: set[int] | None = None) -> None:
        self.actions: list[str] = []
        self.runtime = runtime
        self.tick_on = tick_on
        self.calls = 0

    def execute(self, proposal):
        self.calls += 1
        self.actions.append(proposal.action)
        if self.runtime is not None and (self.tick_on is None or self.calls in self.tick_on):
            self.runtime.tick(1, render=True)
        return ExecutionResult(ok=True, executed=True, released=True)

    def release_all(self) -> None:
        return None


class Frame:
    def __init__(self, pixels: bytes, visual: VisualObservation, *, width: int, height: int) -> None:
        self.pixels = pixels
        self.visual = visual
        self.width = width
        self.height = height
        self.pixel_format = "RGB"


class FrameRuntime:
    def __init__(self, frames: list[Frame]) -> None:
        self.frames = frames
        self.index = 0
        self.ticks = 0
        self.tick_sizes: list[int] = []
        self.renders: list[bool] = []
        self.presses: list[str] = []
        self.events: list[tuple] = []

    def tick(self, count: int = 1, *, render: bool = True) -> bool:
        self.events.append(("tick", count, render))
        self.ticks += count
        self.tick_sizes.append(count)
        self.renders.append(render)
        self.index = min(self.index + count, len(self.frames) - 1)
        return True

    def capture_frame(self) -> Framebuffer:
        frame = self.frames[self.index]
        self.events.append(("capture", self.index))
        return Framebuffer(frame.width, frame.height, frame.pixel_format, frame.pixels, "synthetic")

    def press_button(self, button, *, delay_frames: int = 1) -> None:
        self.presses.append(str(button))
        self.events.append(("press", str(button)))


class CountingVision:
    def __init__(self, runtime: FrameRuntime) -> None:
        self.runtime = runtime
        self.calls = 0
        self.indices: list[int] = []

    def observe(self, frame) -> VisualObservation:
        self.calls += 1
        self.indices.append(self.runtime.index)
        self.runtime.events.append(("vision", self.runtime.index))
        return self.runtime.frames[self.runtime.index].visual


def _frame(pixels: bytes, visual: VisualObservation, *, width: int = W, height: int = H) -> Frame:
    return Frame(pixels, visual, width=width, height=height)


def _black(visual: VisualObservation | None = None) -> Frame:
    return _frame(_solid(W, H, 0), visual or _visual(description="A dark frame."))


def _near_black(visual: VisualObservation | None = None) -> Frame:
    return _frame(_solid(W, H, 4), visual or _visual(description="A nearly dark frame."))


def _loop(observer, *, reasoner=None, executor=None, owner=ControlOwner.AI_CONTROL, grace=8, chunk=1, max_steps=1, dry_run=False, stuck=None, max_consecutive_failures=5, passive_budget_frames=0):
    return AgentLoop(
        observer=observer,
        reasoner=reasoner or ChooseReasoner(),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=executor or RecordingExecutor(),
        ownership=ControlGate(owner),
        stuck=stuck,
        max_steps=max_steps,
        max_consecutive_failures=max_consecutive_failures,
        dry_run=dry_run,
        transition_grace_frames=grace,
        transition_chunk_frames=chunk,
        passive_budget_frames=passive_budget_frames,
    )


def _wired(frames: list[Frame], **kwargs):
    runtime = FrameRuntime(frames)
    vision = CountingVision(runtime)
    observer = VisualOnlyObserver(runtime, vision)
    reasoner = kwargs.pop("reasoner", None) or ChooseReasoner()
    executor = kwargs.pop("executor", None) or RecordingExecutor(runtime, tick_on=set())
    executor.runtime = runtime
    loop = _loop(observer, reasoner=reasoner, executor=executor, **kwargs)
    return loop, runtime, vision, reasoner, executor


def test_stable_normal_frame_is_stable() -> None:
    assert frame_stability(_structured(W, H), W, H, "RGB") is SceneStability.STABLE


def test_near_black_frame_is_transient() -> None:
    assert frame_stability(_solid(W, H, 4), W, H, "RGB") is SceneStability.TRANSIENT
    assert frame_stability(_solid(W, H, 0), W, H, "RGB") is SceneStability.TRANSIENT
    # 246 black samples and 10 samples at 80. Span is 80, so this is not the uniform rule.
    mostly_black = bytearray()
    for index in range(W * H):
        value = 80 if index >= W * H - 10 else 0
        mostly_black.extend((value, value, value))
    assert frame_stability(bytes(mostly_black), W, H, "RGB") is SceneStability.TRANSIENT


def test_uniform_disruption_is_transient() -> None:
    assert frame_stability(_solid(W, H, 250), W, H, "RGB") is SceneStability.TRANSIENT


def test_dark_structured_scene_is_not_transient() -> None:
    pixels = _dark_stable(W, H)
    assert frame_stability(pixels, W, H, "RGB") is SceneStability.STABLE


def test_partial_scene_is_not_transient() -> None:
    assert frame_stability(_partial(W, H), W, H, "RGB") is SceneStability.STABLE


def test_stable_scene_after_transient_classifies_stable() -> None:
    seen = [
        frame_stability(_solid(W, H, 0), W, H, "RGB"),
        frame_stability(_solid(W, H, 3), W, H, "RGB"),
        frame_stability(_structured(W, H), W, H, "RGB"),
    ]
    assert seen == [SceneStability.TRANSIENT, SceneStability.TRANSIENT, SceneStability.STABLE]


def test_first_transient_observation_does_not_escalate_stuck() -> None:
    observer = SequenceObserver([_state("TRANSIENT", digest="t1")])
    result = _loop(observer, grace=3, max_steps=1).run()
    step = result.steps[0]
    assert step.proposal is None
    assert step.stuck_state == "NORMAL"
    assert step.scene_stability == "TRANSIENT"
    assert step.transition_state == "TRANSIENT"
    assert result.halt_reason == "max_steps"


def test_transient_frames_within_grace_do_not_escalate_stuck() -> None:
    states = [_state("TRANSIENT", digest=f"t{i}") for i in range(3)]
    reasoner = ChooseReasoner()
    result = _loop(SequenceObserver(states), reasoner=reasoner, grace=3, max_steps=3).run()
    assert reasoner.calls == 0
    assert [step.stuck_state for step in result.steps] == ["NORMAL", "NORMAL", "NORMAL"]
    assert all(step.proposal is None for step in result.steps)
    assert result.halt_reason == "max_steps"


def test_transition_grace_is_bounded() -> None:
    frames = [_black() for _ in range(4)]
    loop, runtime, vision, reasoner, _executor = _wired(frames, grace=6, chunk=4, max_steps=2)
    result = loop.run()
    assert runtime.ticks == 6
    assert runtime.tick_sizes == [4, 2]
    assert result.steps[1].passive_frames == 0
    assert runtime.ticks == 6


def test_grace_exhaustion_resumes_stuck_behavior() -> None:
    frames = [_black() for _ in range(4)]
    stuck = StuckDetector(StuckConfig(unchanged_limit=1, same_action_limit=99, max_recovery_attempts=1))
    loop, runtime, _vision, reasoner, executor = _wired(
        frames,
        grace=2,
        chunk=2,
        max_steps=5,
        stuck=stuck,
        executor=RecordingExecutor(tick_on=set()),
    )
    result = loop.run()
    assert result.steps[0].stuck_state == "NORMAL"
    assert result.halt_reason == "intervention_required"
    assert result.stuck_state == "INTERVENTION_REQUIRED"
    assert runtime.ticks == 2
    assert executor.actions
    assert "MOVE_RIGHT" not in executor.actions
    assert reasoner.calls >= 2


def test_stable_scene_resets_transition_grace() -> None:
    calm = _visual(description="A field with a path.")
    later = _visual(description="Another field.")
    frames = [
        _black(),
        _black(),
        _frame(_structured(W, H), calm),
        _black(),
        _black(),
        _frame(_structured(W, H, scale=3), later),
    ]
    loop, runtime, vision, _reasoner, _executor = _wired(
        frames,
        grace=2,
        chunk=1,
        max_steps=1,
        executor=RecordingExecutor(tick_on={1}),
    )
    result = loop.run()
    assert runtime.index == 5
    assert result.steps[0].passive_frames == 4
    assert vision.indices == [2, 5]
    assert runtime.ticks == 5


def test_transition_context_prefers_wait() -> None:
    states = [_state("TRANSIENT", digest="a"), _state("TRANSIENT", digest="b")]
    reasoner = ChooseReasoner()
    result = _loop(SequenceObserver(states), reasoner=reasoner, grace=1, max_steps=2).run()
    assert result.steps[0].proposal is None
    assert result.steps[1].proposal is not None
    assert result.steps[1].proposal.action == "WAIT"
    assert result.steps[1].proposal.parameters["frames"] == 30
    assert TRANSITION_GUIDANCE in reasoner.lines[0]
    assert TRANSITION_GUIDANCE not in SYSTEM_PROMPT


def test_black_frame_does_not_select_exploratory_movement() -> None:
    frames = [_black(), _black(), _frame(_structured(W, H), _visual())]
    loop, runtime, vision, reasoner, executor = _wired(frames, grace=8, chunk=1, max_steps=1)
    result = loop.run()
    assert runtime.presses == []
    assert vision.indices == [2]
    assert result.steps[0].passive_frames == 2
    assert result.steps[0].scene_stability == "STABLE"
    assert result.steps[0].proposal.action == "MOVE_RIGHT"
    assert TRANSITION_GUIDANCE not in reasoner.lines[0]
    assert executor.actions == ["MOVE_RIGHT"]


def test_transient_decision_refuses_gameplay_input() -> None:
    refused = sorted(action for action in DEFAULT_GAMEPLAY_ACTIONS if action != "WAIT")
    assert refused
    for action in refused:
        def one_action(_context, _lines, name=action):
            return {"action": name, "reason": "the frame is dark"}

        loop, runtime, _vision, _reasoner, executor = _wired(
            [_black()],
            grace=2,
            chunk=2,
            max_steps=2,
            max_consecutive_failures=1,
            reasoner=ChooseReasoner(one_action),
        )
        result = loop.run()
        assert result.halt_reason == "max_steps"
        assert len(result.steps) == 2
        for step in result.steps:
            assert step.scene_stability == "TRANSIENT"
            assert step.interaction_mode == "NON_BATTLE"
            assert step.executed is False
            assert step.execution_ok is False
            assert step.error.startswith("TransitionInputError")
        assert executor.actions == []
        assert runtime.presses == []
        assert runtime.ticks == 2


def test_wait_during_transition_is_bounded_by_the_normal_validator() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    accepted = validator.parse_and_validate({"action": "WAIT", "parameters": {"frames": 30}, "reason": "hold"})
    assert accepted.parameters["frames"] == 30
    with pytest.raises(InvalidActionError):
        validator.parse_and_validate({"action": "WAIT", "parameters": {"frames": 181}, "reason": "too long"})

    def choose(_context, _lines):
        return {"action": "WAIT", "parameters": {"frames": 999}, "reason": "too long"}

    states = [_state("TRANSIENT", digest="a"), _state("TRANSIENT", digest="b")]
    executor = RecordingExecutor()
    result = _loop(
        SequenceObserver(states),
        reasoner=ChooseReasoner(choose),
        executor=executor,
        grace=1,
        max_steps=2,
    ).run()
    assert result.steps[1].validation_ok is False
    assert result.steps[1].executed is False
    assert "InvalidActionError" in result.steps[1].error
    assert executor.actions == []


def test_scene_transition_after_move_is_not_moved() -> None:
    before = _ramp(SHIFT_W, SHIFT_H)
    after = _shifted(SHIFT_W, SHIFT_H, 1)
    direct = classify_movement(
        action="MOVE_LEFT",
        executed=True,
        navigation_before=None,
        navigation_after=None,
        scene_before=frame_signature(before, SHIFT_W, SHIFT_H, "RGB"),
        scene_after=frame_signature(after, SHIFT_W, SHIFT_H, "RGB"),
    )
    assert direct is MovementOutcome.MOVED
    calm = _visual(description="A field with a path.")
    frames = [
        _frame(before, calm, width=SHIFT_W, height=SHIFT_H),
        _frame(_solid(SHIFT_W, SHIFT_H, 0), calm, width=SHIFT_W, height=SHIFT_H),
        _frame(after, calm, width=SHIFT_W, height=SHIFT_H),
    ]
    loop, _runtime, _vision, _reasoner, executor = _wired(
        frames,
        grace=4,
        chunk=1,
        max_steps=1,
        executor=RecordingExecutor(tick_on={1}),
    )
    step = loop.run().steps[0]
    assert executor.actions == ["MOVE_RIGHT"]
    assert step.movement_outcome == MovementOutcome.UNCERTAIN.value
    assert step.transition_state == "TRANSIENT"
    assert step.screen_changed is True
    assert step.progress is False


def test_transient_override_is_uncertain_and_tokens_still_win() -> None:
    before = frame_signature(_ramp(SHIFT_W, SHIFT_H), SHIFT_W, SHIFT_H, "RGB")
    after = frame_signature(_shifted(SHIFT_W, SHIFT_H, 1), SHIFT_W, SHIFT_H, "RGB")
    uncertain = classify_movement(
        action="MOVE_LEFT",
        executed=True,
        navigation_before=None,
        navigation_after=None,
        scene_before=before,
        scene_after=after,
        stability_after=SceneStability.TRANSIENT.value,
    )
    moved = classify_movement(
        action="MOVE_LEFT",
        executed=True,
        navigation_before="position_token=1",
        navigation_after="position_token=2",
        scene_before=before,
        scene_after=after,
        stability_after=SceneStability.TRANSIENT.value,
    )
    blocked = classify_movement(
        action="MOVE_LEFT",
        executed=True,
        navigation_before="position_token=1",
        navigation_after="position_token=1",
        scene_before=before,
        scene_after=after,
        stability_before=SceneStability.TRANSIENT.value,
    )
    assert uncertain is MovementOutcome.UNCERTAIN
    assert moved is MovementOutcome.MOVED
    assert blocked is MovementOutcome.BLOCKED


def test_stable_movement_still_classifies_moved() -> None:
    calm = _visual(description="A field with a path.")
    frames = [
        _frame(_ramp(SHIFT_W, SHIFT_H), calm, width=SHIFT_W, height=SHIFT_H),
        _frame(_shifted(SHIFT_W, SHIFT_H, 1), calm, width=SHIFT_W, height=SHIFT_H),
    ]
    loop, runtime, _vision, reasoner, _executor = _wired(
        frames,
        grace=8,
        chunk=1,
        max_steps=1,
        executor=RecordingExecutor(tick_on={1}),
    )
    step = loop.run().steps[0]
    assert step.movement_outcome == MovementOutcome.MOVED.value
    assert step.progress is True
    assert step.passive_frames == 0
    assert step.transition_state == "STABLE"
    assert runtime.ticks == 1
    assert reasoner.calls == 1


def test_live_transition_sequence_does_not_intervene() -> None:
    overworld = _visual(description="A field with a path.")
    partial = _visual(description="A field coming into view.")
    battle = _visual(description="A combat exchange.", battle_visible=True)
    frames = [
        _frame(_structured(W, H), overworld),
        _near_black(),
        _black(),
        _frame(_partial(W, H), partial),
        _frame(_structured(W, H, scale=3), battle),
    ]
    reasoner = ChooseReasoner()
    loop, runtime, vision, reasoner, executor = _wired(
        frames,
        grace=30,
        chunk=1,
        max_steps=3,
        reasoner=reasoner,
        executor=RecordingExecutor(tick_on={1, 2, 3}),
    )

    def guarded_propose(*, context, goal, stuck_state, discouraged, history_lines, validator):
        current = frames[runtime.index]
        assert frame_stability(current.pixels, current.width, current.height, current.pixel_format) is SceneStability.STABLE
        return ChooseReasoner.propose(
            reasoner,
            context=context,
            goal=goal,
            stuck_state=stuck_state,
            discouraged=discouraged,
            history_lines=history_lines,
            validator=validator,
        )

    reasoner.propose = guarded_propose
    result = loop.run()
    assert result.halt_reason != "intervention_required"
    assert all(step.stuck_state != "INTERVENTION_REQUIRED" for step in result.steps)
    assert runtime.presses == []
    assert 1 not in vision.indices
    assert 2 not in vision.indices
    crossing = result.steps[0]
    assert crossing.movement_outcome == MovementOutcome.UNCERTAIN.value
    assert crossing.transition_state == "TRANSIENT"
    assert crossing.passive_frames == 2
    assert crossing.stuck_state == "NORMAL"
    assert crossing.progress is False
    assert result.steps[-1].interaction_mode == "BATTLE_ACTIVE"
    assert executor.actions[0] == "MOVE_RIGHT"
    record = step_record(crossing)
    assert record["scene_stability"] == "STABLE"
    assert record["transition_state"] == "TRANSIENT"
    assert record["transition_grace_remaining"] == 30
    assert record["passive_frames"] == 2
    rendered = format_step(crossing)
    assert "SCENE STABILITY STABLE" in rendered
    assert "transition=TRANSIENT" in rendered
    assert "movement=UNCERTAIN" in rendered
    assert "passive_frames=2" in rendered
    assert "stuck_state=NORMAL" in rendered


def test_persistent_black_beyond_grace_can_reach_stuck() -> None:
    stuck = StuckDetector(StuckConfig(unchanged_limit=1, same_action_limit=99, max_recovery_attempts=1))
    loop, runtime, _vision, _reasoner, executor = _wired(
        [_black() for _ in range(3)],
        grace=2,
        chunk=2,
        max_steps=5,
        stuck=stuck,
    )
    result = loop.run()
    assert result.steps[0].stuck_state == "NORMAL"
    assert result.halt_reason == "intervention_required"
    assert runtime.ticks == 2
    assert "MOVE_RIGHT" not in executor.actions


def test_stable_progress_after_transition_clears_stuck() -> None:
    battle = _visual(description="A combat exchange.", battle_visible=True)
    frames = [_black(), _black(), _black(), _frame(_structured(W, H, scale=5), battle)]
    stuck = StuckDetector(StuckConfig(unchanged_limit=1, same_action_limit=99, max_recovery_attempts=3))
    executor = RecordingExecutor(tick_on={3})
    loop, runtime, _vision, _reasoner, executor = _wired(
        frames,
        grace=2,
        chunk=1,
        max_steps=4,
        stuck=stuck,
        executor=executor,
    )
    result = loop.run()
    assert result.steps[1].stuck_state == "SUSPECTED_STUCK"
    assert result.steps[2].progress is True
    assert result.steps[2].stuck_state == "NORMAL"
    assert result.steps[2].movement_outcome == MovementOutcome.NOT_APPLICABLE.value
    assert result.steps[3].interaction_mode == "BATTLE_ACTIVE"
    assert result.halt_reason == "max_steps"


def test_battle_activates_only_after_the_stable_scene() -> None:
    battle = _visual(description="A combat exchange.", battle_visible=True)
    frames = [
        _near_black(),
        _black(),
        _frame(_structured(W, H, scale=4), battle),
    ]
    loop, runtime, vision, reasoner, executor = _wired(frames, grace=8, chunk=1, max_steps=1)
    result = loop.run()
    step = result.steps[0]
    assert step.interaction_mode == "BATTLE_ACTIVE"
    assert step.scene_stability == "STABLE"
    assert vision.indices == [2]
    assert runtime.presses == []
    assert reasoner.calls == 1
    assert derive_battle_view(reasoner.contexts[0]).mode is InteractionMode.BATTLE_ACTIVE
    prompt = build_user_prompt(
        context=reasoner.contexts[0],
        goal="Explore",
        allowed=DEFAULT_GAMEPLAY_ACTIONS,
        stuck_state="NORMAL",
        discouraged=(),
        history_lines=reasoner.lines[0],
    )
    assert prompt.startswith(BATTLE_PROMPT_BLOCK)
    assert executor.actions == ["PRESS_A"]


def test_transition_alone_does_not_assert_battle() -> None:
    calm = _visual(description="A new field.")
    frames = [_black(), _black(), _frame(_structured(W, H), calm)]
    loop, _runtime, vision, reasoner, _executor = _wired(frames, grace=8, chunk=1, max_steps=1)
    step = loop.run().steps[0]
    assert step.interaction_mode == "NON_BATTLE"
    assert step.scene_stability == "STABLE"
    assert frame_stability(_solid(W, H, 0), W, H, "RGB") is SceneStability.TRANSIENT
    assert derive_battle_view(reasoner.contexts[0]).mode is InteractionMode.NON_BATTLE
    prompt = build_user_prompt(
        context=reasoner.contexts[0],
        goal="Explore",
        allowed=DEFAULT_GAMEPLAY_ACTIONS,
        stuck_state="NORMAL",
        discouraged=(),
        history_lines=reasoner.lines[0],
    )
    assert "INTERACTION_MODE: BATTLE" not in prompt
    assert 0 not in vision.indices
    assert 1 not in vision.indices


def test_pump_advances_without_a_decision_per_frame_or_extra_vision() -> None:
    measured = _measure_black_pump()
    assert measured["visions"] == 1
    assert measured["reasons"] == 1
    assert measured["ticks"] == 8
    assert measured["tick_calls"] == 2
    assert measured["presses"] == 0
    assert measured["elapsed_s"] < 0.35
    assert measured["renders"] == [True, True]


def _measure_black_pump() -> dict:
    runtime = FrameRuntime([_black()])
    vision = CountingVision(runtime)
    reasoner = ChooseReasoner(
        lambda _context, _lines: {"action": "FLY", "reason": "not allowed"},
        delay_s=0.05,
    )
    loop = _loop(
        VisualOnlyObserver(runtime, vision),
        reasoner=reasoner,
        grace=8,
        chunk=4,
        max_steps=1,
    )
    started = time.perf_counter()
    result = loop.run()
    elapsed = time.perf_counter() - started
    assert result.steps[0].executed is False
    assert result.steps[0].passive_frames == 8
    return {
        "visions": vision.calls,
        "reasons": reasoner.calls,
        "ticks": runtime.ticks,
        "tick_calls": len(runtime.tick_sizes),
        "presses": len(runtime.presses),
        "elapsed_s": elapsed,
        "renders": list(runtime.renders),
    }


def test_ordinary_stable_gameplay_still_uses_the_decision_loop() -> None:
    calm = _visual(description="A field with a path.")
    frames = [
        _frame(_structured(W, H), calm),
        _frame(_structured(W, H, scale=5), calm),
        _frame(_structured(W, H, scale=9), calm),
    ]
    loop, runtime, vision, reasoner, executor = _wired(
        frames,
        grace=8,
        chunk=1,
        max_steps=2,
        executor=RecordingExecutor(tick_on={1, 2}),
    )
    result = loop.run()
    assert reasoner.calls == 2
    assert all(step.passive_frames == 0 for step in result.steps)
    assert all(step.transition_state == "STABLE" for step in result.steps)
    assert runtime.presses == []
    assert vision.calls == 3
    assert result.steps[1].perception_reused is True
    assert executor.actions == ["MOVE_RIGHT", "MOVE_RIGHT"]


@pytest.mark.parametrize("owner", [ControlOwner.PAUSED, ControlOwner.USER_CONTROL, ControlOwner.CONVERSATION])
def test_ownership_blocks_pump_and_input_during_transition(owner: ControlOwner) -> None:
    loop, runtime, vision, _reasoner, executor = _wired(
        [_black(), _frame(_structured(W, H), _visual())],
        owner=owner,
        grace=10,
        chunk=1,
        max_steps=1,
    )
    step = loop.run().steps[0]
    assert runtime.ticks == 0
    assert runtime.presses == []
    assert executor.actions == []
    assert step.executed is False
    assert f"OwnershipDeniedError: owner={owner.value}" in step.error
    assert vision.calls == 1


def test_dry_run_does_not_pump_a_transition() -> None:
    loop, runtime, _vision, _reasoner, executor = _wired(
        [_black()],
        grace=8,
        chunk=1,
        max_steps=1,
        dry_run=True,
    )
    step = loop.run().steps[0]
    assert runtime.ticks == 0
    assert runtime.presses == []
    assert executor.actions == []
    assert step.execution_ok is True
    assert step.executed is False
    assert "StaleSceneError" not in step.error


def test_stale_proposal_across_a_transition_fails_closed() -> None:
    class ProbeObserver:
        def __init__(self) -> None:
            self.probes = 0
            self.confirms = 0

        def observe(self) -> ObservedState:
            return _state("STABLE", digest="room")

        def confirm_execution(self, prior: ObservedState) -> ObservedState:
            self.confirms += 1
            return prior

        def probe_stability(self) -> str:
            self.probes += 1
            return SceneStability.TRANSIENT.value

    observer = ProbeObserver()
    executor = RecordingExecutor()
    result = _loop(
        observer,
        executor=executor,
        max_steps=2,
        max_consecutive_failures=1,
    ).run()
    assert observer.probes == 2
    assert observer.confirms == 2
    assert executor.actions == []
    assert all(step.error.startswith("StaleSceneError") for step in result.steps)
    assert all(step.executed is False for step in result.steps)
    assert result.halt_reason == "max_steps"
    assert result.stuck_state == "NORMAL"


def test_show_window_pump_advances_the_same_runtime() -> None:
    class Vision:
        def __init__(self) -> None:
            self.calls = 0

        def observe(self, frame):
            self.calls += 1
            return _visual(description="A dark frame.")

    args = build_parser().parse_args(["--show-window"])
    assert args.show_window is True
    window = controlled_window(show_window=args.show_window, configured="null")
    assert window == VISIBLE_PYBOY_WINDOW
    assert controlled_window(show_window=False, configured="null") == "null"
    # Same constructor argument the demo passes. start() is not called, so no SDL window opens.
    adapter = PyBoyAdapter(window=window, sound_emulated=False)
    assert adapter._window == window
    assert adapter._pyboy is None
    renders: list[tuple[int, bool]] = []

    def tick(count: int = 1, *, render: bool = True) -> bool:
        renders.append((count, render))
        return True

    def capture_frame() -> Framebuffer:
        return Framebuffer(W, H, "RGB", _solid(W, H, 0), "synthetic")

    adapter.tick = tick
    adapter.capture_frame = capture_frame
    vision = Vision()
    observer, gb_executor = wire_controlled_runtime(adapter, vision)
    assert observer._emulator is adapter
    assert gb_executor._emulator is adapter

    def refuse(_context, _lines):
        return {"action": "FLY", "reason": "not allowed"}

    loop = _loop(
        observer,
        reasoner=ChooseReasoner(refuse),
        executor=gb_executor,
        grace=4,
        chunk=2,
        max_steps=1,
    )
    result = loop.run()
    assert loop.observer._emulator is adapter
    assert loop.executor._emulator is adapter
    assert adapter._window == "SDL2"
    assert renders == [(2, True), (2, True)]
    assert vision.calls == 1
    assert result.steps[0].passive_frames == 4
    assert result.steps[0].executed is False
    assert adapter._pyboy is None


def test_grace_rejects_an_unbounded_budget() -> None:
    with pytest.raises(ValueError):
        _loop(SequenceObserver([_state()]), grace=0)
