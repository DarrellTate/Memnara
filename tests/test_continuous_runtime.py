"""Continuous runtime: one owner thread advances the game while models think."""

from __future__ import annotations

import threading
import time
from dataclasses import FrozenInstanceError, replace

import pytest

from memnara.agent.actions import DEFAULT_GAMEPLAY_ACTIONS, ActionProposal, ActionRegistry
from memnara.agent.loop import AgentLoop, format_step
from memnara.agent.observe import VisualOnlyObserver
from memnara.agent.ownership import ControlGate, ControlOwner
from memnara.agent.stuck import StuckConfig, StuckDetector
from memnara.agent.validator import ActionValidator
from memnara.demo.autonomy import build_parser, step_record, wire_continuous_runtime
from memnara.emulators.base import Button, Framebuffer
from memnara.emulators.gameplay import GameBoyActionExecutor
from memnara.perception.vision.models import SceneType, VisualObservation
from memnara.runtime.continuous import (
    DEFAULT_TARGET_FPS,
    ActionCommand,
    CommandResult,
    RuntimeActionExecutor,
    RuntimeFrameSource,
    RuntimeSnapshot,
    ThreadedEmulatorRuntime,
)
from memnara.runtime.exceptions import (
    RuntimeBusyError,
    RuntimeShutdownError,
    RuntimeStartupError,
    RuntimeStoppedError,
)
from tests.support.frames import FRAME_PIXELS, IDLE_PIXELS, frame, paint

PIXELS = FRAME_PIXELS
_paint = paint
_frame = frame


class FakeAdapter:
    """Records every call and the thread that made it. Detects reentrancy."""

    def __init__(self, *, mark: int = 1, raise_on_tick: Exception | None = None) -> None:
        self.mark = mark
        self.idle = 0
        self.ticks = 0
        self.frames = 0
        self.captures = 0
        self.presses: list[str] = []
        self.releases: list[tuple[str, bool]] = []
        self.is_open = True
        self.threads: set[str] = set()
        self.renders: set[bool] = set()
        self.overlaps = 0
        self.pending_release = 0
        self.raise_on_tick = raise_on_tick
        self._busy = False
        self._guard = threading.Lock()

    def _enter(self) -> None:
        with self._guard:
            if self._busy:
                self.overlaps += 1
            self._busy = True
        self.threads.add(threading.current_thread().name)

    def _exit(self) -> None:
        with self._guard:
            self._busy = False

    def tick(self, count: int = 1, *, render: bool = True) -> bool:
        self._enter()
        try:
            if self.raise_on_tick is not None and self.presses:
                raise self.raise_on_tick
            self.ticks += 1
            self.frames += count
            self.renders.add(render)
            return True
        finally:
            self._exit()

    def capture_frame(self) -> Framebuffer:
        self._enter()
        try:
            self.captures += 1
            return _frame(_paint(self.mark, idle=self.idle))
        finally:
            self._exit()

    def press_button(self, button: Button, *, delay_frames: int = 1) -> None:
        """Matches PyBoy: queue a press and a deferred release, emulate nothing."""
        self._enter()
        try:
            self.presses.append(button.value)
            self.pending_release = delay_frames
        finally:
            self._exit()

    def release_button(self, button: Button) -> None:
        self._enter()
        try:
            # The open flag travels with the release so a close that overtook it
            # cannot pass unnoticed.
            self.releases.append((button.value, self.is_open))
        finally:
            self._exit()

    def close(self) -> None:
        self._enter()
        try:
            self.is_open = False
        finally:
            self._exit()


class Stall:
    """Measures what a runtime did during one model call, and only during it.

    Sampling before and after the sleep is the point: a window that also contains
    action frames would let a frozen runtime look alive.
    """

    def __init__(self, probe) -> None:
        self._probe = probe
        self.windows: list[int] = []

    def sleep(self, seconds: float) -> None:
        before = self._probe()
        time.sleep(seconds)
        self.windows.append(self._probe() - before)

    @property
    def worst(self) -> int:
        return min(self.windows) if self.windows else -1


class Vision:
    """Vision provider with a controllable stall, like a slow local model."""

    def __init__(self, *, delay_s: float = 0.0, battle: bool = False) -> None:
        self.delay_s = delay_s
        self.battle = battle
        self.calls = 0
        self.observed_frames: list[int] = []
        self.on_call = None
        self.stall: Stall | None = None

    def observe(self, frame: Framebuffer) -> VisualObservation:
        self.calls += 1
        if self.on_call is not None:
            self.on_call(self.calls)
        if self.delay_s:
            if self.stall is not None:
                self.stall.sleep(self.delay_s)
            else:
                time.sleep(self.delay_s)
        return VisualObservation(
            scene_type=SceneType.MENU,
            description="a menu is open",
            visible_text=("FIGHT",),
            entities=(),
            menu_visible=True,
            dialogue_visible=False,
            battle_visible=self.battle,
            confidence=0.9,
            notable_changes="",
            source="VISUAL",
            model="test-vision",
        )


class Reasoner:
    def __init__(self, *, delay_s: float = 0.0, action: str = "PRESS_A") -> None:
        self.delay_s = delay_s
        self.action = action
        self.calls = 0
        self.on_call = None
        self.stall: Stall | None = None

    def propose(self, context, goal, stuck_state=None, discouraged=(), history_lines=(), validator=None):
        self.calls += 1
        if self.on_call is not None:
            self.on_call(self.calls)
        if self.delay_s:
            if self.stall is not None:
                self.stall.sleep(self.delay_s)
            else:
                time.sleep(self.delay_s)
        return ActionProposal(action=self.action, parameters={}, reason="test", confidence=0.9)


