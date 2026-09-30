"""Movement outcome, stuck recovery, and bounded history. Synthetic frames only."""

from __future__ import annotations

from pathlib import Path

from memnara.agent.actions import ActionRegistry, DEFAULT_GAMEPLAY_ACTIONS
from memnara.agent.battle import InteractionMode, derive_battle_view
from memnara.agent.history import StepHistory
from memnara.agent.loop import AgentLoop, format_step
from memnara.agent.movement import (
    MovementOutcome,
    classify_movement,
    frame_signature,
    read_navigation_token,
)
from memnara.agent.observe import ObservedState, VisualOnlyObserver, digest_pixels, fingerprint_context
from memnara.agent.ownership import ControlGate, ControlOwner
from memnara.agent.reasoning import SYSTEM_PROMPT, build_user_prompt
from memnara.agent.stuck import StuckConfig, StuckDetector
from memnara.agent.validator import ActionValidator
from memnara.demo.autonomy import build_parser, controlled_window, step_record
from memnara.emulators.base import Framebuffer
from memnara.emulators.pyboy_adapter import VISIBLE_PYBOY_WINDOW
from memnara.perception.context import StructuredFact, StructuredGameState
from memnara.perception.fusion import compact_summary, fuse
from memnara.perception.vision.models import SceneType, VisualObservation

WIDTH = 24
HEIGHT = 16


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


def _rgb(width: int, height: int, value_at) -> bytes:
    raw = bytearray()
    for y in range(height):
        for x in range(width):
            value = value_at(x, y) & 255
            raw.extend((value, value, value))
    return bytes(raw)


def _base_frame() -> bytes:
    return _rgb(WIDTH, HEIGHT, lambda x, _y: x * 10)


def _shifted_frame(dx: int) -> bytes:
    def paint(x, y):
        source = x - dx
        if source < 0 or source >= WIDTH:
            return 0
        return source * 10

    return _rgb(WIDTH, HEIGHT, paint)


def _vertical_frame(height: int, dy: int) -> bytes:
    def paint(x, y):
        source = y - dy
        if source < 0 or source >= height:
            return 0
        return source * 10

    return _rgb(WIDTH, height, paint)


def _bumped_frame(fill: int) -> bytes:
    raw = bytearray(_base_frame())
    x0, x1 = WIDTH // 4, WIDTH - WIDTH // 4
    y0, y1 = HEIGHT // 4, HEIGHT - HEIGHT // 4
    for y in range(y0, y1):
        for x in range(x0, x1):
            index = (y * WIDTH + x) * 3
            raw[index : index + 3] = bytes((fill, fill, fill))
    return bytes(raw)


def _speckled_frame() -> bytes:
    raw = bytearray(_base_frame())
    for x, value in ((0, 255), (3, 0), (20, 255)):
        for y in range(HEIGHT):
            index = (y * WIDTH + x) * 3
            raw[index : index + 3] = bytes((value, value, value))
    return bytes(raw)


def _state(pixels: bytes, *, description: str = "A generic field.", token: str | None = None, navigation: str | None = None, **visual_kw) -> ObservedState:
    context = fuse(visual=_visual(description=description, **visual_kw))
    scene = frame_signature(pixels, WIDTH, HEIGHT, "RGB")
    return ObservedState(
        context=context,
        fingerprint=fingerprint_context(context, token),
        progress_token=token,
        screen_digest=digest_pixels(pixels),
        perception_ms=1.0,
        summary=compact_summary(context),
        scene=scene,
        navigation_token=navigation,
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
    def __init__(self, actions: list[str] | str) -> None:
        self.actions = [actions] if isinstance(actions, str) else list(actions)
        self.index = 0
        self.history: list[tuple[str, ...]] = []
        self.discouraged: list[tuple[str, ...]] = []

    def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
        self.history.append(history_lines)
        self.discouraged.append(tuple(discouraged))
        action = self.actions[min(self.index, len(self.actions) - 1)]
        self.index += 1
        return validator.parse_and_validate({"action": action, "reason": "try"})


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, proposal):
        from memnara.agent.execute import ExecutionResult

        self.calls.append(proposal.action)
        return ExecutionResult(ok=True, executed=True, released=True)

    def release_all(self) -> None:
        return None


