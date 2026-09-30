"""Post-M6 display wiring and progress semantics. Synthetic fixtures only."""

from __future__ import annotations

from memnara.agent.actions import ActionRegistry, DEFAULT_GAMEPLAY_ACTIONS
from memnara.agent.loop import AgentLoop
from memnara.agent.observe import ObservedState, fingerprint_context
from memnara.agent.ownership import ControlGate
from memnara.agent.reasoning import SYSTEM_PROMPT
from memnara.agent.stuck import StuckConfig, StuckDetector
from memnara.agent.validator import ActionValidator
from memnara.demo.autonomy import build_parser, controlled_window, wire_controlled_runtime
from memnara.emulators.gameplay import GameBoyActionExecutor
from memnara.emulators.pyboy_adapter import HEADLESS_PYBOY_WINDOW, VISIBLE_PYBOY_WINDOW, PyBoyAdapter
from memnara.perception.fusion import compact_summary, fuse
from memnara.perception.vision.models import SceneType, VisualObservation


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


def _state(*, digest: str = "aaa", token: str | None = None, **visual_kw) -> ObservedState:
    context = fuse(visual=_visual(**visual_kw))
    return ObservedState(
        context=context,
        fingerprint=fingerprint_context(context, token),
        progress_token=token,
        screen_digest=digest,
        perception_ms=1.0,
        summary=compact_summary(context),
    )


class SequenceObserver:
    def __init__(self, states: list[ObservedState]) -> None:
        self.states = states
        self.calls = 0

    def observe(self) -> ObservedState:
        item = self.states[min(self.calls, len(self.states) - 1)]
        self.calls += 1
        return item


class ScriptedReasoner:
    def __init__(self, action: str = "MOVE_RIGHT") -> None:
        self.action = action

    def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
        return validator.parse_and_validate({"action": self.action, "reason": "move"})


class RecordingExecutor:
    def execute(self, proposal):
        from memnara.agent.execute import ExecutionResult

        return ExecutionResult(ok=True, executed=True, released=True)

    def release_all(self) -> None:
        return None


def _step(before: ObservedState, after: ObservedState, *, action: str = "MOVE_RIGHT"):
    loop = AgentLoop(
        observer=SequenceObserver([before, after]),
        reasoner=ScriptedReasoner(action),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=RecordingExecutor(),
        ownership=ControlGate(),
        max_steps=1,
    )
    return loop.run().steps[0]


def test_default_window_stays_headless() -> None:
    args = build_parser().parse_args([])
    assert args.show_window is False
    assert controlled_window(show_window=False, configured=HEADLESS_PYBOY_WINDOW) == "null"
    adapter = PyBoyAdapter()
    assert adapter._window == HEADLESS_PYBOY_WINDOW


def test_show_window_requests_visible_pyboy_window() -> None:
    args = build_parser().parse_args(["--show-window"])
    assert args.show_window is True
    assert controlled_window(show_window=True, configured="null") == VISIBLE_PYBOY_WINDOW
    assert VISIBLE_PYBOY_WINDOW == "SDL2"


def test_show_window_uses_the_same_emulator_instance() -> None:
    created: list[PyBoyAdapter] = []

    def factory(window: str) -> PyBoyAdapter:
        adapter = PyBoyAdapter(window=window, sound_emulated=False)
        created.append(adapter)
        return adapter

    adapter = factory(controlled_window(show_window=True, configured="null"))
    observer, executor = wire_controlled_runtime(adapter, vision=object())
    assert len(created) == 1
    assert observer._emulator is adapter
    assert executor._emulator is adapter
    assert isinstance(executor, GameBoyActionExecutor)
    assert adapter._window == "SDL2"


def test_same_frame_rephrased_description_is_not_overworld_progress() -> None:
    step = _step(
        _state(digest="same", description="maze-like structure"),
        _state(digest="same", description="grid of mushroom-like objects"),
    )
    assert step.screen_changed is False
    assert step.state_changed is False
    assert step.progress is False
    assert step.before_fingerprint == step.after_fingerprint


def test_same_frame_without_semantic_change_is_not_progress() -> None:
    step = _step(_state(digest="same"), _state(digest="same"))
    assert step.screen_changed is False
    assert step.state_changed is False
    assert step.progress is False


def test_framebuffer_change_with_new_description_can_be_progress() -> None:
    step = _step(
        _state(digest="before", description="A closed room."),
        _state(digest="after", description="An open path to the north."),
    )
    assert step.screen_changed is True
    assert step.progress is True


