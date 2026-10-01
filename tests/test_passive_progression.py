"""Post-M6 passive runtime progression. Synthetic frames only. No model per pumped frame."""

from __future__ import annotations

import threading

from memnara.agent.actions import DEFAULT_GAMEPLAY_ACTIONS, ActionRegistry
from memnara.agent.exceptions import MalformedProposalError
from memnara.agent.execute import ExecutionResult
from memnara.agent.loop import AgentLoop, format_step
from memnara.agent.observe import VisualOnlyObserver
from memnara.agent.ownership import ControlGate, ControlOwner
from memnara.agent.readiness import PASSIVE_GUIDANCE, frames_meaningfully_changed
from memnara.agent.reasoning import SYSTEM_PROMPT
from memnara.agent.validator import ActionValidator
from memnara.demo.autonomy import step_record
from memnara.emulators.base import Framebuffer
from memnara.perception.vision.models import SceneType, VisualObservation

W = 16
H = 16


def _paint(mark: int) -> bytes:
    raw = bytearray()
    for y in range(H):
        for x in range(W):
            value = (x * 17 + y * 9 + mark * 13) % 256
            raw.extend((value, (value + 40) % 256, (value + 90) % 256))
    return bytes(raw)


def _frame(pixels: bytes) -> Framebuffer:
    return Framebuffer(W, H, "RGB", pixels, "synthetic")


def _visual(text: str, *, battle: bool = False) -> VisualObservation:
    return VisualObservation(
        scene_type=SceneType.MENU,
        description=text,
        visible_text=(text,),
        entities=(),
        menu_visible=True,
        dialogue_visible=False,
        battle_visible=battle,
        confidence=0.9,
        notable_changes="",
        source="VISUAL",
        model="qwen3-vl:8b",
    )


class Reel:
    """Menu pixels stay put until a button press starts the automatic reel."""

    def __init__(self, anim_marks: list[int], *, final_mark: int, menu_mark: int = 1, autostart: bool = False) -> None:
        self.menu = _paint(menu_mark)
        self.final = _paint(final_mark)
        self.anim = [_paint(mark) for mark in anim_marks]
        self.phase = "anim" if autostart else "menu"
        self.anim_i = 0
        self.ticks = 0
        self.presses: list[str] = []

    def current(self) -> bytes:
        if self.phase == "menu":
            return self.menu
        if self.phase == "final":
            return self.final
        return self.anim[min(self.anim_i, len(self.anim) - 1)]

    def capture_frame(self) -> Framebuffer:
        return _frame(self.current())

    def tick(self, count: int = 1, *, render: bool = True) -> bool:
        self.ticks += count
        for _ in range(count):
            if self.phase != "anim":
                continue
            self.anim_i += 1
            if self.anim_i >= len(self.anim):
                self.phase = "final"
        return True

    def press_button(self, button, *, delay_frames: int = 1) -> None:
        self.presses.append(str(button))
        if self.phase == "menu":
            self.phase = "anim"
            self.anim_i = 0


class AlwaysChanging:
    def __init__(self) -> None:
        self.ticks = 0
        self.presses: list[str] = []

    def capture_frame(self) -> Framebuffer:
        return _frame(_paint(self.ticks + 3))

    def tick(self, count: int = 1, *, render: bool = True) -> bool:
        self.ticks += count
        return True

    def press_button(self, button, *, delay_frames: int = 1) -> None:
        self.presses.append(str(button))


class Vision:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.calls = 0
        self.phases: list[str] = []

    def observe(self, frame) -> VisualObservation:
        self.calls += 1
        phase = getattr(self.runtime, "phase", "moving")
        self.phases.append(phase)
        if phase == "final":
            return _visual("FINAL MENU", battle=True)
        if phase == "menu":
            return _visual("ACTIONABLE MENU", battle=True)
        return _visual(f"MID {phase}", battle=False)


