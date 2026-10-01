"""Generic M6 battle handling. Synthetic fixtures only."""

from __future__ import annotations

from memnara.agent.actions import ActionProposal, ActionRegistry, DEFAULT_GAMEPLAY_ACTIONS
from memnara.agent.battle import BATTLE_PROMPT_BLOCK, InteractionMode, derive_battle_view
from memnara.agent.exceptions import InvalidActionError
from memnara.agent.execute import ExecutionResult
from memnara.agent.loop import AgentLoop, format_step
from memnara.agent.observe import ObservedState, VisualOnlyObserver, fingerprint_context
from memnara.agent.ollama import OllamaReasoningProvider
from memnara.agent.ownership import ControlGate, ControlOwner
from memnara.agent.reasoning import SYSTEM_PROMPT, build_user_prompt
from memnara.agent.stuck import StuckConfig, StuckDetector
from memnara.agent.validator import ActionValidator
from memnara.perception.context import StructuredGameState
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


def _observed(*, digest: str = "aaa", token: str | None = None, game_state=None, **visual_kw) -> ObservedState:
    visual = None if visual_kw.get("visual_absent") else _visual(**{k: v for k, v in visual_kw.items() if k != "visual_absent"})
    context = fuse(visual=visual, game_state=game_state)
    return ObservedState(
        context=context,
        fingerprint=fingerprint_context(context, token),
        progress_token=token,
        screen_digest=digest,
        perception_ms=1.0,
        summary=compact_summary(context),
    )


def _battle(**visual_kw) -> ObservedState:
    visual_kw.setdefault("battle_visible", True)
    visual_kw.setdefault("scene_type", SceneType.UNKNOWN)
    visual_kw.setdefault("description", "A combat screen.")
    return _observed(**visual_kw)


class SequenceObserver:
    def __init__(self, states: list[ObservedState]) -> None:
        self.states = states
        self.calls = 0

    def observe(self) -> ObservedState:
        idx = min(self.calls, len(self.states) - 1)
        self.calls += 1
        return self.states[idx]


class ScriptedReasoner:
    def __init__(self, payloads: list) -> None:
        self.payloads = list(payloads)
        self.contexts = []

    def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
        self.contexts.append(context)
        raw = self.payloads.pop(0) if self.payloads else {"action": "WAIT", "reason": "fallback"}
        if isinstance(raw, Exception):
            raise raw
        return validator.parse_and_validate(raw)


class RecordingExecutor:
    def __init__(self, *, boom: bool = False) -> None:
        self.calls: list[str] = []
        self.released = 0
        self.boom = boom

    def execute(self, proposal) -> ExecutionResult:
        self.calls.append(proposal.action)
        if self.boom:
            raise RuntimeError("executor boom")
        return ExecutionResult(ok=True, executed=True, released=True)

    def release_all(self) -> None:
        self.released += 1


def _loop(**kwargs) -> AgentLoop:
    return AgentLoop(
        observer=kwargs.pop("observer", SequenceObserver([_observed()])),
        reasoner=kwargs.pop("reasoner", ScriptedReasoner([{"action": "PRESS_A", "reason": "advance"}])),
        validator=kwargs.pop("validator", ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))),
        executor=kwargs.pop("executor", RecordingExecutor()),
        ownership=kwargs.pop("ownership", ControlGate()),
        stuck=kwargs.pop("stuck", None),
        max_steps=kwargs.pop("max_steps", 1),
        max_consecutive_failures=kwargs.pop("max_consecutive_failures", 5),
        dry_run=kwargs.pop("dry_run", False),
    )


def _prompt_body(context) -> str:
    """The non-battle prompt body. Battle mode only prepends BATTLE_PROMPT_BLOCK."""
    summary = compact_summary(context)
    allowed_text = ", ".join(sorted(DEFAULT_GAMEPLAY_ACTIONS))
    return (
        f"GOAL: Advance\n"
        f"ALLOWED_ACTIONS: {allowed_text}\n"
        f"STUCK_STATE: NORMAL\n"
        f"DISCOURAGED_ACTIONS: (none)\n"
        f"RECENT_STEPS:\n(none)\n"
        f"CURRENT_EVIDENCE:\n{summary}\n"
        "Propose exactly one allowed action. For WAIT you may set parameters.frames (1-180). "
        "Other actions take no parameters."
    )


