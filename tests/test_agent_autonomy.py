from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from memnara.agent.actions import ActionProposal, ActionRegistry, DEFAULT_GAMEPLAY_ACTIONS
from memnara.agent.exceptions import ExecutionFailedError, InvalidActionError, MalformedProposalError
from memnara.agent.execute import ExecutionResult
from memnara.agent.loop import AgentLoop, format_step
from memnara.agent.observe import ObservedState, fingerprint_context
from memnara.demo.autonomy import step_record
from memnara.agent.ollama import OllamaReasoningProvider
from memnara.agent.ownership import ControlGate, ControlOwner
from memnara.agent.reasoning import build_user_prompt
from memnara.agent.stuck import StuckConfig, StuckDetector
from memnara.agent.validator import ActionValidator
from memnara.emulators.base import EmulatorAdapter, Framebuffer
from memnara.emulators.buttons import Button
from memnara.emulators.gameplay import GameBoyActionExecutor
from memnara.perception.context import PerceptionContext
from memnara.perception.fusion import compact_summary, fuse
from memnara.perception.vision.models import SceneType, VisualObservation


def _visual(**overrides) -> VisualObservation:
    data = dict(
        scene_type=SceneType.OVERWORLD,
        description="A room with furniture.",
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


def _observed(*, digest: str = "aaa", token: str | None = None, **visual_kw) -> ObservedState:
    visual = _visual(**visual_kw)
    context = fuse(visual=visual)
    return ObservedState(
        context=context,
        fingerprint=fingerprint_context(context, token),
        progress_token=token,
        screen_digest=digest,
        perception_ms=1.5,
        summary=compact_summary(context),
    )


class SequenceObserver:
    def __init__(self, states: list[ObservedState]) -> None:
        self.states = states
        self.calls = 0

    def observe(self) -> ObservedState:
        idx = min(self.calls, len(self.states) - 1)
        self.calls += 1
        return self.states[idx]


class ScriptedReasoner:
    def __init__(self, payloads: list[Any]) -> None:
        self.payloads = list(payloads)
        self.contexts: list[PerceptionContext] = []
        self.stuck_seen: list[tuple[str, tuple[str, ...]]] = []

    def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
        assert isinstance(context, PerceptionContext)
        self.contexts.append(context)
        self.stuck_seen.append((stuck_state, discouraged))
        if not self.payloads:
            raw: Any = {"action": "WAIT", "reason": "fallback"}
        else:
            raw = self.payloads.pop(0)
        if isinstance(raw, Exception):
            raise raw
        if isinstance(raw, ActionProposal):
            return raw
        return validator.parse_and_validate(raw)


class RecordingExecutor:
    def __init__(self, *, fail: bool = False, boom: bool = False) -> None:
        self.calls: list[str] = []
        self.released = 0
        self.fail = fail
        self.boom = boom

    def execute(self, proposal: ActionProposal) -> ExecutionResult:
        self.calls.append(proposal.action)
        if self.boom:
            raise RuntimeError("executor boom")
        if self.fail:
            return ExecutionResult(ok=False, executed=False, error="executor failed")
        return ExecutionResult(ok=True, executed=True, released=True)

    def release_all(self) -> None:
        self.released += 1


class FakeEmulator(EmulatorAdapter):
    def __init__(self) -> None:
        self.pressed: list[str] = []
        self.held: list[str] = []
        self.released: list[str] = []
        self.ticks = 0
        self._open = True

    def start(self, rom_path) -> None:
        self._open = True

    def stop(self) -> None:
        self._open = False

    def tick(self, count: int = 1, *, render: bool = True) -> bool:
        self.ticks += count
        return True

    def capture_frame(self) -> Framebuffer:
        return Framebuffer(2, 2, "RGBA", b"\x00" * 16, "fake")

    def press_button(self, button, *, delay_frames: int = 1) -> None:
        self.pressed.append(str(getattr(button, "value", button)))

    def hold_button(self, button) -> None:
        self.held.append(str(getattr(button, "value", button)))

    def release_button(self, button) -> None:
        self.released.append(str(getattr(button, "value", button)))

    def set_speed(self, speed: int) -> None:
        return None

    @property
    def native_resolution(self) -> tuple[int, int]:
        return (160, 144)

    def save_state(self, path) -> None:
        return None

    def load_state(self, path) -> None:
        return None

    def read_bytes(self, address: int, length: int) -> bytes:
        return b"\x00" * length

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def backend_version(self) -> str:
        return "fake"

    @property
    def cartridge_title(self) -> str | None:
        return "FAKE"


def _loop(**kwargs) -> AgentLoop:
    observer = kwargs.pop("observer", SequenceObserver([_observed()]))
    reasoner = kwargs.pop("reasoner", ScriptedReasoner([{"action": "MOVE_UP", "reason": "explore"}]))
    executor = kwargs.pop("executor", RecordingExecutor())
    ownership = kwargs.pop("ownership", ControlGate())
    validator = kwargs.pop("validator", ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)))
    return AgentLoop(
        observer=observer,
        reasoner=reasoner,
        validator=validator,
        executor=executor,
        ownership=ownership,
        **kwargs,
    )