class Reasoner:
    def __init__(self, runtime=None, *, mutate=False) -> None:
        self.runtime = runtime
        self.mutate = mutate
        self.calls = 0
        self.lines: list[tuple[str, ...]] = []
        self.texts: list[tuple[str, ...]] = []

    def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
        self.calls += 1
        self.lines.append(tuple(history_lines))
        visual = context.visual
        self.texts.append(tuple(visual.visible_text) if visual else ())
        if self.mutate and self.runtime is not None:
            self.runtime.menu = _paint(250)
            self.runtime.phase = "menu"
        return validator.parse_and_validate({"action": "PRESS_A", "reason": "choose the current option"})


class PressExec:
    def __init__(self, runtime, *, chunk: int = 0) -> None:
        self.runtime = runtime
        self.chunk = chunk
        self.actions: list[str] = []

    def execute(self, proposal):
        self.actions.append(proposal.action)
        self.runtime.press_button(proposal.action)
        if self.chunk:
            self.runtime.tick(self.chunk, render=True)
        return ExecutionResult(ok=True, executed=True, released=True)

    def release_all(self) -> None:
        return None


def _loop(runtime, *, budget=180, chunk=8, max_steps=2, owner=ControlOwner.AI_CONTROL, dry_run=False, reasoner=None, executor=None, mutate=False):
    vision = Vision(runtime)
    observer = VisualOnlyObserver(runtime, vision)
    return (
        AgentLoop(
            observer=observer,
            reasoner=reasoner or Reasoner(runtime, mutate=mutate),
            validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
            executor=executor or PressExec(runtime),
            ownership=ControlGate(owner),
            max_steps=max_steps,
            dry_run=dry_run,
            passive_budget_frames=budget,
            passive_chunk_frames=chunk,
            transition_grace_frames=8,
            transition_chunk_frames=1,
        ),
        vision,
        observer,
    )


def test_autonomous_pixel_change_is_distinct_from_a_settled_frame() -> None:
    before = _frame(_paint(1))
    after = _frame(_paint(8))
    assert frames_meaningfully_changed(before, after)
    assert frames_meaningfully_changed(before, _frame(_paint(1))) is False


def test_animation_between_menus_uses_one_decision_per_menu() -> None:
    runtime = Reel(list(range(10, 60)), final_mark=90, menu_mark=1)
    loop, vision, _observer = _loop(runtime, max_steps=2)
    result = loop.run()
    assert runtime.phase == "final"
    assert runtime.ticks >= 50
    assert runtime.ticks <= 96
    assert runtime.presses == ["PRESS_A", "PRESS_A"]
    assert vision.calls == 2
    assert vision.phases == ["menu", "final"]
    assert loop.reasoner.calls == 2
    assert loop.reasoner.texts == [("ACTIONABLE MENU",), ("FINAL MENU",)]
    assert result.steps[0].progression_frames >= 50
    assert result.steps[0].interaction_outcome == "ADVANCED"
    assert result.steps[0].decision_readiness == "INPUT_REQUIRED"
    assert result.steps[1].progression_frames == 0
    assert result.steps[1].perception_reused is True
    assert result.steps[1].decision_readiness == "INPUT_REQUIRED"
    assert "anim" not in vision.phases
    assert PASSIVE_GUIDANCE not in SYSTEM_PROMPT


def test_already_running_animation_is_pumped_before_the_first_decision() -> None:
    runtime = Reel(list(range(10, 40)), final_mark=90, autostart=True)
    loop, vision, _observer = _loop(runtime, max_steps=1)
    result = loop.run()
    step = result.steps[0]
    assert runtime.phase == "final"
    assert runtime.ticks >= 30
    assert runtime.ticks <= 56
    assert runtime.presses == ["PRESS_A"]
    assert vision.calls == 1
    assert vision.phases == ["final"]
    assert loop.reasoner.calls == 1
    assert loop.reasoner.texts == [("FINAL MENU",)]
    assert step.progression_frames >= 30
    assert step.decision_readiness == "INPUT_REQUIRED"
    assert any(PASSIVE_GUIDANCE in line for line in loop.reasoner.lines[0])
    assert step.proposal.action == "PRESS_A"