def _prompt(context) -> str:
    return build_user_prompt(
        context=context,
        goal="Advance",
        allowed=DEFAULT_GAMEPLAY_ACTIONS,
        stuck_state="NORMAL",
        discouraged=(),
        history_lines=(),
    )


def test_visual_only_battle_visible_activates_mode() -> None:
    view = derive_battle_view(_battle().context)
    assert view.mode is InteractionMode.BATTLE_ACTIVE
    assert view.visual_battle_visible is True
    assert view.structured_in_battle is None
    assert view.conflict_present is False


def test_visual_only_not_battle_stays_normal() -> None:
    view = derive_battle_view(_observed().context)
    assert view.mode is InteractionMode.NON_BATTLE
    assert view.visual_battle_visible is False


def test_scene_type_alone_does_not_activate_battle() -> None:
    context = _observed(scene_type=SceneType.BATTLE, battle_visible=False, description="Unclear.").context
    assert derive_battle_view(context).mode is InteractionMode.NON_BATTLE


def test_structured_battle_state_activates_without_visual() -> None:
    state = StructuredGameState(is_in_battle=True, is_in_battle_confidence="SOURCE_DOCUMENTED", adapter_id="generic")
    context = fuse(game_state=state)
    view = derive_battle_view(context)
    assert view.mode is InteractionMode.BATTLE_ACTIVE
    assert view.visual_battle_visible is None
    assert view.structured_in_battle is True


def test_structured_flag_enriches_visual_battle() -> None:
    state = StructuredGameState(is_in_battle=True, is_in_battle_confidence="VERIFIED")
    context = fuse(visual=_visual(battle_visible=True, scene_type=SceneType.UNKNOWN), game_state=state)
    view = derive_battle_view(context)
    assert view.mode is InteractionMode.BATTLE_ACTIVE
    assert view.visual_battle_visible is True
    assert view.structured_in_battle is True
    assert view.conflict_present is False
    assert context.conflicts == ()


def test_disagreement_preserves_m4_conflict_and_either_signal_activates() -> None:
    state = StructuredGameState(is_in_battle=False, is_in_battle_confidence="SOURCE_DOCUMENTED", source="RAM")
    visual = _visual(battle_visible=True, source="VISUAL")
    context = fuse(visual=visual, game_state=state)
    view = derive_battle_view(context)
    assert len(context.conflicts) == 1
    assert context.conflicts[0].concept == "battle"
    assert context.conflicts[0].left_value == "true"
    assert context.conflicts[0].right_value == "false"
    assert view.mode is InteractionMode.BATTLE_ACTIVE
    assert view.conflict_present is True
    assert view.visual_battle_visible is True
    assert view.structured_in_battle is False
    summary = compact_summary(context)
    assert "battle_visible=True" in summary
    assert "battle=false" in summary
    assert "CONFLICTS:" in summary