def test_valid_structured_action_parses() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    proposal = validator.parse_and_validate(
        '{"action": "move_up", "reason": "look around", "confidence": 0.4}'
    )
    assert proposal.action == "MOVE_UP"
    assert proposal.reason == "look around"
    assert proposal.confidence == 0.4
    assert proposal.parameters == {}


def test_unknown_action_rejected() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    with pytest.raises(InvalidActionError):
        validator.parse_and_validate({"action": "USE_MOVE_1", "reason": "battle"})


def test_malformed_model_output_rejected() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    with pytest.raises(MalformedProposalError):
        validator.parse_and_validate("not-json")
    with pytest.raises(MalformedProposalError):
        validator.parse_and_validate({"actions": ["MOVE_UP", "MOVE_LEFT"], "reason": "script"})
    with pytest.raises(MalformedProposalError):
        validator.parse_and_validate({"action": ["MOVE_UP", "WAIT"], "reason": "two"})


def test_loop_revalidates_reasoner_output() -> None:
    executor = RecordingExecutor()
    raw = ActionProposal(action="MOVE_UP", parameters={"frames": 9}, reason="bad params")
    loop = _loop(
        reasoner=ScriptedReasoner([raw]),
        executor=executor,
        max_steps=1,
        max_consecutive_failures=3,
    )
    result = loop.run()
    assert executor.calls == []
    assert result.steps[0].validation_ok is False
    executor = RecordingExecutor()
    loop = _loop(
        observer=SequenceObserver([_observed(), _observed(digest="bbb")]),
        reasoner=ScriptedReasoner([{"action": "PRESS_A", "reason": "talk"}]),
        executor=executor,
        max_steps=1,
    )
    result = loop.run()
    assert len(result.steps) == 1
    assert executor.calls == ["PRESS_A"]


def test_no_action_outside_ai_control() -> None:
    executor = RecordingExecutor()
    loop = _loop(
        executor=executor,
        ownership=ControlGate(ControlOwner.USER_CONTROL),
        max_steps=1,
    )
    result = loop.run()
    assert executor.calls == []
    assert result.steps[0].executed is False
    assert "OwnershipDeniedError" in result.steps[0].error


def test_paused_emits_no_gameplay_action() -> None:
    executor = RecordingExecutor()
    loop = _loop(
        executor=executor,
        ownership=ControlGate(ControlOwner.PAUSED),
        max_steps=2,
    )
    result = loop.run()
    assert executor.calls == []
    assert all(not item.executed for item in result.steps)
    assert all("OwnershipDeniedError" in item.error for item in result.steps)


def test_validated_action_maps_through_executor() -> None:
    emu = FakeEmulator()
    executor = GameBoyActionExecutor(emu, tap_frames=2, settle_frames=3)
    proposal = ActionProposal(action="MOVE_RIGHT", reason="try east")
    result = executor.execute(proposal)
    assert result.ok is True
    assert result.executed is True
    assert emu.pressed == ["right"]
    assert emu.ticks == 3
    assert Button.RIGHT.value in emu.released or "right" in emu.released