def test_passive_budget_forces_a_decision_without_a_model_call_per_chunk() -> None:
    runtime = AlwaysChanging()
    loop, vision, _observer = _loop(runtime, budget=16, chunk=8, max_steps=1)
    result = loop.run()
    assert runtime.ticks <= 32
    assert runtime.ticks >= 16
    assert vision.calls == 2
    assert loop.reasoner.calls == 1
    assert result.steps[0].progression_frames <= 32
    assert result.steps[0].decision_readiness == "PASSIVE_PROGRESS"
    assert result.steps[0].progression_chunks >= 1


def test_settled_menu_does_not_keep_the_passive_budget() -> None:
    runtime = Reel([11], final_mark=90, menu_mark=1)
    loop, vision, _observer = _loop(runtime, budget=180, chunk=8, max_steps=1)
    result = loop.run()
    # One changing chunk, then one unchanged chunk. Not the 180-frame budget.
    assert result.steps[0].progression_frames <= 16
    assert runtime.ticks <= 32
    assert runtime.phase == "final"
    assert vision.calls == 2
    assert loop.reasoner.calls == 1
    assert result.steps[0].decision_readiness == "INPUT_REQUIRED"


def test_old_chunked_decisions_call_the_model_more_often() -> None:
    """The pre-patch cadence reasons again after every short settle."""
    runtime = Reel(list(range(10, 60)), final_mark=90, menu_mark=1)
    loop, vision, _observer = _loop(
        runtime,
        budget=0,
        max_steps=10,
        executor=PressExec(runtime, chunk=8),
    )
    loop.run()
    assert loop.reasoner.calls >= 7
    assert vision.calls >= 7


def test_fade_still_reaches_a_stable_frame_when_passive_budget_is_on() -> None:
    class Fade:
        def capture_frame(self):
            if self.index < 3:
                return _frame(bytes([0, 0, 0]) * (W * H))
            self.phase = "menu"
            return _frame(self.menu)

        def tick(self, count=1, *, render=True):
            self.ticks += count
            self.index = min(self.index + count, 3)
            return True

        def __init__(self) -> None:
            self.ticks = 0
            self.index = 0
            self.menu = _paint(4)
            self.phase = "black"
            self.presses: list[str] = []

        def press_button(self, button, *, delay_frames=1):
            self.presses.append(str(button))

    runtime = Fade()
    loop, vision, _observer = _loop(runtime, budget=180, chunk=8, max_steps=1)
    result = loop.run()
    assert result.steps[0].scene_stability == "STABLE"
    assert result.steps[0].passive_frames == 3
    assert runtime.presses == ["PRESS_A"]
    assert vision.calls == 1
    assert loop.reasoner.calls == 1
    assert vision.phases == ["menu"]


def test_unreadable_live_frame_is_not_executed() -> None:
    class Boom(Reel):
        def capture_frame(self):
            if self.presses is None:
                raise RuntimeError("unused")
            if getattr(self, "fail_peek", False):
                raise RuntimeError("peek failed")
            return super().capture_frame()

    runtime = Boom([11], final_mark=90, menu_mark=1)

    class Arm(Reasoner):
        def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
            runtime.fail_peek = True
            return super().propose(
                context=context,
                goal=goal,
                stuck_state=stuck_state,
                discouraged=discouraged,
                history_lines=history_lines,
                validator=validator,
            )

    loop, _vision, _observer = _loop(runtime, reasoner=Arm(runtime), max_steps=1)
    step = loop.run().steps[0]
    assert step.executed is False
    assert "StaleObservationError" in step.error
    assert runtime.presses == []


def test_stale_frame_is_not_executed() -> None:
    runtime = Reel([11, 12], final_mark=90, menu_mark=1)
    loop, _vision, _observer = _loop(runtime, mutate=True, max_steps=1)
    step = loop.run().steps[0]
    assert step.executed is False
    assert "StaleObservationError" in step.error
    assert runtime.presses == []
    assert step.stuck_state == "NORMAL"