def _run(states: list[ObservedState], action: str = "MOVE_RIGHT", **kwargs) -> AgentLoop:
    reasoner = kwargs.pop("reasoner", ScriptedReasoner(action))
    loop = AgentLoop(
        observer=kwargs.pop("observer", SequenceObserver(states)),
        reasoner=reasoner,
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=kwargs.pop("executor", RecordingExecutor()),
        ownership=kwargs.pop("ownership", ControlGate()),
        stuck=kwargs.pop("stuck", StuckDetector()),
        max_steps=kwargs.pop("max_steps", 1),
    )
    loop.run()
    return loop


def _rgba(width: int, height: int, value_at) -> bytes:
    raw = bytearray()
    for y in range(height):
        for x in range(width):
            value = value_at(x, y) & 255
            raw.extend((value, value, value, 255))
    return bytes(raw)


def _native_frame(shift_x: int) -> bytes:
    width, height = 160, 144

    def paint(x, _y):
        source = x - shift_x
        if source < 0 or source >= width:
            return 0
        return (source * 3) & 255

    return _rgba(width, height, paint)


def _native_bump(pixels: bytes) -> bytes:
    width, height = 160, 144
    raw = bytearray(pixels)
    x0, x1 = width // 4, width - width // 4
    y0, y1 = height // 4, height - height // 4
    for y in range(y0, y1):
        for x in range(x0, x1):
            index = (y * width + x) * 4
            raw[index : index + 3] = b"\xff\xff\xff"
    return bytes(raw)


def test_native_framebuffer_scroll_is_moved_and_center_change_is_uncertain() -> None:
    before = _native_frame(0)
    scrolled = _native_frame(16)
    bumped = _native_bump(before)
    moved = classify_movement(
        action="MOVE_RIGHT",
        executed=True,
        navigation_before=None,
        navigation_after=None,
        scene_before=frame_signature(before, 160, 144, "RGBA"),
        scene_after=frame_signature(scrolled, 160, 144, "RGBA"),
    )
    uncertain = classify_movement(
        action="MOVE_RIGHT",
        executed=True,
        navigation_before=None,
        navigation_after=None,
        scene_before=frame_signature(before, 160, 144, "RGBA"),
        scene_after=frame_signature(bumped, 160, 144, "RGBA"),
    )
    assert moved is MovementOutcome.MOVED
    assert uncertain is MovementOutcome.UNCERTAIN


def test_scene_shift_is_moved() -> None:
    step = _run([_state(_base_frame()), _state(_shifted_frame(1))]).history.items[0]
    assert step.movement_outcome == MovementOutcome.MOVED.value
    assert step.screen_changed is True
    assert step.progress is True


def test_vertical_scene_shift_is_moved() -> None:
    height = 24
    before = _vertical_frame(height, 0)
    after = _vertical_frame(height, 1)
    outcome = classify_movement(
        action="MOVE_UP",
        executed=True,
        navigation_before=None,
        navigation_after=None,
        scene_before=frame_signature(before, WIDTH, height, "RGB"),
        scene_after=frame_signature(after, WIDTH, height, "RGB"),
    )
    assert outcome is MovementOutcome.MOVED


def test_identical_frame_after_move_is_blocked() -> None:
    frame = _base_frame()
    step = _run([_state(frame), _state(frame)]).history.items[0]
    assert step.screen_changed is False
    assert step.movement_outcome == MovementOutcome.BLOCKED.value
    assert step.progress is False


def test_center_only_change_is_uncertain_and_not_progress() -> None:
    step = _run(
        [
            _state(_base_frame(), description="maze-like structure"),
            _state(_bumped_frame(255), description="grid of mushroom-like objects"),
        ]
    ).history.items[0]
    assert step.screen_changed is True
    assert step.state_changed is False
    assert step.movement_outcome == MovementOutcome.UNCERTAIN.value
    assert step.progress is False
    rendered = format_step(step)
    assert "movement=UNCERTAIN" in rendered
    assert "progress=False" in rendered