def test_execution_failure_is_reported() -> None:
    executor = RecordingExecutor(fail=True)
    loop = _loop(executor=executor, max_steps=1)
    result = loop.run()
    assert result.steps[0].execution_ok is False
    assert result.steps[0].executed is False
    assert "executor failed" in result.steps[0].error
    boom = RecordingExecutor(boom=True)
    exploded = _loop(executor=boom, max_steps=1).run()
    assert exploded.steps[0].execution_ok is False
    assert "RuntimeError" in exploded.steps[0].error
    assert boom.released == 1


def test_perception_is_reobserved_after_execute() -> None:
    observer = SequenceObserver([_observed(digest="aaa"), _observed(digest="bbb")])
    loop = _loop(observer=observer, max_steps=1)
    result = loop.run()
    assert observer.calls == 2
    assert result.steps[0].screen_changed is True
    assert result.steps[0].progress is False


def test_history_records_before_action_after() -> None:
    observer = SequenceObserver([_observed(digest="aaa"), _observed(digest="bbb")])
    loop = _loop(observer=observer, max_steps=1)
    step = loop.run().steps[0]
    assert "VISUAL:" in step.before_summary
    assert step.proposal is not None
    assert step.proposal.action == "MOVE_UP"
    assert "VISUAL:" in step.after_summary
    assert step.before_fingerprint
    assert step.after_fingerprint


def test_repeated_unchanged_state_triggers_suspected_stuck() -> None:
    same = _observed(digest="same")
    detector = StuckDetector(StuckConfig(unchanged_limit=2, same_action_limit=99, max_recovery_attempts=8))
    loop = _loop(
        observer=SequenceObserver([same]),
        reasoner=ScriptedReasoner([{"action": "MOVE_UP", "reason": "wall"}] * 6),
        stuck=detector,
        max_steps=3,
    )
    result = loop.run()
    states = [item.stuck_state for item in result.steps]
    assert "SUSPECTED_STUCK" in states


def test_stuck_recovery_changes_strategy() -> None:
    same = _observed(digest="same")
    reasoner = ScriptedReasoner([{"action": "MOVE_UP", "reason": "again"}] * 8)
    detector = StuckDetector(StuckConfig(unchanged_limit=2, same_action_limit=99, max_recovery_attempts=8))
    loop = _loop(
        observer=SequenceObserver([same]),
        reasoner=reasoner,
        stuck=detector,
        max_steps=5,
    )
    result = loop.run()
    seen_states = [item.stuck_state for item in result.steps]
    assert seen_states == [
        "NORMAL",
        "NORMAL",
        "SUSPECTED_STUCK",
        "CHANGE_STRATEGY",
        "EXPLORE",
    ]
    assert detector.discouraged


def test_unrecovered_stuck_halts() -> None:
    same = _observed(digest="same")
    detector = StuckDetector(StuckConfig(unchanged_limit=1, same_action_limit=99, max_recovery_attempts=2))
    loop = _loop(
        observer=SequenceObserver([same]),
        reasoner=ScriptedReasoner([{"action": "MOVE_LEFT", "reason": "nudge"}] * 20),
        stuck=detector,
        max_steps=12,
    )
    result = loop.run()
    assert result.halt_reason == "intervention_required"
    assert result.stuck_state == "INTERVENTION_REQUIRED"
    assert len(result.steps) < 12


def test_absence_of_coordinates_does_not_break_stuck_detection() -> None:
    visual_only = _observed(digest="wall", token=None)
    assert visual_only.progress_token is None
    detector = StuckDetector(StuckConfig(unchanged_limit=2, same_action_limit=99, max_recovery_attempts=8))
    loop = _loop(
        observer=SequenceObserver([visual_only]),
        stuck=detector,
        max_steps=3,
    )
    result = loop.run()
    assert "SUSPECTED_STUCK" in [item.stuck_state for item in result.steps]