def test_battle_prompt_is_exactly_the_generic_block_plus_evidence() -> None:
    context = _battle(menu_visible=True, visible_text=("Confirm",), dialogue_visible=True).context
    battle = _prompt(context)
    assert battle == BATTLE_PROMPT_BLOCK + "\n" + _prompt_body(context)
    assert BATTLE_PROMPT_BLOCK == (
        "INTERACTION_MODE: BATTLE\n"
        "You are currently in a battle/combat interaction.\n"
        "Use only the visible/permitted information supplied.\n"
        "Choose ONE allowlisted action that safely advances or resolves the battle.\n"
        "Do not invent game-specific controls or mechanics.\n"
        "If a menu is visible, reason from the visible menu.\n"
        "If text/dialogue is visible, advance appropriately.\n"
        "If sources disagree, neither source is silently correct.\n"
        "If uncertain, choose a bounded safe exploratory action."
    )
    assert SYSTEM_PROMPT == (
        "You are Memnara, a local agent controlling a video game through a constrained action interface.\n"
        "\n"
        "Rules:\n"
        "- You receive fused current evidence (visual interpretation plus optional labeled game state).\n"
        "- Use only that evidence. Do not claim hidden knowledge, walkthroughs, memory addresses, or emulator internals.\n"
        "- Propose exactly ONE gameplay action from the allowed list.\n"
        "- Unsupported action names are invalid.\n"
        "- Uncertainty is acceptable. Prefer a short-term exploratory action over invented certainty.\n"
        "- Do not output multiple actions, scripts, shell commands, or code.\n"
        "- Do not write RAM or suggest privileged state.\n"
        "- Short reason only: why this one action might make progress.\n"
        "- If the scene looks like a menu or dialogue, PRESS_A or PRESS_B or WAIT may be more appropriate than walking.\n"
        "- If evidence shows a battle, you may still use generic buttons; you do not have battle strategy.\n"
        "- If the goal is to explore or move through terrain to trigger an encounter, prefer a movement action. Do not choose WAIT only because standing still might cause a movement-triggered encounter. WAIT remains valid when visible evidence shows waiting is useful, such as dialogue, a menu, or an animation that is still changing.\n"
        "- Recent steps report movement outcomes. MOVED means the attempted locomotion changed position. BLOCKED means there is strong evidence the position did not change: the whole frame was unchanged, or a structured navigation token stayed the same. If one direction repeatedly returns BLOCKED, prefer a different direction or another safe exploratory action. UNCERTAIN means movement success was not established. Do not treat a center animation, or UNCERTAIN, as proof the move worked. Repeated UNCERTAIN results without other progress are not a reason to keep using the same direction.\n"
        "- Do not assume a button confirms, cancels, attacks, selects, or navigates based only on conventions from other games. Use recent observed outcomes to infer which controls are effective in the current interaction. If an action repeatedly produces NO_EFFECT in an unchanged interaction, prefer a different safe action.\n"
        "\n"
        "Return JSON matching the schema: action, optional parameters, reason, optional confidence (0-1).\n"
    )
    normal = _prompt(_observed(dialogue_visible=True, scene_type=SceneType.UNKNOWN).context)
    assert normal == _prompt_body(_observed(dialogue_visible=True, scene_type=SceneType.UNKNOWN).context)
    assert "INTERACTION_MODE: BATTLE" not in normal


def test_ollama_battle_request_includes_battle_block_only_when_active() -> None:
    seen: list[dict] = []

    def post(path, body):
        seen.append(body)
        return {"message": {"content": '{"action":"PRESS_A","reason":"advance text"}'}}

    provider = OllamaReasoningProvider(http_post=post)
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    provider.propose(
        context=_battle().context,
        goal="Advance",
        stuck_state="NORMAL",
        discouraged=(),
        history_lines=(),
        validator=validator,
    )
    battle_context = _battle().context
    user = seen[0]["messages"][1]["content"]
    assert user == _prompt(battle_context)
    seen.clear()
    normal_context = _observed().context
    provider.propose(
        context=normal_context,
        goal="Advance",
        stuck_state="NORMAL",
        discouraged=(),
        history_lines=(),
        validator=validator,
    )
    assert seen[0]["messages"][1]["content"] == _prompt(normal_context)


def test_ownership_blocks_battle_except_ai_control() -> None:
    for owner in (ControlOwner.USER_CONTROL, ControlOwner.CONVERSATION, ControlOwner.PAUSED):
        executor = RecordingExecutor()
        step = _loop(
            observer=SequenceObserver([_battle(), _battle(digest="bbb")]),
            executor=executor,
            ownership=ControlGate(owner),
        ).run().steps[0]
        assert executor.calls == []
        assert step.executed is False
        assert "OwnershipDeniedError" in step.error
        assert step.interaction_mode == "BATTLE_ACTIVE"
    allowed = RecordingExecutor()
    step = _loop(
        observer=SequenceObserver([_battle(), _battle(digest="ccc")]),
        executor=allowed,
        ownership=ControlGate(ControlOwner.AI_CONTROL),
    ).run().steps[0]
    assert allowed.calls == ["PRESS_A"]
    assert step.executed is True