def test_framebuffer_change_with_same_description_is_not_progress() -> None:
    step = _step(
        _state(digest="pix1", description="A combat screen.", battle_visible=True),
        _state(digest="pix2", description="A combat screen.", battle_visible=True),
    )
    assert step.screen_changed is True
    assert step.progress is False


def test_dialogue_text_change_remains_progress() -> None:
    step = _step(
        _state(digest="same", dialogue_visible=True, visible_text=("Hello",)),
        _state(digest="same", dialogue_visible=True, visible_text=("Hello there",)),
    )
    assert step.screen_changed is False
    assert step.progress is True


def test_menu_change_remains_progress() -> None:
    step = _step(
        _state(digest="same", menu_visible=False),
        _state(digest="same", menu_visible=True),
    )
    assert step.progress is True


def test_battle_entry_and_exit_remain_progress() -> None:
    entry = _step(
        _state(digest="same", battle_visible=False),
        _state(digest="same", battle_visible=True),
    )
    exit_step = _step(
        _state(digest="same", battle_visible=True, scene_type=SceneType.UNKNOWN),
        _state(digest="same", battle_visible=False, scene_type=SceneType.UNKNOWN),
    )
    assert entry.progress is True
    assert exit_step.progress is True


def test_structured_token_change_remains_progress() -> None:
    step = _step(
        _state(digest="same", token="phase=a"),
        _state(digest="same", token="phase=b", description="different wording"),
    )
    assert step.state_changed is True
    assert step.progress is True
    assert step.screen_changed is False


def test_repeated_unchanged_movement_can_escalate_stuck() -> None:
    # Six distinct wordings: each step observes before and after. Repeating the
    # last frame would let stuck escalate even if wording still changed the fingerprint.
    states = [
        _state(digest="wall", description=wording)
        for wording in (
            "maze-like structure",
            "grid of mushroom-like objects",
            "T-shaped blocks",
            "helmet and sword shapes",
            "a quiet room of tiles",
            "scattered block shapes",
        )
    ]
    assert len({item.fingerprint for item in states}) == 1
    detector = StuckDetector(StuckConfig(unchanged_limit=2, same_action_limit=99, max_recovery_attempts=8))
    loop = AgentLoop(
        observer=SequenceObserver(states),
        reasoner=ScriptedReasoner("MOVE_RIGHT"),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=RecordingExecutor(),
        ownership=ControlGate(),
        stuck=detector,
        max_steps=3,
    )
    result = loop.run()
    assert [item.progress for item in result.steps] == [False, False, False]
    assert [item.screen_changed for item in result.steps] == [False, False, False]
    assert all(item.before_fingerprint == item.after_fingerprint for item in result.steps)
    assert len({item.after_fingerprint for item in result.steps}) == 1
    assert result.steps[-1].stuck_state == "SUSPECTED_STUCK"


def test_meaningful_progress_resets_stuck_after_blocked_movement() -> None:
    blocked = _state(digest="wall", description="A wall.")
    moved = _state(digest="moved", description="A new opening.")
    states = [blocked, blocked, blocked, blocked, blocked, blocked, blocked, moved]
    detector = StuckDetector(StuckConfig(unchanged_limit=2, same_action_limit=99, max_recovery_attempts=8))
    loop = AgentLoop(
        observer=SequenceObserver(states),
        reasoner=ScriptedReasoner("MOVE_RIGHT"),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=RecordingExecutor(),
        ownership=ControlGate(),
        stuck=detector,
        max_steps=4,
    )
    result = loop.run()
    assert result.steps[2].stuck_state == "SUSPECTED_STUCK"
    assert result.steps[3].progress is True
    assert result.steps[3].stuck_state == "NORMAL"


def test_encounter_goal_does_not_treat_waiting_as_movement() -> None:
    text = SYSTEM_PROMPT.lower()
    assert "prefer a movement action" in text
    assert "standing still might cause a movement-triggered encounter" in text
    assert "wait remains valid" in text


def test_wait_remains_a_legal_action() -> None:
    assert "WAIT" in DEFAULT_GAMEPLAY_ACTIONS
    proposal = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)).parse_and_validate(
        {"action": "WAIT", "reason": "dialogue is still printing", "parameters": {"frames": 8}}
    )
    assert proposal.action == "WAIT"