def test_invalid_proposals_cannot_execute() -> None:
    executor = RecordingExecutor()
    loop = _loop(
        reasoner=ScriptedReasoner([{"action": "TELEPORT", "reason": "cheat"}]),
        executor=executor,
        max_steps=1,
        max_consecutive_failures=3,
    )
    result = loop.run()
    assert executor.calls == []
    assert result.steps[0].validation_ok is False
    assert result.steps[0].executed is False


def test_loop_honors_max_steps() -> None:
    loop = _loop(max_steps=3)
    result = loop.run()
    assert result.halt_reason == "max_steps"
    assert len(result.steps) == 3


def test_dry_run_never_sends_gameplay_input() -> None:
    executor = RecordingExecutor()
    loop = _loop(executor=executor, dry_run=True, max_steps=2)
    result = loop.run()
    assert executor.calls == []
    assert result.dry_run is True
    assert all(item.validation_ok for item in result.steps)
    assert all(not item.executed for item in result.steps)
    assert all(item.execution_ok for item in result.steps)


def test_generic_agent_core_has_no_pyboy_or_ram_addresses() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "memnara" / "agent"
    forbidden = ("pyboy",)
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in text, f"{path.name} must not contain {token!r}"


def test_perception_context_is_reasoning_input_boundary() -> None:
    reasoner = ScriptedReasoner([{"action": "WAIT", "reason": "look"}])
    observed = _observed()
    loop = _loop(observer=SequenceObserver([observed]), reasoner=reasoner, max_steps=1, dry_run=True)
    loop.run()
    assert reasoner.contexts
    assert isinstance(reasoner.contexts[0], PerceptionContext)
    prompt = build_user_prompt(
        context=observed.context,
        goal="Explore",
        allowed=DEFAULT_GAMEPLAY_ACTIONS,
        stuck_state="NORMAL",
        discouraged=(),
        history_lines=(),
    )
    assert "CURRENT_EVIDENCE" in prompt
    assert "VISUAL:" in prompt
    assert re.search(r"0x[0-9A-Fa-f]{3,}", prompt) is None
    assert "walkthrough" not in prompt.lower()


def test_wait_parameters_and_forbidden_keys() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    wait = validator.parse_and_validate({"action": "WAIT", "parameters": {"frames": 12}, "reason": "pause"})
    assert wait.parameters == {"frames": 12}
    with pytest.raises(InvalidActionError):
        validator.parse_and_validate({"action": "MOVE_UP", "parameters": {"frames": 2}, "reason": "nope"})
    with pytest.raises(InvalidActionError):
        validator.parse_and_validate({"action": "WAIT", "reason": "x", "shell": "rm"})


def test_consecutive_failures_halt() -> None:
    loop = _loop(
        reasoner=ScriptedReasoner([MalformedProposalError("bad")] * 5),
        max_steps=8,
        max_consecutive_failures=2,
    )
    result = loop.run()
    assert result.halt_reason == "consecutive_failures"
    assert len(result.steps) == 2


def test_ollama_reasoner_parses_content_and_thinking_fallback() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    observed = _observed()

    def post_content(path, body):
        assert body["think"] is False
        assert "format" in body
        return {"message": {"content": '{"action":"PRESS_B","reason":"cancel","confidence":0.2}'}}

    provider = OllamaReasoningProvider(http_post=post_content, think=False)
    proposal = provider.propose(
        context=observed.context,
        goal="Explore",
        stuck_state="NORMAL",
        discouraged=(),
        history_lines=(),
        validator=validator,
    )
    assert proposal.action == "PRESS_B"
    assert "json_in_message.thinking" not in proposal.metadata

    def post_thinking(path, body):
        return {"message": {"content": "", "thinking": '{"action":"WAIT","reason":"unsure"}'}}

    thinking = OllamaReasoningProvider(http_post=post_thinking)
    fallback = thinking.propose(
        context=observed.context,
        goal="Explore",
        stuck_state="NORMAL",
        discouraged=(),
        history_lines=(),
        validator=validator,
    )
    assert fallback.action == "WAIT"
    assert fallback.metadata == {"json_in_message.thinking": True}
    assert "hidden" not in fallback.reason.lower()