def test_fixed_camera_shift_inside_the_center_is_not_blocked() -> None:
    """Actor relocates inside the central window. The border stays put."""

    def placed(offset: int) -> bytes:
        raw = bytearray(_base_frame())
        x0 = WIDTH // 4 + 1 + offset
        y0 = HEIGHT // 4 + 1
        for y in range(y0, y0 + 2):
            for x in range(x0, x0 + 2):
                index = (y * WIDTH + x) * 3
                raw[index : index + 3] = b"\xff\xff\xff"
        return bytes(raw)

    before_pixels = placed(0)
    after_pixels = placed(3)
    before_scene = frame_signature(before_pixels, WIDTH, HEIGHT, "RGB")
    after_scene = frame_signature(after_pixels, WIDTH, HEIGHT, "RGB")
    assert before_scene is not None and after_scene is not None
    assert before_scene.border_digest == after_scene.border_digest
    assert before_scene.center_digest != after_scene.center_digest
    step = _run([_state(before_pixels), _state(after_pixels)]).history.items[0]
    assert step.screen_changed is True
    assert step.movement_outcome == MovementOutcome.UNCERTAIN.value
    assert step.movement_outcome != MovementOutcome.BLOCKED.value
    assert step.progress is False


def test_ambiguous_scene_change_is_uncertain_and_not_progress() -> None:
    step = _run([_state(_base_frame()), _state(_speckled_frame(), description="a different caption")]).history.items[0]
    assert step.screen_changed is True
    assert step.movement_outcome == MovementOutcome.UNCERTAIN.value
    assert step.progress is False


def test_non_movement_actions_are_not_applicable() -> None:
    pixels = (_base_frame(), _bumped_frame(180))
    for action in ("PRESS_A", "PRESS_B", "PRESS_START", "PRESS_SELECT", "WAIT"):
        step = _run([_state(pixels[0]), _state(pixels[1])], action=action).history.items[0]
        assert step.movement_outcome == MovementOutcome.NOT_APPLICABLE.value


def test_navigation_token_change_is_moved() -> None:
    context_before = fuse(
        visual=_visual(),
        game_state=StructuredGameState(
            facts=(
                StructuredFact(key="position_token", value="alpha", source="RAM", confidence="VERIFIED"),
                StructuredFact(key="unrelated_fact", value="ignore", source="RAM", confidence="VERIFIED"),
            )
        ),
    )
    context_after = fuse(
        visual=_visual(),
        game_state=StructuredGameState(
            facts=(StructuredFact(key="position_token", value="beta", source="RAM", confidence="VERIFIED"),)
        ),
    )
    assert read_navigation_token(context_before) == "position_token=alpha"
    before = _state(_bumped_frame(10), navigation=read_navigation_token(context_before))
    after = _state(_bumped_frame(10), navigation=read_navigation_token(context_after))
    step = _run([before, after]).history.items[0]
    assert step.movement_outcome == MovementOutcome.MOVED.value
    assert step.progress is True


def test_stable_navigation_token_overrides_a_scene_shift() -> None:
    before = _state(_base_frame(), navigation="position_token=alpha")
    after = _state(_shifted_frame(1), navigation="position_token=alpha")
    step = _run([before, after]).history.items[0]
    assert step.screen_changed is True
    assert step.movement_outcome == MovementOutcome.BLOCKED.value
    assert step.progress is False


def test_stable_navigation_token_with_animation_is_blocked() -> None:
    before = _state(_base_frame(), navigation="position_token=alpha")
    after = _state(_bumped_frame(240), navigation="position_token=alpha")
    step = _run([before, after]).history.items[0]
    assert step.screen_changed is True
    assert step.movement_outcome == MovementOutcome.BLOCKED.value
    assert step.progress is False