def _wire(
    adapter: FakeAdapter,
    vision: Vision,
    *,
    owner: ControlOwner = ControlOwner.AI_CONTROL,
    target_fps: float = 60.0,
    reasoner: Reasoner | None = None,
    max_steps: int = 1,
    should_advance=None,
    can_apply_input=None,
    dry_run: bool = False,
    passive_budget_frames: int = 16,
):
    gate = ControlGate(owner)
    runtime = ThreadedEmulatorRuntime(
        adapter,
        target_fps=target_fps,
        should_advance=should_advance,
        can_apply_input=can_apply_input or gate.allows_gameplay,
    )
    observer = VisualOnlyObserver(RuntimeFrameSource(runtime), vision)
    executor = RuntimeActionExecutor(runtime)
    loop = AgentLoop(
        observer=observer,
        reasoner=reasoner or Reasoner(),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=executor,
        ownership=gate,
        stuck=StuckDetector(StuckConfig()),
        max_steps=max_steps,
        dry_run=dry_run,
        goal="test",
        passive_budget_frames=passive_budget_frames,
        passive_chunk_frames=4,
    )
    return runtime, loop, executor, gate


def _wire_stepped(
    adapter: FakeAdapter,
    vision: Vision,
    *,
    reasoner: Reasoner | None = None,
    max_steps: int = 1,
    passive_budget_frames: int = 16,
):
    """The pre-patch frame-stepped wiring, for same-scenario comparisons."""
    return AgentLoop(
        observer=VisualOnlyObserver(adapter, vision),
        reasoner=reasoner or Reasoner(),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=GameBoyActionExecutor(adapter),
        ownership=ControlGate(ControlOwner.AI_CONTROL),
        stuck=StuckDetector(StuckConfig()),
        max_steps=max_steps,
        goal="test",
        passive_budget_frames=passive_budget_frames,
        passive_chunk_frames=4,
    )


# --- concurrency and runtime ownership -------------------------------------


def test_the_continuous_runtime_does_not_spend_more_model_calls() -> None:
    """The authorized constraint: keep the game moving without thinking more.

    Both runtimes run the same scenario with the same providers, so a future
    patch cannot quietly buy smoothness with extra inference.
    """
    stepped_vision, stepped_reasoner = Vision(), Reasoner()
    stepped = _wire_stepped(
        FakeAdapter(), stepped_vision, reasoner=stepped_reasoner, max_steps=3
    )
    stepped.run()

    live_vision, live_reasoner = Vision(), Reasoner()
    runtime, loop, _, _ = _wire(
        FakeAdapter(), live_vision, reasoner=live_reasoner, max_steps=3
    )
    runtime.start()
    try:
        loop.run()
    finally:
        runtime.stop()

    assert stepped_vision.calls > 0 and stepped_reasoner.calls > 0
    assert live_vision.calls <= stepped_vision.calls
    assert live_reasoner.calls <= stepped_reasoner.calls
    assert live_reasoner.calls == 3, "one reasoning call per step, as before"


def test_runtime_advances_while_vision_is_blocked() -> None:
    adapter = FakeAdapter()
    vision = Vision(delay_s=0.4)
    runtime, loop, _, _ = _wire(adapter, vision, passive_budget_frames=0)
    stall = Stall(lambda: runtime.frames_advanced)
    vision.stall = stall
    runtime.start()
    try:
        loop.run()
    finally:
        runtime.stop()
    assert stall.windows, "vision never stalled"
    # 0.4 s at 60 fps is about 24 frames. Action frames are outside this window.
    assert stall.worst >= 10, f"runtime advanced {stall.worst} frames during a vision call"


def test_runtime_advances_while_reasoning_is_blocked() -> None:
    adapter = FakeAdapter()
    vision = Vision()
    reasoner = Reasoner(delay_s=0.4)
    runtime, loop, _, _ = _wire(
        adapter, vision, reasoner=reasoner, passive_budget_frames=0
    )
    stall = Stall(lambda: runtime.frames_advanced)
    reasoner.stall = stall
    runtime.start()
    try:
        loop.run()
    finally:
        runtime.stop()
    assert stall.windows, "reasoning never stalled"
    assert stall.worst >= 10, f"runtime advanced {stall.worst} frames during a reasoning call"


def test_the_frame_stepped_runtime_does_freeze_during_inference() -> None:
    """The contrast that gives the two tests above their meaning."""
    adapter = FakeAdapter()
    vision = Vision(delay_s=0.3)
    stall = Stall(lambda: adapter.frames)
    vision.stall = stall
    observer = VisualOnlyObserver(adapter, vision)
    loop = AgentLoop(
        observer=observer,
        reasoner=Reasoner(),
        validator=ActionValidator(ActionRegistry(DEFAULT_GAMEPLAY_ACTIONS)),
        executor=GameBoyActionExecutor(adapter),
        ownership=ControlGate(ControlOwner.AI_CONTROL),
        stuck=StuckDetector(StuckConfig()),
        max_steps=1,
        goal="test",
        passive_budget_frames=0,
    )
    loop.run()
    assert stall.windows, "vision never stalled"
    assert max(stall.windows) == 0, "the frame-stepped runtime advanced without being asked"


def test_a_single_owner_thread_drives_the_emulator() -> None:
    adapter = FakeAdapter()
    vision = Vision(delay_s=0.1)
    runtime, loop, _, _ = _wire(adapter, vision)
    runtime.start()
    try:
        loop.run()
    finally:
        runtime.stop()
    assert adapter.threads == {runtime.owner_thread_name}
    assert runtime.owner_thread_name == "memnara-runtime"