def test_gameboy_wait_ticks_without_button() -> None:
    emu = FakeEmulator()
    executor = GameBoyActionExecutor(emu, wait_frames=11)
    result = executor.execute(ActionProposal(action="WAIT", parameters={"frames": 7}, reason="idle"))
    assert result.ok
    assert emu.pressed == []
    assert emu.ticks == 7


def test_executor_unsupported_action_raises() -> None:
    emu = FakeEmulator()
    executor = GameBoyActionExecutor(emu)
    with pytest.raises(InvalidActionError):
        executor.execute(ActionProposal(action="USE_POTION", reason="no"))


def test_reobserve_failure_is_recorded() -> None:
    class BoomSecond:
        def __init__(self) -> None:
            self.calls = 0
            self.first = _observed()

        def observe(self) -> ObservedState:
            self.calls += 1
            if self.calls >= 2:
                raise RuntimeError("vision confidence")
            return self.first

    executor = RecordingExecutor()
    loop = _loop(observer=BoomSecond(), executor=executor, max_steps=1)
    result = loop.run()
    assert executor.calls == ["MOVE_UP"]
    assert result.steps[0].executed is True
    assert "PerceptionFailedError" in result.steps[0].error
    assert result.steps[0].progress is False
    assert result.steps[0].movement_outcome == "UNCERTAIN"


TOKEN = "map=38:x=1:y=2:mode=OVERWORLD:battle=False"
THINKING_SENTINEL = "PRIVATE_COT_SENTINEL_9f3c_DO_NOT_STORE"


def test_ai_control_may_execute() -> None:
    executor = RecordingExecutor()
    loop = _loop(
        observer=SequenceObserver([_observed(), _observed(digest="bbb")]),
        executor=executor,
        ownership=ControlGate(ControlOwner.AI_CONTROL),
        max_steps=1,
    )
    result = loop.run()
    assert executor.calls == ["MOVE_UP"]
    assert result.steps[0].executed is True


def test_conversation_emits_no_gameplay_action() -> None:
    executor = RecordingExecutor()
    loop = _loop(
        executor=executor,
        ownership=ControlGate(ControlOwner.CONVERSATION),
        max_steps=1,
    )
    result = loop.run()
    assert executor.calls == []
    assert result.steps[0].executed is False
    assert "OwnershipDeniedError" in result.steps[0].error


def test_stale_proposal_denied_if_owner_changes_during_reason() -> None:
    ownership = ControlGate(ControlOwner.AI_CONTROL)
    executor = RecordingExecutor()

    class FlipOwner:
        def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
            ownership.set_owner(ControlOwner.USER_CONTROL)
            return validator.parse_and_validate({"action": "MOVE_UP", "reason": "stale"})

    loop = _loop(
        observer=SequenceObserver([_observed(), _observed(digest="bbb")]),
        reasoner=FlipOwner(),
        executor=executor,
        ownership=ownership,
        max_steps=1,
    )
    result = loop.run()
    assert executor.calls == []
    assert result.steps[0].validation_ok is True
    assert result.steps[0].executed is False
    assert "OwnershipDeniedError" in result.steps[0].error


def test_executor_exception_releases_input() -> None:
    class BoomTick(FakeEmulator):
        def tick(self, count: int = 1, *, render: bool = True) -> bool:
            raise RuntimeError("tick failed")

    emu = BoomTick()
    executor = GameBoyActionExecutor(emu, tap_frames=2, settle_frames=3)
    with pytest.raises(ExecutionFailedError):
        executor.execute(ActionProposal(action="MOVE_UP", reason="go"))
    assert emu.pressed == ["up"]
    assert emu.held == []
    assert {str(item) for item in emu.released} >= {"up", "down", "left", "right", "a", "b", "start", "select"}


def test_unknown_model_fields_are_rejected() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    with pytest.raises(MalformedProposalError):
        validator.parse_and_validate(
            {"action": "WAIT", "reason": "x", "scratch": "nope", "confidence": 0.1}
        )
    proposal = validator.parse_and_validate({"action": "WAIT", "reason": "x"})
    assert proposal.metadata == {}