def test_owner_change_after_battle_proposal_blocks_execution() -> None:
    ownership = ControlGate(ControlOwner.AI_CONTROL)
    executor = RecordingExecutor()

    class Flip:
        def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
            ownership.set_owner(ControlOwner.USER_CONTROL)
            return validator.parse_and_validate({"action": "PRESS_A", "reason": "stale owner"})

    step = _loop(
        observer=SequenceObserver([_battle()]),
        reasoner=Flip(),
        executor=executor,
        ownership=ownership,
    ).run().steps[0]
    assert executor.calls == []
    assert step.validation_ok is True
    assert "OwnershipDeniedError" in step.error
    assert "StaleModeError" not in step.error


def test_non_battle_to_battle_and_exit_transitions() -> None:
    states = [
        _observed(digest="over"),
        _observed(digest="over2"),
        _battle(digest="bat"),
        _battle(digest="bat2"),
        _observed(digest="out", description="A field again."),
        _observed(digest="out2", description="A field again."),
    ]
    result = _loop(
        observer=SequenceObserver(states),
        reasoner=ScriptedReasoner([{"action": "MOVE_UP", "reason": "walk"}, {"action": "PRESS_A", "reason": "fight"}, {"action": "PRESS_A", "reason": "leave"}]),
        max_steps=3,
    ).run()
    modes = [item.interaction_mode for item in result.steps]
    assert modes == ["NON_BATTLE", "BATTLE_ACTIVE", "NON_BATTLE"]
    assert "TRANSITION" not in format_step(result.steps[0])
    entry = format_step(result.steps[1], previous_mode=result.steps[0].interaction_mode)
    exit_text = format_step(result.steps[2], previous_mode=result.steps[1].interaction_mode)
    assert "MODE BATTLE" in entry
    assert "TRANSITION entry" in entry
    assert "MODE NON_BATTLE" in exit_text
    assert "TRANSITION exit" in exit_text


def test_stale_battle_proposal_is_not_executed() -> None:
    executor = RecordingExecutor()
    battle = _battle()
    normal = _observed(description="Combat ended.")

    class ExitBeforeExecute(SequenceObserver):
        def confirm_execution(self, prior: ObservedState) -> ObservedState:
            assert prior.context.visual is not None
            assert prior.context.visual.battle_visible is True
            return normal

    step = _loop(
        observer=ExitBeforeExecute([battle]),
        executor=executor,
        max_consecutive_failures=1,
    ).run().steps[0]
    assert executor.calls == []
    assert step.executed is False
    assert step.execution_ok is False
    assert step.error == "StaleModeError: reasoned=BATTLE_ACTIVE confirmed=NON_BATTLE"
    assert step.interaction_mode == "BATTLE_ACTIVE"
    assert _loop(
        observer=ExitBeforeExecute([battle]),
        executor=RecordingExecutor(),
        max_steps=1,
        max_consecutive_failures=1,
    ).run().halt_reason == "max_steps"


def test_same_mode_confirm_still_executes() -> None:
    executor = RecordingExecutor()
    first = _battle(visible_text=("A",))
    later = _battle(digest="menu", visible_text=("B",), menu_visible=True)

    class SameMode(SequenceObserver):
        def confirm_execution(self, prior: ObservedState) -> ObservedState:
            return later

    step = _loop(observer=SameMode([first, later]), executor=executor).run().steps[0]
    assert executor.calls == ["PRESS_A"]
    assert step.executed is True