def test_no_direct_emulator_call_overlaps_another() -> None:
    adapter = FakeAdapter()
    vision = Vision(delay_s=0.05)
    runtime, loop, _, _ = _wire(adapter, vision, max_steps=3)
    runtime.start()
    try:
        loop.run()
    finally:
        runtime.stop()
    assert adapter.overlaps == 0


def test_observer_and_executor_share_one_emulator() -> None:
    adapter = FakeAdapter()
    runtime, loop, executor, _ = _wire(adapter, Vision())
    runtime.start()
    try:
        loop.run()
    finally:
        runtime.stop()
    assert adapter.presses == ["a"]
    assert executor.commands and executor.commands[0].action == "PRESS_A"


def test_visible_and_headless_use_the_same_runtime_architecture() -> None:
    results = []
    for render in (True, False):
        adapter = FakeAdapter()
        runtime = ThreadedEmulatorRuntime(adapter, target_fps=120.0, render=render)
        runtime.start()
        try:
            runtime.wait_for_frames(4, timeout_s=2.0)
        finally:
            runtime.stop()
        results.append((type(runtime).__name__, adapter.renders))
    assert results[0][0] == results[1][0] == "ThreadedEmulatorRuntime"
    assert results[0][1] == {True}
    assert results[1][1] == {False}


def test_runtime_holds_a_bounded_cadence_instead_of_racing() -> None:
    """Pacing is proven against an unpaced owner thread with the same publish path."""
    window = 0.25

    racing = FakeAdapter()
    unpaced = ThreadedEmulatorRuntime(racing, target_fps=60.0, chunk_frames=2)
    unpaced._pace = lambda _frames: None  # same loop and publish; no throttle
    unpaced.start()
    try:
        time.sleep(window)
        raced = unpaced.frames_advanced
    finally:
        unpaced.stop()

    adapter = FakeAdapter()
    runtime = ThreadedEmulatorRuntime(adapter, target_fps=60.0, chunk_frames=2)
    runtime.start()
    try:
        time.sleep(window)
        paced = runtime.frames_advanced
    finally:
        runtime.stop()

    expected = int(60.0 * window)
    assert paced >= max(4, expected // 2), f"paced {paced} frames, expected about {expected}"
    assert paced <= expected * 2, f"paced {paced} frames raced past the {expected}-frame target"
    assert raced > paced * 5, f"paced {paced} frames, unpaced {raced} in the same window"
    assert adapter.overlaps == 0
    assert racing.overlaps == 0


def test_stop_joins_the_owner_thread_and_releases_input() -> None:
    adapter = FakeAdapter()
    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=120.0, close_runtime=adapter.close
    )
    runtime.start()
    runtime.wait_for_frames(2, timeout_s=2.0)
    runtime.stop()
    assert runtime.running is False
    assert {name for name, _ in adapter.releases} == {button.value for button in Button}
    assert all(was_open for _, was_open in adapter.releases), "released after close"
    assert adapter.is_open is False
    assert runtime.error == ""


def test_a_shutdown_that_failed_to_close_the_emulator_says_so() -> None:
    """A clean-looking stop must not hide a leaked emulator, or evidence lies."""
    adapter = FakeAdapter()

    def wont_close() -> None:
        raise OSError("window handle refused to close")

    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=120.0, close_runtime=wont_close
    )
    runtime.start()
    runtime.wait_for_frames(2, timeout_s=2.0)
    runtime.stop()
    assert runtime.running is False
    # Input release precedes the close, so it still happened.
    assert {name for name, _ in adapter.releases} == {button.value for button in Button}
    assert runtime.error == "CloseFailed: OSError: window handle refused to close"


def test_the_owner_thread_opens_and_closes_the_emulator() -> None:
    """Startup and shutdown stay on the owner thread, so a window keeps one owner."""
    adapter = FakeAdapter()
    opened: list[str] = []
    closed: list[str] = []
    runtime = ThreadedEmulatorRuntime(
        adapter,
        target_fps=120.0,
        open_runtime=lambda: opened.append(threading.current_thread().name),
        close_runtime=lambda: closed.append(threading.current_thread().name),
    )
    runtime.start()
    runtime.wait_for_frames(2, timeout_s=2.0)
    runtime.stop()
    assert opened == ["memnara-runtime"]
    assert closed == ["memnara-runtime"]
    assert adapter.threads == {"memnara-runtime"}


def test_a_failed_open_is_reported_and_does_not_leave_a_thread() -> None:
    adapter = FakeAdapter()

    def boom() -> None:
        raise RuntimeError("rom missing")

    runtime = ThreadedEmulatorRuntime(adapter, open_runtime=boom)
    with pytest.raises(RuntimeStartupError, match="rom missing"):
        runtime.start()
    assert runtime.running is False
    # The emulator never opened, so nothing may be released or closed.
    assert adapter.releases == []
    assert adapter.captures == 0


def test_a_stuck_owner_thread_refuses_to_report_a_clean_stop() -> None:
    """A caller must not free the emulator under a live owner thread."""
    adapter = FakeAdapter()
    wedged = threading.Event()

    def never_returns() -> None:
        wedged.set()
        time.sleep(2.0)

    runtime = ThreadedEmulatorRuntime(adapter, target_fps=120.0, close_runtime=never_returns)
    runtime.start()
    runtime.wait_for_frames(2, timeout_s=2.0)
    with pytest.raises(RuntimeShutdownError):
        runtime.stop(timeout_s=0.2)
    assert wedged.is_set()
    assert runtime.running is True
    # A runtime that failed to stop stays failed, so no caller reads it as healthy.
    assert "did not stop" in runtime.error
    with pytest.raises(RuntimeStoppedError):
        runtime.latest_snapshot()
    runtime.stop(timeout_s=5.0)
    assert runtime.running is False