def test_non_finite_action_confidence_rejected() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    with pytest.raises(MalformedProposalError):
        validator.parse_and_validate({"action": "WAIT", "reason": "x", "confidence": float("nan")})
    with pytest.raises(MalformedProposalError):
        validator.parse_and_validate({"action": "WAIT", "reason": "x", "confidence": float("inf")})
    with pytest.raises(MalformedProposalError):
        validator.parse_and_validate({"action": "WAIT", "reason": "x", "confidence": float("-inf")})
    with pytest.raises(MalformedProposalError):
        validator.parse_and_validate('{"action":"WAIT","reason":"x","confidence":NaN}')
    with pytest.raises(MalformedProposalError):
        validator.parse_and_validate('{"action":"WAIT","reason":"x","confidence":Infinity}')
    with pytest.raises(MalformedProposalError):
        validator.parse_and_validate('{"action":"WAIT","reason":"x","confidence":-Infinity}')


def test_duplicate_action_key_in_raw_json_rejected() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    with pytest.raises(MalformedProposalError):
        validator.parse_and_validate('{"action":"WAIT","action":"PRESS_A","reason":"x"}')


def test_pixel_digest_change_is_not_progress_when_token_stable() -> None:
    observer = SequenceObserver(
        [_observed(digest="aaa", token=TOKEN), _observed(digest="bbb", token=TOKEN)]
    )
    loop = _loop(observer=observer, max_steps=1)
    step = loop.run().steps[0]
    assert step.screen_changed is True
    assert step.state_changed is False
    assert step.progress is False
    assert step.before_fingerprint == step.after_fingerprint


def test_digest_flicker_with_stable_token_reaches_suspected_stuck() -> None:
    class Flicker:
        def __init__(self) -> None:
            self.calls = 0

        def observe(self) -> ObservedState:
            self.calls += 1
            return _observed(digest=f"pix{self.calls}", token=TOKEN)

    detector = StuckDetector(StuckConfig(unchanged_limit=2, same_action_limit=99, max_recovery_attempts=8))
    loop = _loop(
        observer=Flicker(),
        reasoner=ScriptedReasoner([{"action": "MOVE_UP", "reason": "wall"}] * 6),
        stuck=detector,
        max_steps=3,
    )
    result = loop.run()
    assert [item.progress for item in result.steps] == [False, False, False]
    assert all(item.screen_changed for item in result.steps)
    assert [item.stuck_state for item in result.steps] == [
        "NORMAL",
        "NORMAL",
        "SUSPECTED_STUCK",
    ]


def test_dialogue_text_change_is_progress_with_stable_token() -> None:
    observer = SequenceObserver(
        [
            _observed(digest="aaa", token=TOKEN, visible_text=("HELLO",)),
            _observed(digest="aaa", token=TOKEN, visible_text=("HELLO WORLD",)),
        ]
    )
    step = _loop(observer=observer, max_steps=1).run().steps[0]
    assert step.screen_changed is False
    assert step.state_changed is False
    assert step.progress is True


def test_structured_token_change_is_progress() -> None:
    observer = SequenceObserver(
        [
            _observed(digest="aaa", token=TOKEN),
            _observed(digest="aaa", token="map=39:x=1:y=2:mode=OVERWORLD:battle=False"),
        ]
    )
    step = _loop(observer=observer, max_steps=1).run().steps[0]
    assert step.state_changed is True
    assert step.progress is True
    assert step.screen_changed is False


def test_visual_only_description_change_on_same_frame_is_not_progress() -> None:
    observer = SequenceObserver(
        [
            _observed(digest="aaa", token=None, description="A quiet bedroom."),
            _observed(digest="aaa", token=None, description="An open doorway to the south."),
        ]
    )
    step = _loop(observer=observer, max_steps=1).run().steps[0]
    assert step.progress is False
    assert step.screen_changed is False
    assert step.state_changed is False
    assert step.before_fingerprint == step.after_fingerprint