def test_dialogue_menu_and_battle_progress_stay_independent_of_movement() -> None:
    blocked = (_base_frame(), _bumped_frame(220))
    dialogue = _run(
        [
            _state(blocked[0], dialogue_visible=True, visible_text=("Hello",)),
            _state(blocked[1], dialogue_visible=True, visible_text=("Hello there",)),
        ]
    ).history.items[0]
    menu = _run(
        [
            _state(blocked[0], menu_visible=False),
            _state(blocked[1], menu_visible=True),
        ]
    ).history.items[0]
    entry = _run(
        [
            _state(blocked[0], battle_visible=False),
            _state(blocked[1], battle_visible=True),
        ]
    ).history.items[0]
    assert dialogue.movement_outcome == MovementOutcome.UNCERTAIN.value
    assert dialogue.progress is True
    assert menu.movement_outcome == MovementOutcome.UNCERTAIN.value
    assert menu.progress is True
    assert entry.movement_outcome == MovementOutcome.UNCERTAIN.value
    assert entry.progress is True
    assert derive_battle_view(_state(blocked[1], battle_visible=True).context).mode is InteractionMode.BATTLE_ACTIVE


def test_battle_exit_and_structured_token_still_progress() -> None:
    exit_step = _run(
        [
            _state(_base_frame(), battle_visible=True, scene_type=SceneType.UNKNOWN),
            _state(_base_frame(), battle_visible=False, scene_type=SceneType.UNKNOWN),
        ],
        action="PRESS_A",
    ).history.items[0]
    token_step = _run(
        [
            _state(_bumped_frame(10), token="phase=a", navigation="position_token=alpha"),
            _state(_bumped_frame(10), token="phase=b", navigation="position_token=alpha"),
        ]
    ).history.items[0]
    assert exit_step.progress is True
    assert exit_step.movement_outcome == MovementOutcome.NOT_APPLICABLE.value
    assert token_step.state_changed is True
    assert token_step.progress is True
    assert token_step.movement_outcome == MovementOutcome.BLOCKED.value


def test_repeated_uncertain_direction_escalates_stuck_and_discourages_it() -> None:
    states = [_state(_bumped_frame(200 + index), description=f"wording {index}") for index in range(8)]
    reasoner = ScriptedReasoner("MOVE_RIGHT")
    detector = StuckDetector(StuckConfig(unchanged_limit=9, same_action_limit=3, max_recovery_attempts=8))
    loop = _run(states, reasoner=reasoner, stuck=detector, max_steps=4)
    steps = loop.history.items
    assert [item.movement_outcome for item in steps] == ["UNCERTAIN"] * 4
    assert [item.progress for item in steps] == [False] * 4
    assert all(item.screen_changed for item in steps)
    assert steps[2].stuck_state == "SUSPECTED_STUCK"
    assert steps[3].stuck_state == "CHANGE_STRATEGY"
    assert "MOVE_RIGHT" in reasoner.discouraged[-1]


def test_alternating_uncertain_directions_still_accumulate_no_progress() -> None:
    states = [_state(_bumped_frame(180 + index)) for index in range(6)]
    detector = StuckDetector(StuckConfig(unchanged_limit=2, same_action_limit=99, max_recovery_attempts=8))
    reasoner = ScriptedReasoner(["MOVE_RIGHT", "MOVE_UP", "MOVE_LEFT"])
    steps = _run(states, reasoner=reasoner, stuck=detector, max_steps=3).history.items
    assert [item.movement_outcome for item in steps] == ["UNCERTAIN"] * 3
    assert [item.progress for item in steps] == [False] * 3
    assert steps[-1].stuck_state == "SUSPECTED_STUCK"


def test_moved_after_blocks_resets_stuck() -> None:
    uncertain = [_state(_bumped_frame(200 + index)) for index in range(6)]
    detector = StuckDetector(StuckConfig(unchanged_limit=2, same_action_limit=99, max_recovery_attempts=8))
    steps = _run(
        uncertain + [_state(_base_frame()), _state(_shifted_frame(1), description="The scene has shifted.")],
        stuck=detector,
        max_steps=4,
    ).history.items
    assert [item.movement_outcome for item in steps[:3]] == ["UNCERTAIN"] * 3
    assert steps[2].stuck_state == "SUSPECTED_STUCK"
    assert steps[3].movement_outcome == MovementOutcome.MOVED.value
    assert steps[3].progress is True
    assert steps[3].stuck_state == "NORMAL"