def test_a_dead_owner_thread_is_surfaced_to_the_agent() -> None:
    adapter = FakeAdapter()
    runtime = ThreadedEmulatorRuntime(adapter, target_fps=120.0)
    runtime.start()
    source = RuntimeFrameSource(runtime)
    assert source.capture_frame().pixels
    runtime._error = "RuntimeError: emulator vanished"
    try:
        with pytest.raises(RuntimeStoppedError):
            source.capture_frame()
        with pytest.raises(RuntimeStoppedError):
            source.tick(2)
    finally:
        runtime._error = ""
        runtime.stop()


def test_a_frozen_runtime_reports_a_frame_wait_timeout_without_failing() -> None:
    adapter = FakeAdapter()
    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=120.0, should_advance=lambda: False
    )
    runtime.start()
    source = RuntimeFrameSource(runtime, wait_timeout_s=0.1)
    try:
        assert source.tick(4) is False
    finally:
        runtime.stop()
    assert runtime.frame_wait_timeouts == 1
    assert runtime.error == ""


def test_input_is_refused_on_the_owner_thread_when_ownership_changed() -> None:
    """Defense in depth: the only code that can move a button checks ownership."""
    adapter = FakeAdapter()
    gate = ControlGate(ControlOwner.AI_CONTROL)
    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=120.0, can_apply_input=gate.allows_gameplay
    )
    runtime.start()
    try:
        gate.owner = ControlOwner.USER_CONTROL
        result = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=2.0)
    finally:
        runtime.stop()
    assert result.executed is False
    assert result.error.startswith("OwnershipDeniedError")
    assert adapter.presses == []


def test_a_restarted_runtime_is_refused() -> None:
    runtime = ThreadedEmulatorRuntime(FakeAdapter(), target_fps=120.0)
    runtime.start()
    runtime.stop()
    with pytest.raises(RuntimeStartupError):
        runtime.start()


def test_a_paused_snapshot_reports_that_it_is_not_advancing() -> None:
    adapter = FakeAdapter()
    advance = True
    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=120.0, should_advance=lambda: advance
    )
    runtime.start()
    try:
        runtime.wait_for_frames(2, timeout_s=2.0)
        assert runtime.latest_snapshot().advancing is True
        advance = False
        time.sleep(0.1)
        assert runtime.latest_snapshot().advancing is False
    finally:
        runtime.stop()


def test_submitting_after_stop_reports_a_stopped_runtime() -> None:
    adapter = FakeAdapter()
    runtime = ThreadedEmulatorRuntime(adapter, target_fps=120.0)
    runtime.start()
    runtime.stop()
    result = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=1.0)
    assert result.ok is False
    assert result.executed is False
    assert "RuntimeStoppedError" in result.error


def test_paused_ownership_freezes_the_runtime() -> None:
    adapter = FakeAdapter()
    gate = ControlGate(ControlOwner.PAUSED)
    runtime = ThreadedEmulatorRuntime(
        adapter,
        target_fps=120.0,
        should_advance=lambda: gate.owner is not ControlOwner.PAUSED,
    )
    runtime.start()
    try:
        time.sleep(0.15)
        frozen = runtime.frames_advanced
        gate.owner = ControlOwner.AI_CONTROL
        time.sleep(0.15)
        thawed = runtime.frames_advanced
    finally:
        runtime.stop()
    assert frozen == 0
    assert thawed > frozen


def test_user_control_keeps_the_runtime_advancing() -> None:
    adapter = FakeAdapter()
    vision = Vision()
    runtime, loop, executor, _ = _wire(
        adapter, vision, owner=ControlOwner.USER_CONTROL, target_fps=120.0
    )
    runtime.start()
    try:
        result = loop.run()
    finally:
        runtime.stop()
    assert runtime.frames_advanced > 0
    assert executor.commands == []
    assert adapter.presses == []
    step = result.steps[0]
    assert step.error.startswith("OwnershipDeniedError")
    # A proposal refused on ownership counts as dropped, like a stale one.
    assert step.stale_proposals_dropped == 1
    assert step.applied_observation_id == "", "a refused action landed nowhere"


def test_dry_run_keeps_the_runtime_advancing_without_gameplay_input() -> None:
    """Dry run still means no input. The clock is allowed to keep moving."""
    adapter = FakeAdapter()
    vision = Vision(delay_s=0.15)
    reasoner = Reasoner(delay_s=0.15)
    runtime, loop, executor, _ = _wire(
        adapter, vision, reasoner=reasoner, dry_run=True, target_fps=120.0
    )
    runtime.start()
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    assert runtime.frames_advanced > 0
    assert adapter.presses == []
    assert executor.commands == []
    assert step.executed is False
    assert step.execution_ok is True
    assert step.applied_observation_id == ""


# --- stale proposals -------------------------------------------------------


def test_idle_animation_does_not_invalidate_an_equivalent_decision() -> None:
    adapter = FakeAdapter()
    vision = Vision()
    reasoner = Reasoner(delay_s=0.2)
    runtime, loop, executor, _ = _wire(adapter, vision, reasoner=reasoner)
    runtime.start()
    reasoner.on_call = lambda _n: setattr(adapter, "idle", IDLE_PIXELS)
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    assert step.frames_since_observation > 0, "no frames elapsed, test proves nothing"
    assert step.error == ""
    assert step.executed is True
    assert step.stale_proposals_dropped == 0
    assert executor.commands[0].source_observation_id == step.observation_id


def test_a_changed_menu_discards_the_pending_action() -> None:
    adapter = FakeAdapter()
    vision = Vision()
    reasoner = Reasoner(delay_s=0.1)
    runtime, loop, executor, _ = _wire(adapter, vision, reasoner=reasoner)
    runtime.start()
    reasoner.on_call = lambda _n: setattr(adapter, "mark", 9)
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    assert step.error.startswith("StaleObservationError")
    assert step.executed is False
    assert step.stale_proposals_dropped == 1
    assert executor.commands == []
    assert adapter.presses == []