def test_paused_and_user_control_do_not_pump() -> None:
    for owner in (ControlOwner.PAUSED, ControlOwner.USER_CONTROL, ControlOwner.CONVERSATION):
        runtime = Reel(list(range(10, 40)), final_mark=90, autostart=True)
        loop, _vision, _observer = _loop(runtime, owner=owner, max_steps=1)
        step = loop.run().steps[0]
        assert runtime.ticks == 0
        assert step.executed is False
        assert step.progression_frames == 0


def test_dry_run_does_not_pump_or_press() -> None:
    runtime = Reel(list(range(10, 40)), final_mark=90, autostart=True)
    loop, vision, _observer = _loop(runtime, dry_run=True, max_steps=1)
    step = loop.run().steps[0]
    assert runtime.ticks == 0
    assert runtime.presses == []
    assert step.executed is False
    assert step.execution_ok is True
    assert vision.calls == 1


def test_malformed_action_still_fails_closed() -> None:
    class Idle:
        def __init__(self) -> None:
            self.ticks = 0
            self.phase = "menu"

        def capture_frame(self):
            return _frame(_paint(1))

        def tick(self, count=1, *, render=True):
            self.ticks += count
            return True

    class Bad:
        def propose(self, *, context, goal, stuck_state, discouraged, history_lines, validator):
            raise MalformedProposalError("bad")

    runtime = Idle()
    loop, _vision, _observer = _loop(runtime, reasoner=Bad(), max_steps=1)
    step = loop.run().steps[0]
    assert "MalformedProposalError" in step.error
    assert step.executed is False


def test_one_runtime_and_no_extra_thread() -> None:
    runtime = Reel([11, 12, 13], final_mark=90)
    before = threading.active_count()
    loop, _vision, observer = _loop(runtime, max_steps=1)
    loop.run()
    assert threading.active_count() == before
    assert observer._emulator is runtime
    assert loop.executor.runtime is runtime


def test_battle_menu_reasoning_is_not_repeated_on_animation_frames() -> None:
    runtime = Reel(list(range(10, 60)), final_mark=90, menu_mark=2)
    loop, vision, _observer = _loop(runtime, max_steps=2)
    result = loop.run()
    assert loop.reasoner.calls == 2
    assert vision.calls == 2
    assert result.steps[0].interaction_mode == "BATTLE_ACTIVE"
    assert result.steps[1].interaction_mode == "BATTLE_ACTIVE"
    assert result.steps[0].interaction_outcome == "ADVANCED"
    assert "anim" not in vision.phases


def test_no_effect_press_does_not_invent_passive_progress() -> None:
    class Still(Reel):
        def press_button(self, button, *, delay_frames=1) -> None:
            self.presses.append(str(button))

    runtime = Still([11], final_mark=90, menu_mark=1)
    loop, vision, _observer = _loop(runtime, max_steps=1)
    step = loop.run().steps[0]
    assert step.interaction_outcome == "NO_EFFECT"
    assert step.progress is False
    assert step.progression_frames == 0
    assert vision.calls == 1
    assert vision.phases == ["menu"]


def test_timing_evidence_names_model_wait_and_passive_runtime() -> None:
    runtime = Reel(list(range(10, 40)), final_mark=90, autostart=True)
    loop, _vision, _observer = _loop(runtime, max_steps=1)
    step = loop.run().steps[0]
    rendered = format_step(step, timing_details=True)
    assert "model_wait_ms=" in rendered
    assert "passive_runtime_ms=" in rendered
    assert "progression_frames=" in rendered
    assert "emulated_fps=" in rendered
    record = step_record(step)
    assert record["decision_readiness"] == step.decision_readiness
    assert record["progression_frames"] == step.progression_frames
    assert "model_wait_ms" in record["timings"]
    assert "passive_runtime_ms" in record["timings"]
    assert "readiness=" in format_step(step)