def test_dry_run_stale_mode_does_not_count_as_execution_policy_success() -> None:
    normal = _observed()
    battle = _battle()

    class Enter(SequenceObserver):
        def confirm_execution(self, prior: ObservedState) -> ObservedState:
            return battle

    step = _loop(observer=Enter([normal]), dry_run=True).run().steps[0]
    assert step.executed is False
    assert step.execution_ok is False
    assert step.error == "StaleModeError: reasoned=NON_BATTLE confirmed=BATTLE_ACTIVE"


def test_battle_animation_digest_is_not_progress() -> None:
    class Flicker:
        def __init__(self) -> None:
            self.calls = 0

        def observe(self) -> ObservedState:
            self.calls += 1
            return _battle(digest=f"pix{self.calls}", description="A combat screen.")

    detector = StuckDetector(StuckConfig(unchanged_limit=2, same_action_limit=99, max_recovery_attempts=8))
    result = _loop(
        observer=Flicker(),
        reasoner=ScriptedReasoner([{"action": "WAIT", "reason": "watch", "parameters": {"frames": 2}}] * 6),
        stuck=detector,
        max_steps=3,
    ).run()
    assert [item.progress for item in result.steps] == [False, False, False]
    assert all(item.screen_changed for item in result.steps)
    assert [item.stuck_state for item in result.steps] == ["NORMAL", "NORMAL", "SUSPECTED_STUCK"]


def test_battle_text_change_is_progress() -> None:
    observer = SequenceObserver(
        [
            _battle(visible_text=("Ready",), menu_visible=False, digest="same"),
            _battle(visible_text=("Choose",), menu_visible=False, digest="same"),
        ]
    )
    step = _loop(observer=observer).run().steps[0]
    assert step.progress is True
    assert step.screen_changed is False
    assert step.stuck_state == "NORMAL"
    assert step.interaction_mode == "BATTLE_ACTIVE"


def test_battle_menu_change_alone_is_progress() -> None:
    observer = SequenceObserver(
        [
            _battle(description="A combat screen.", visible_text=(), menu_visible=False, digest="same"),
            _battle(description="A combat screen.", visible_text=(), menu_visible=True, digest="same"),
        ]
    )
    step = _loop(observer=observer).run().steps[0]
    assert step.progress is True
    assert step.screen_changed is False


def test_structured_true_activates_when_visual_is_false() -> None:
    state = StructuredGameState(is_in_battle=True, is_in_battle_confidence="SOURCE_DOCUMENTED", source="RAM")
    context = fuse(visual=_visual(battle_visible=False, source="VISUAL"), game_state=state)
    view = derive_battle_view(context)
    assert context.conflicts[0].left_value == "false"
    assert context.conflicts[0].right_value == "true"
    assert view.mode is InteractionMode.BATTLE_ACTIVE
    assert view.conflict_present is True
    assert view.visual_battle_visible is False
    assert view.structured_in_battle is True


def test_battle_exit_is_progress() -> None:
    observer = SequenceObserver(
        [
            _battle(description="A quiet field.", scene_type=SceneType.UNKNOWN, digest="same"),
            _observed(
                description="A quiet field.",
                scene_type=SceneType.UNKNOWN,
                battle_visible=False,
                digest="same",
            ),
        ]
    )
    step = _loop(observer=observer).run().steps[0]
    assert step.progress is True
    assert step.interaction_mode == "BATTLE_ACTIVE"


def test_structured_token_change_during_battle_is_progress() -> None:
    observer = SequenceObserver(
        [
            _battle(token="phase=select"),
            _battle(token="phase=resolve", digest="aaa"),
        ]
    )
    step = _loop(observer=observer).run().steps[0]
    assert step.state_changed is True
    assert step.progress is True