def _confirm_with_a_fresh_reading(loop: AgentLoop) -> None:
    """Give the observer a confirm step that re-reads the scene.

    A structured-state runtime can answer this cheaply. Generic VISION keeps the
    default no-op confirm, which is why the battle-mode branch needs this wiring
    to be exercised at all.
    """
    observer = loop.observer

    def confirm(prior):
        # Drop the cached reading so the confirm genuinely re-reads the scene.
        observer.invalidate_perception_reuse()
        return observer.observe()

    observer.confirm_execution = confirm  # type: ignore[method-assign]


def test_entering_a_battle_discards_the_pending_action() -> None:
    """Only the interaction mode changes here, so only the mode check can fail it."""
    adapter = FakeAdapter()
    vision = Vision()
    reasoner = Reasoner(delay_s=0.05)
    runtime, loop, executor, _ = _wire(adapter, vision, reasoner=reasoner)
    _confirm_with_a_fresh_reading(loop)
    runtime.start()
    # The frame is left alone. A battle begins only in what perception reports.
    reasoner.on_call = lambda _n: setattr(vision, "battle", True)
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    assert step.error == "StaleModeError: reasoned=NON_BATTLE confirmed=BATTLE_ACTIVE"
    assert step.executed is False
    assert step.stale_proposals_dropped == 1
    assert executor.commands == []
    assert adapter.presses == []


def test_leaving_a_battle_discards_the_pending_action() -> None:
    adapter = FakeAdapter()
    vision = Vision(battle=True)
    reasoner = Reasoner(delay_s=0.05)
    runtime, loop, executor, _ = _wire(adapter, vision, reasoner=reasoner)
    _confirm_with_a_fresh_reading(loop)
    runtime.start()
    reasoner.on_call = lambda _n: setattr(vision, "battle", False)
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    assert step.error == "StaleModeError: reasoned=BATTLE_ACTIVE confirmed=NON_BATTLE"
    assert step.executed is False
    assert step.stale_proposals_dropped == 1
    assert executor.commands == []
    assert adapter.presses == []


def test_a_battle_that_repaints_the_screen_is_also_stale_without_a_confirm_step() -> None:
    """Generic VISION has no confirm reading, so the repaint is what catches it."""
    adapter = FakeAdapter()
    vision = Vision()
    reasoner = Reasoner(delay_s=0.05)
    runtime, loop, executor, _ = _wire(adapter, vision, reasoner=reasoner)
    runtime.start()

    def enter_battle(_n: int) -> None:
        vision.battle = True
        adapter.mark = 5

    reasoner.on_call = enter_battle
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    assert step.error == (
        "StaleObservationError: the scene changed materially while the decision was pending"
    )
    assert step.executed is False
    assert executor.commands == []


def test_a_started_transition_discards_the_pending_action() -> None:
    adapter = FakeAdapter()
    vision = Vision()
    reasoner = Reasoner(delay_s=0.1)
    runtime, loop, executor, _ = _wire(adapter, vision, reasoner=reasoner)
    runtime.start()

    def fade_out(_n: int) -> None:
        adapter.capture_frame = lambda: _frame(bytes(PIXELS * 3))

    reasoner.on_call = fade_out
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    assert step.error.startswith("StaleSceneError")
    assert step.executed is False
    assert executor.commands == []


def test_an_ownership_change_during_inference_invalidates_the_proposal() -> None:
    adapter = FakeAdapter()
    vision = Vision()
    reasoner = Reasoner(delay_s=0.05)
    runtime, loop, executor, gate = _wire(adapter, vision, reasoner=reasoner)
    runtime.start()
    reasoner.on_call = lambda _n: setattr(gate, "owner", ControlOwner.USER_CONTROL)
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    assert step.executed is False
    assert executor.commands == []
    assert adapter.presses == []
    assert step.error.startswith("OwnershipDeniedError")


def test_no_delayed_ai_input_reaches_the_runtime_after_a_takeover() -> None:
    adapter = FakeAdapter()
    vision = Vision()
    reasoner = Reasoner(delay_s=0.05)
    runtime, loop, executor, gate = _wire(
        adapter, vision, reasoner=reasoner, max_steps=3
    )
    runtime.start()
    reasoner.on_call = lambda n: (
        setattr(gate, "owner", ControlOwner.USER_CONTROL) if n == 2 else None
    )
    try:
        result = loop.run()
    finally:
        runtime.stop()
    assert adapter.presses == ["a"]
    assert len(executor.commands) == 1
    assert [step.executed for step in result.steps] == [True, False, False]
    # The drop count is a running run total, so it climbs rather than resetting.
    assert [step.stale_proposals_dropped for step in result.steps] == [0, 1, 2]


def test_a_structured_token_that_moved_on_discards_the_pending_action() -> None:
    """A runtime with cheap structured state can answer without a second model call."""
    adapter = FakeAdapter()
    vision = Vision()
    reasoner = Reasoner(delay_s=0.05)
    runtime, loop, executor, _ = _wire(adapter, vision, reasoner=reasoner)
    runtime.start()
    tokens = ["map:1", "map:2"]
    original_observe = loop.observer.observe_frame
    loop.observer.observe_frame = lambda frame: replace(  # type: ignore[method-assign]
        original_observe(frame), progress_token=tokens[0]
    )
    loop.observer.peek_progress_token = lambda: tokens[-1]  # type: ignore[attr-defined]
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    assert step.error == "StaleObservationError: structured state advanced"
    assert step.executed is False
    assert executor.commands == []