def test_recent_uncertain_outcomes_are_bounded_history() -> None:
    states = [_state(_bumped_frame(190 + index)) for index in range(12)]
    reasoner = ScriptedReasoner("MOVE_RIGHT")
    loop = _run(states, reasoner=reasoner, max_steps=6)
    assert reasoner.history[1] == ("MOVE_RIGHT → UNCERTAIN",)
    assert len(loop.history.action_lines()) == 4
    assert loop.history.action_lines()[-1] == "MOVE_RIGHT → UNCERTAIN"
    assert len(loop.history.items) == 6
    prompt = build_user_prompt(
        context=states[0].context,
        goal="Explore",
        allowed=DEFAULT_GAMEPLAY_ACTIONS,
        stuck_state="NORMAL",
        discouraged=("MOVE_RIGHT",),
        history_lines=loop.history.action_lines(),
    )
    assert "MOVE_RIGHT → UNCERTAIN" in prompt
    assert "movement success was not established" in SYSTEM_PROMPT
    assert "prefer a different direction" in SYSTEM_PROMPT
    history = StepHistory(maxlen=2)
    for item in loop.history.items:
        history.append(item)
    assert len(history.items) == 2
    source = Path(__file__).resolve().parents[1].joinpath("src/memnara/agent/movement.py").read_text(encoding="utf-8")
    assert "sqlite" not in source
    assert "open(" not in source


def test_evidence_records_movement_outcome() -> None:
    step = _run([_state(_base_frame()), _state(_bumped_frame(255))]).history.items[0]
    record = step_record(step)
    assert record["movement_outcome"] == "UNCERTAIN"
    assert "screen_changed" in record
    assert "state_changed" in record


def test_malformed_action_fails_closed() -> None:
    class BadReasoner:
        def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
            return validator.parse_and_validate({"action": "JUMP", "reason": "no"})

    step = _run([_state(_base_frame())], reasoner=BadReasoner(), max_steps=1).history.items[0]
    assert step.validation_ok is False
    assert step.executed is False
    assert step.movement_outcome == MovementOutcome.NOT_APPLICABLE.value
    assert "InvalidActionError" in step.error


def test_ownership_still_blocks_execution() -> None:
    executor = RecordingExecutor()
    step = _run(
        [_state(_base_frame()), _state(_shifted_frame(1))],
        executor=executor,
        ownership=ControlGate(ControlOwner.PAUSED),
    ).history.items[0]
    assert executor.calls == []
    assert step.executed is False
    assert "OwnershipDeniedError" in step.error
    assert step.movement_outcome == MovementOutcome.NOT_APPLICABLE.value


def test_stale_proposal_is_not_executed() -> None:
    battle = _state(_base_frame(), battle_visible=True)
    calm = _state(_base_frame(), battle_visible=False)

    class ExitBattle(SequenceObserver):
        def confirm_execution(self, prior: ObservedState) -> ObservedState:
            return calm

    executor = RecordingExecutor()
    step = _run([battle, calm], observer=ExitBattle([battle, calm]), executor=executor).history.items[0]
    assert executor.calls == []
    assert step.executed is False
    assert step.error.startswith("StaleModeError")
    assert step.movement_outcome == MovementOutcome.NOT_APPLICABLE.value


def test_show_window_wiring_is_unchanged() -> None:
    args = build_parser().parse_args(["--show-window"])
    assert args.show_window is True
    assert controlled_window(show_window=True, configured="null") == VISIBLE_PYBOY_WINDOW
    assert controlled_window(show_window=False, configured="null") == "null"


def test_signature_uses_the_frame_already_captured() -> None:
    class OneShot:
        def capture_frame(self) -> Framebuffer:
            return Framebuffer(WIDTH, HEIGHT, "RGB", _bumped_frame(255), "synthetic")

    class Vision:
        def __init__(self) -> None:
            self.calls = 0

        def observe(self, frame: Framebuffer) -> VisualObservation:
            self.calls += 1
            return _visual()

    vision = Vision()
    observed = VisualOnlyObserver(OneShot(), vision).observe()
    assert vision.calls == 1
    assert observed.scene is not None
    assert observed.navigation_token is None