def test_dialogue_caption_change_without_visible_text_is_progress() -> None:
    observer = SequenceObserver(
        [
            _observed(
                digest="aaa",
                token=TOKEN,
                visible_text=(),
                dialogue_visible=True,
                description="A figure stands above a box. The text reads: 'A world of dreams'",
            ),
            _observed(
                digest="aaa",
                token=TOKEN,
                visible_text=(),
                dialogue_visible=True,
                description="A figure stands above a box. The text reads: 'and adventures with'",
            ),
        ]
    )
    step = _loop(observer=observer, max_steps=1).run().steps[0]
    assert step.screen_changed is False
    assert step.state_changed is False
    assert step.progress is True


def test_overworld_description_jitter_is_not_progress() -> None:
    observer = SequenceObserver(
        [
            _observed(
                digest="aaa",
                token=TOKEN,
                dialogue_visible=False,
                menu_visible=False,
                description="A pixelated character wearing a cap and jacket stands in a room.",
            ),
            _observed(
                digest="bbb",
                token=TOKEN,
                dialogue_visible=False,
                menu_visible=False,
                description="A pixelated character with a cap, jacket, and pants stands in a room.",
            ),
        ]
    )
    step = _loop(observer=observer, max_steps=1).run().steps[0]
    assert step.screen_changed is True
    assert step.state_changed is False
    assert step.progress is False


def test_dialogue_press_a_does_not_false_stuck() -> None:
    lines = (
        "first line of dialogue",
        "second line of dialogue",
        "third line of dialogue",
        "fourth line of dialogue",
        "fifth line of dialogue",
        "sixth line of dialogue",
        "seventh line of dialogue",
        "eighth line of dialogue",
    )
    states = [
        _observed(
            digest=f"pix{index}",
            token=TOKEN,
            visible_text=(),
            dialogue_visible=True,
            description=f"A speaker is shown. The text reads: '{line}'",
        )
        for index, line in enumerate(lines)
    ]
    observer = SequenceObserver(states)
    detector = StuckDetector()
    loop = _loop(
        observer=observer,
        reasoner=ScriptedReasoner([{"action": "PRESS_A", "reason": "advance text"}] * 8),
        stuck=detector,
        max_steps=4,
    )
    result = loop.run()
    assert [item.proposal.action if item.proposal else None for item in result.steps] == ["PRESS_A"] * 4
    assert all(item.executed for item in result.steps)
    assert all(item.progress for item in result.steps)
    assert all(item.screen_changed for item in result.steps)
    assert all(not item.state_changed for item in result.steps)
    assert [item.stuck_state for item in result.steps] == ["NORMAL"] * 4


def test_thinking_fallback_does_not_leak_raw_thinking() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    observed = _observed()
    thinking = (
        f"{THINKING_SENTINEL} I would cheat via RAM if I could.\n"
        '{"action":"WAIT","reason":"validated-reason"}'
    )

    def post_thinking(path, body):
        return {"message": {"content": "", "thinking": thinking}}

    provider = OllamaReasoningProvider(http_post=post_thinking)
    proposal = provider.propose(
        context=observed.context,
        goal="Explore",
        stuck_state="NORMAL",
        discouraged=(),
        history_lines=(),
        validator=validator,
    )
    assert proposal.action == "WAIT"
    assert proposal.reason == "validated-reason"
    assert proposal.metadata == {"json_in_message.thinking": True}
    assert THINKING_SENTINEL not in str(proposal.metadata)
    assert THINKING_SENTINEL not in proposal.reason

    class ThinkingReasoner:
        def propose(self, **kwargs):
            return provider.propose(**kwargs)

    loop = _loop(
        observer=SequenceObserver([observed]),
        reasoner=ThinkingReasoner(),
        dry_run=True,
        max_steps=1,
    )
    result = loop.run()
    step = result.steps[0]
    rendered = format_step(step)
    lines = loop.history.action_lines()
    record = json.dumps(step_record(step))
    blob = "\n".join(
        [
            rendered,
            record,
            str(step),
            str(step.proposal),
            "\n".join(lines),
        ]
    )
    assert THINKING_SENTINEL not in blob
    assert "validated-reason" in rendered
    assert step.proposal is not None
    assert step.proposal.metadata == {"json_in_message.thinking": True}