def test_an_unchanged_structured_token_keeps_the_action() -> None:
    adapter = FakeAdapter()
    vision = Vision()
    runtime, loop, executor, _ = _wire(adapter, vision)
    runtime.start()
    original_observe = loop.observer.observe_frame
    loop.observer.observe_frame = lambda frame: replace(  # type: ignore[method-assign]
        original_observe(frame), progress_token="map:1"
    )
    loop.observer.peek_progress_token = lambda: "map:1"  # type: ignore[attr-defined]
    try:
        result = loop.run()
    finally:
        runtime.stop()
    assert result.steps[0].executed is True
    assert len(executor.commands) == 1


def test_a_failing_token_probe_does_not_invent_staleness() -> None:
    adapter = FakeAdapter()
    runtime, loop, executor, _ = _wire(adapter, Vision())
    runtime.start()

    def boom():
        raise RuntimeError("state read failed")

    loop.observer.peek_progress_token = boom  # type: ignore[attr-defined]
    try:
        result = loop.run()
    finally:
        runtime.stop()
    assert result.steps[0].executed is True
    assert len(executor.commands) == 1


def test_a_frozen_runtime_still_applies_input_when_ownership_allows_it() -> None:
    """`should_advance` governs the clock. Input is governed by `can_apply_input`."""
    adapter = FakeAdapter()
    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=1000.0, should_advance=lambda: False
    )
    runtime.start()
    try:
        idle = runtime.frames_advanced
        time.sleep(0.05)
        assert runtime.frames_advanced == idle
        result = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=2.0)
    finally:
        runtime.stop()
    assert result.executed is True
    assert result.frames_applied > 0


def test_a_pause_is_not_counted_as_a_runtime_freeze() -> None:
    adapter = FakeAdapter()
    advance = True
    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=120.0, should_advance=lambda: advance
    )
    runtime.start()
    try:
        runtime.wait_for_frames(4, timeout_s=2.0)
        advance = False
        time.sleep(0.5)
        advance = True
        runtime.wait_for_frames(4, timeout_s=2.0)
    finally:
        runtime.stop()
    assert runtime.max_gap_ms < 200, f"a 500 ms pause was reported as a {runtime.max_gap_ms:.0f} ms freeze"


def test_a_command_in_flight_when_the_runtime_dies_is_not_left_hanging() -> None:
    adapter = FakeAdapter()
    entered = threading.Event()

    class DyingExecutor:
        def __init__(self, adapter) -> None:
            self.adapter = adapter

        def execute(self, proposal):
            entered.set()
            raise BaseException("owner thread killed")  # noqa: TRY002

        def release_all(self) -> None:
            return None

    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=120.0, executor_factory=DyingExecutor
    )
    runtime.start()
    try:
        result = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=2.0)
        reported = runtime.error
    finally:
        runtime._error = ""
        runtime.stop()
    assert entered.is_set()
    assert result.ok is False
    assert "mid-action" in result.error
    # The owner thread's death is surfaced, not swallowed.
    assert "owner thread killed" in reported
    assert runtime.running is False


# --- command queue ---------------------------------------------------------


def test_the_command_queue_is_bounded_to_one_pending_action() -> None:
    adapter = FakeAdapter()
    entered = threading.Event()
    gate = threading.Event()

    class BlockingExecutor:
        def __init__(self, adapter) -> None:
            self.adapter = adapter

        def execute(self, proposal):
            entered.set()
            gate.wait(timeout=5)
            from memnara.agent.execute import ExecutionResult

            return ExecutionResult(ok=True, executed=True, released=True, detail="held")

        def release_all(self) -> None:
            return None

    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=120.0, executor_factory=BlockingExecutor
    )
    runtime.start()
    results: dict[str, CommandResult] = {}

    def submit(action: str) -> None:
        results[action] = runtime.submit(ActionCommand(action=action), timeout_s=5.0)

    first = threading.Thread(target=submit, args=("PRESS_A",))
    first.start()
    assert entered.wait(timeout=2)
    second = threading.Thread(target=submit, args=("PRESS_B",))
    second.start()
    time.sleep(0.1)
    try:
        with pytest.raises(RuntimeBusyError):
            runtime.submit(ActionCommand(action="PRESS_UP"), timeout_s=1.0)
    finally:
        gate.set()
        first.join(timeout=2)
        second.join(timeout=2)
        runtime.stop()
    # The first two were accepted; only the third exceeded the one-slot queue.
    assert sorted(results) == ["PRESS_A", "PRESS_B"]
    assert results["PRESS_A"].executed is True
    assert results["PRESS_B"].executed is True


def test_a_command_the_agent_stopped_waiting_for_is_never_pressed() -> None:
    """A timed-out action is abandoned, not applied late on a changed scene."""
    adapter = FakeAdapter()
    holding = threading.Event()
    release = threading.Event()

    class SlowStart:
        def __init__(self, adapter) -> None:
            self.adapter = adapter
            self.executed = 0

        def execute(self, proposal):
            from memnara.agent.execute import ExecutionResult

            self.executed += 1
            self.adapter.press_button(Button.A, delay_frames=8)
            return ExecutionResult(ok=True, executed=True, released=True)

        def release_all(self) -> None:
            return None

    class Gate:
        """Holds the owner thread before it can take the command."""

        def __call__(self) -> bool:
            holding.set()
            release.wait(timeout=5)
            return True

    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=120.0, should_advance=Gate(), executor_factory=SlowStart
    )
    runtime.start()
    assert holding.wait(timeout=2)
    try:
        result = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=0.2)
        release.set()
        time.sleep(0.2)
    finally:
        release.set()
        runtime.stop()
    assert result.executed is False
    assert "RuntimeTimeoutError" in result.error
    assert adapter.presses == [], "an abandoned action still reached the emulator"