def test_repeated_battle_stall_reaches_stuck_and_progress_resets() -> None:
    stalled = _battle(description="A combat screen.")
    advanced = _battle(description="A combat screen.", visible_text=("The exchange continues.",), digest="next")
    states = [stalled, stalled, stalled, stalled, stalled, stalled, stalled, advanced]
    detector = StuckDetector(StuckConfig(unchanged_limit=2, same_action_limit=99, max_recovery_attempts=8))
    result = _loop(
        observer=SequenceObserver(states),
        reasoner=ScriptedReasoner([{"action": "PRESS_A", "reason": "again"}] * 6),
        stuck=detector,
        max_steps=4,
    ).run()
    assert [item.stuck_state for item in result.steps] == [
        "NORMAL",
        "NORMAL",
        "SUSPECTED_STUCK",
        "NORMAL",
    ]
    assert result.steps[-1].progress is True


def test_loop_revalidates_unvalidated_battle_proposal() -> None:
    executor = RecordingExecutor()

    class Bypass:
        def propose(self, **kwargs):
            return ActionProposal(action="USE_MOVE_1", parameters={}, reason="bypass", confidence=None)

    step = _loop(
        observer=SequenceObserver([_battle()]),
        reasoner=Bypass(),
        executor=executor,
    ).run().steps[0]
    assert executor.calls == []
    assert step.validation_ok is False
    assert step.executed is False
    assert "InvalidActionError" in step.error


def test_structured_only_battle_prompt_is_the_battle_block() -> None:
    state = StructuredGameState(is_in_battle=True, is_in_battle_confidence="SOURCE_DOCUMENTED")
    context = fuse(game_state=state)
    assert _prompt(context) == BATTLE_PROMPT_BLOCK + "\n" + _prompt_body(context)


def test_visual_false_structured_true_prompt_is_the_battle_block() -> None:
    state = StructuredGameState(is_in_battle=True, is_in_battle_confidence="SOURCE_DOCUMENTED", source="RAM")
    context = fuse(visual=_visual(battle_visible=False, source="VISUAL"), game_state=state)
    assert derive_battle_view(context).mode is InteractionMode.BATTLE_ACTIVE
    assert _prompt(context) == BATTLE_PROMPT_BLOCK + "\n" + _prompt_body(context)


def test_structured_battle_sets_loop_mode_without_visual() -> None:
    state = StructuredGameState(is_in_battle=True, is_in_battle_confidence="SOURCE_DOCUMENTED")
    context = fuse(game_state=state)
    observed = ObservedState(
        context=context,
        fingerprint=fingerprint_context(context, None),
        progress_token=None,
        screen_digest="ram",
        perception_ms=1.0,
        summary=compact_summary(context),
    )
    step = _loop(observer=SequenceObserver([observed, observed]), dry_run=True).run().steps[0]
    assert step.interaction_mode == "BATTLE_ACTIVE"
    assert step.executed is False
    assert step.execution_ok is True


def test_malformed_battle_action_fails_closed() -> None:
    executor = RecordingExecutor()
    step = _loop(
        observer=SequenceObserver([_battle()]),
        reasoner=ScriptedReasoner([{"action": "USE_MOVE_1", "reason": "invented"}]),
        executor=executor,
    ).run().steps[0]
    assert executor.calls == []
    assert step.validation_ok is False
    assert step.executed is False
    assert "InvalidActionError" in step.error


def test_battle_executor_exception_releases_input() -> None:
    executor = RecordingExecutor(boom=True)
    step = _loop(observer=SequenceObserver([_battle()]), executor=executor).run().steps[0]
    assert executor.released == 1
    assert step.executed is False
    assert "RuntimeError" in step.error


def test_validator_rejects_unknown_battle_name() -> None:
    validator = ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS))
    try:
        validator.parse_and_validate({"action": "OPEN_BAG", "reason": "no"})
    except InvalidActionError:
        return
    raise AssertionError("unknown action was accepted")


def test_visual_only_confirm_does_not_capture_or_call_vision() -> None:
    class Boom:
        def capture_frame(self):
            raise AssertionError("frame")

        def observe(self, frame):
            raise AssertionError("vlm")

    prior = _battle()
    assert VisualOnlyObserver(Boom(), Boom()).confirm_execution(prior) is prior