def test_one_closed_loop_action_runs_before_the_next_observation() -> None:
    adapter = FakeAdapter()
    vision = Vision()
    runtime, loop, executor, _ = _wire(adapter, vision, max_steps=2)
    order: list[tuple[str, tuple[str, ...]]] = []
    observe = loop.observer.observe_frame
    execute = loop.executor.execute

    def observe_frame(frame):
        order.append(("observe", tuple(adapter.presses)))
        return observe(frame)

    def execute_action(proposal):
        order.append(("execute", tuple(adapter.presses)))
        result = execute(proposal)
        order.append(("executed", tuple(adapter.presses)))
        return result

    loop.observer.observe_frame = observe_frame
    loop.executor.execute = execute_action
    runtime.start()
    try:
        result = loop.run()
    finally:
        runtime.stop()
    assert [kind for kind, _ in order[:4]] == ["observe", "execute", "executed", "observe"]
    assert order[0][1] == ()
    assert order[3][1] == ("a",)
    assert adapter.presses == ["a", "a"]
    assert executor.commands[0].source_observation_id == result.steps[0].observation_id
    assert executor.commands[1].source_observation_id == result.steps[1].observation_id
    assert result.steps[0].observation_id != result.steps[1].observation_id


def test_repeated_proposals_do_not_queue_a_backlog() -> None:
    adapter = FakeAdapter()
    runtime, loop, executor, _ = _wire(adapter, Vision(), max_steps=3)
    runtime.start()
    try:
        loop.run()
    finally:
        runtime.stop()
    assert len(executor.commands) == 3
    assert adapter.presses == ["a", "a", "a"]


def test_a_malformed_action_never_reaches_the_runtime() -> None:
    adapter = FakeAdapter()
    runtime, loop, executor, _ = _wire(
        adapter, Vision(), reasoner=Reasoner(action="LAUNCH_ROCKET")
    )
    runtime.start()
    try:
        result = loop.run()
    finally:
        runtime.stop()
    assert executor.commands == []
    assert adapter.presses == []
    assert result.steps[0].validation_ok is False


def test_a_runtime_exception_during_a_command_releases_input() -> None:
    adapter = FakeAdapter(raise_on_tick=RuntimeError("emulator lost"))
    runtime = ThreadedEmulatorRuntime(adapter, target_fps=120.0)
    runtime.start()
    try:
        result = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=2.0)
    finally:
        runtime.stop()
    assert result.ok is False
    assert result.released is True
    assert "emulator lost" in result.error
    assert {name for name, _ in adapter.releases} == {button.value for button in Button}


# --- shipped wiring and operator surface -----------------------------------


def test_the_demo_wiring_is_the_architecture_the_tests_exercise() -> None:
    """`wire_continuous_runtime` is what ships, so it is what must be correct."""
    adapter = FakeAdapter()
    gate = ControlGate(ControlOwner.AI_CONTROL)
    runtime, observer, executor = wire_continuous_runtime(
        adapter, Vision(), gate, target_fps=120.0
    )
    assert isinstance(runtime, ThreadedEmulatorRuntime)
    assert isinstance(executor, RuntimeActionExecutor)
    # One emulator, one runtime, shared by perception and control.
    assert observer._emulator._runtime is runtime
    assert executor._runtime is runtime
    threads_before = threading.active_count()
    runtime.start()
    try:
        assert threading.active_count() == threads_before + 1
        runtime.wait_for_frames(4, timeout_s=2.0)
        # PAUSED freezes the clock through should_advance.
        gate.owner = ControlOwner.PAUSED
        time.sleep(0.1)
        frozen = runtime.frames_advanced
        time.sleep(0.1)
        assert runtime.frames_advanced == frozen
        # And the owner thread refuses AI input through can_apply_input.
        refused = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=2.0)
        assert refused.error.startswith("OwnershipDeniedError")
        gate.owner = ControlOwner.AI_CONTROL
        allowed = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=2.0)
    finally:
        runtime.stop()
    assert allowed.executed is True
    assert adapter.presses == ["a"]
    assert adapter.threads == {"memnara-runtime"}
    assert threading.active_count() == threads_before


def test_the_cli_defaults_to_the_continuous_runtime() -> None:
    args = build_parser().parse_args([])
    assert args.step_runtime is False
    assert args.target_fps == DEFAULT_TARGET_FPS
    assert args.show_window is False
    stepped = build_parser().parse_args(["--step-runtime", "--target-fps", "30"])
    assert stepped.step_runtime is True
    assert stepped.target_fps == 30.0


def test_the_operator_surface_reports_observation_provenance() -> None:
    adapter = FakeAdapter()
    runtime, loop, _, _ = _wire(adapter, Vision())
    runtime.start()
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    plain = format_step(step)
    detailed = format_step(step, timing_details=True)
    assert "RUNTIME" not in plain, "the default CLI stays uncluttered"
    assert step.observation_id and step.applied_observation_id, "ids must be real, not 'none'"
    assert f"RUNTIME observation={step.observation_id} " in detailed
    assert f"applied_observation={step.applied_observation_id} " in detailed
    assert f"proposal_age_ms={step.proposal_age_ms}" in detailed
    assert f"frames_since_observation={step.frames_since_observation}" in detailed
    assert f"execution_frames={step.execution_frames}" in detailed
    assert "stale_proposals_dropped_total=0" in detailed
    record = step_record(step)
    assert record["observation_id"] == step.observation_id
    assert record["applied_observation_id"] == step.applied_observation_id
    assert record["execution_frames"] == step.execution_frames
    assert record["stale_proposals_dropped_total"] == 0
    assert record["timings"]["proposal_age_ms"] == step.proposal_age_ms


def test_an_executed_action_reports_where_it_landed_and_what_it_cost() -> None:
    adapter = FakeAdapter()
    runtime, loop, executor, _ = _wire(adapter, Vision())
    runtime.start()
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    executor_frames = GameBoyActionExecutor(adapter).settle_frames
    assert step.execution_frames == executor_frames
    assert step.observation_id, "the reasoned observation must be named"
    assert step.applied_observation_id, "the applied observation must be named"
    # The action landed on a later observation than the one it was reasoned from.
    assert step.applied_observation_id != step.observation_id
    assert executor.commands[0].source_observation_id == step.observation_id


def test_action_frames_are_paced_to_the_target_cadence() -> None:
    """Input frames are real game time, so they are paced like any other frame."""
    adapter = FakeAdapter()
    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=60.0, should_advance=lambda: False
    )
    runtime.start()
    settle = GameBoyActionExecutor(adapter).settle_frames
    started = time.perf_counter()
    try:
        result = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=5.0)
    finally:
        runtime.stop()
    elapsed = time.perf_counter() - started
    expected = settle / 60.0
    assert result.frames_applied == settle
    assert elapsed >= expected * 0.7, f"{settle} frames applied in {elapsed:.3f}s, faster than game time"


# --- live feel -------------------------------------------------------------


def test_a_second_of_model_latency_does_not_freeze_the_runtime() -> None:
    """Live-feel check at one second so the default suite stays fast.

    The authorized three-second form runs against the real emulator in
    `test_continuous_runtime_live.py`.
    """
    adapter = FakeAdapter()
    vision = Vision(delay_s=0.5)
    reasoner = Reasoner(delay_s=0.5)
    runtime, loop, _, _ = _wire(
        adapter, vision, reasoner=reasoner, passive_budget_frames=0
    )
    vision.stall = Stall(lambda: runtime.frames_advanced)
    reasoner.stall = Stall(lambda: runtime.frames_advanced)
    runtime.start()
    try:
        result = loop.run()
    finally:
        runtime.stop()
    step = result.steps[0]
    # Half a second at 60 fps is about 30 frames, measured inside each model call.
    assert vision.stall.worst >= 12, vision.stall.windows
    assert reasoner.stall.worst >= 12, reasoner.stall.windows
    assert runtime.max_gap_ms < 400, f"longest runtime freeze was {runtime.max_gap_ms:.0f} ms"
    assert step.executed is True
    assert step.proposal_age_ms is not None and step.proposal_age_ms >= 900


def test_snapshots_are_immutable_and_carry_an_observation_id() -> None:
    adapter = FakeAdapter()
    runtime = ThreadedEmulatorRuntime(adapter, target_fps=120.0)
    runtime.start()
    try:
        first = runtime.latest_snapshot()
        runtime.wait_for_frames(4, timeout_s=2.0)
        later = runtime.latest_snapshot()
    finally:
        runtime.stop()
    assert isinstance(first, RuntimeSnapshot)
    with pytest.raises(FrozenInstanceError):
        first.runtime_frame = 99  # type: ignore[misc]
    assert first.observation_id != later.observation_id
    assert later.runtime_frame >= first.runtime_frame + 4
    assert first.digest and first.frame.pixels


def test_the_runtime_advertises_capabilities_without_naming_an_emulator() -> None:
    runtime = ThreadedEmulatorRuntime(FakeAdapter())
    assert "CONTINUOUS" in runtime.capabilities
    assert "VISION" in runtime.capabilities
    assert "INPUT" in runtime.capabilities
    assert "pyboy" not in repr(runtime.capabilities).lower()


def test_capabilities_come_from_the_wrapped_runtime_when_it_advertises_them() -> None:
    """The core must not infer capabilities from the runtime family name."""

    class Advertising(FakeAdapter):
        capabilities = frozenset({"VISION", "KEYBOARD", "INPUT", "SAVE_STATES"})

    runtime = ThreadedEmulatorRuntime(Advertising())
    assert runtime.capabilities == frozenset(
        {"VISION", "KEYBOARD", "INPUT", "SAVE_STATES", "CONTINUOUS"}
    )
    assert "FRAME_STEPPING" not in runtime.capabilities


def test_a_non_gameboy_runtime_can_supply_its_own_executor() -> None:
    """`ContinuousRuntime` is not a synonym for one emulator family."""
    calls: list[str] = []

    class OtherExecutor:
        def __init__(self, adapter) -> None:
            self.adapter = adapter

        def execute(self, proposal):
            from memnara.agent.execute import ExecutionResult

            calls.append(proposal.action)
            self.adapter.tick(3, render=False)
            return ExecutionResult(ok=True, executed=True, released=True, detail="other")

        def release_all(self) -> None:
            calls.append("release_all")

    adapter = FakeAdapter()
    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=1000.0, executor_factory=OtherExecutor
    )
    runtime.start()
    try:
        result = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=2.0)
    finally:
        runtime.stop()
    assert result.detail == "other"
    assert result.frames_applied == 3
    assert adapter.presses == []
    assert calls[0] == "PRESS_A"
    assert "release_all" in calls


def test_an_owned_gameboy_executor_reports_frames_applied() -> None:
    adapter = FakeAdapter()
    runtime = ThreadedEmulatorRuntime(
        adapter, target_fps=1000.0, should_advance=lambda: False
    )
    runtime.start()
    try:
        result = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=2.0)
    finally:
        runtime.stop()
    assert result.ok is True
    assert result.executed is True
    # Only ticks emulate frames. The button call queues a deferred release.
    executor = GameBoyActionExecutor(adapter)
    assert result.frames_applied == executor.settle_frames
    assert adapter.presses == ["a"]
