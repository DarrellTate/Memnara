"""Continuous runtime: one owner thread advances the game, the agent reads copies.

The owner thread is the only component that touches the emulator. It opens it,
ticks, captures, applies input, releases input, and closes it. Everything else
reads immutable snapshots and submits one bounded command at a time. That keeps a
single-threaded vendor emulator, and a window library with thread affinity,
entirely on one thread while model inference runs elsewhere.

This module is not PyBoy-specific. It drives any `EmulatorAdapter`. A runtime
that already runs on its own clock will implement the same surface differently.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from queue import Empty, Full, Queue

from memnara.agent.actions import ActionProposal
from memnara.agent.execute import ActionExecutor, ExecutionResult
from memnara.agent.observe import digest_pixels
from memnara.emulators.base import EmulatorAdapter, Framebuffer
from memnara.runtime.exceptions import (
    RuntimeBusyError,
    RuntimeShutdownError,
    RuntimeStartupError,
    RuntimeStoppedError,
    RuntimeTimeoutError,
)

# ADR-007 capability names. CONTINUOUS is a proposed addition to that catalog:
# the runtime advances the game without the agent asking for frames. It is
# flagged for project-manager review rather than treated as accepted.
CAPABILITY_VISION = "VISION"
CAPABILITY_INPUT = "INPUT"
CAPABILITY_FRAME_STEPPING = "FRAME_STEPPING"
CAPABILITY_CONTINUOUS = "CONTINUOUS"

# Game Boy hardware is about 60 frames per second. The loop paces to this so a
# slow decision does not let the game race ahead.
DEFAULT_TARGET_FPS = 60.0

# Frames per tick call. Smaller means smoother snapshots and more overhead.
DEFAULT_RUNTIME_CHUNK_FRAMES = 2

# How long a caller waits for a command to finish or for frames to elapse.
DEFAULT_COMMAND_TIMEOUT_S = 30.0
DEFAULT_FRAME_WAIT_TIMEOUT_S = 5.0

# How many recent commands the agent-side executor keeps for diagnostics.
COMMAND_LOG_LIMIT = 16


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Immutable view of the runtime at one instant. Safe to read while it runs."""

    observation_id: str
    frame: Framebuffer
    digest: str
    runtime_frame: int
    captured_at: float
    advancing: bool


@dataclass(frozen=True)
class ActionCommand:
    """One validated gameplay action plus the observation it was reasoned from."""

    action: str
    parameters: dict = field(default_factory=dict)
    source_observation_id: str = ""


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    executed: bool
    released: bool = True
    detail: str = ""
    error: str = ""
    frames_applied: int = 0
    # Set only when the command reached the executor, so an empty value never
    # claims an action landed somewhere it was refused.
    applied_at_observation_id: str = ""


class ContinuousRuntime(ABC):
    """A runtime that advances a game independently of agent decisions."""

    @property
    @abstractmethod
    def capabilities(self) -> frozenset[str]:
        """Advertised capabilities. The core must not infer these from type."""

    @abstractmethod
    def start(self) -> None:
        """Begin advancing. Must publish one snapshot before returning."""

    @abstractmethod
    def stop(self, *, timeout_s: float = 5.0) -> None:
        """Stop advancing, release held input, and join any owner thread."""

    @abstractmethod
    def latest_snapshot(self) -> RuntimeSnapshot:
        """Most recent published snapshot."""

    @abstractmethod
    def wait_for_frames(self, count: int, *, timeout_s: float) -> tuple[RuntimeSnapshot, bool]:
        """Wait for `count` more frames. Returns the snapshot and whether it arrived."""

    @abstractmethod
    def submit(self, command: ActionCommand, *, timeout_s: float) -> CommandResult:
        """Hand one validated action to the owner. At most one may be pending."""


class ThreadedEmulatorRuntime(ContinuousRuntime):
    """Owner thread around an `EmulatorAdapter`. One emulator, one mutator.

    `open_runtime` and `close_runtime` run on the owner thread, so a window
    created by the emulator is created, pumped, and destroyed on one thread.
    """

    def __init__(
        self,
        adapter: EmulatorAdapter,
        *,
        target_fps: float = DEFAULT_TARGET_FPS,
        chunk_frames: int = DEFAULT_RUNTIME_CHUNK_FRAMES,
        render: bool = True,
        should_advance=None,
        can_apply_input=None,
        open_runtime=None,
        close_runtime=None,
        executor_factory=None,
    ) -> None:
        if target_fps <= 0:
            raise ValueError("target_fps must be > 0")
        if chunk_frames < 1:
            raise ValueError("chunk_frames must be >= 1")
        self._adapter = adapter
        self._target_fps = target_fps
        self._chunk_frames = chunk_frames
        self._render = render
        self._should_advance = should_advance or (lambda: True)
        self._can_apply_input = can_apply_input or (lambda: True)
        self._open_runtime = open_runtime
        self._close_runtime = close_runtime
        self._counting = _CountingAdapter(self, adapter)
        if executor_factory is None:
            from memnara.emulators.gameplay import GameBoyActionExecutor

            executor_factory = GameBoyActionExecutor
        self._executor = executor_factory(self._counting)
        self._queue: Queue = Queue(maxsize=1)
        self._cv = threading.Condition()
        self._submit_lock = threading.Lock()
        self._stop = threading.Event()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False
        self._snapshot: RuntimeSnapshot | None = None
        self._inflight: _PendingCommand | None = None
        self._frames = 0
        self._sequence = 0
        self._advancing = False
        self._error = ""
        self._max_gap_ms = 0.0
        self._last_publish = 0.0
        self._owner_thread_name = ""
        self._schedule = 0.0
        self._frame_wait_timeouts = 0

    @property
    def capabilities(self) -> frozenset[str]:
        """Continuous plus whatever the wrapped runtime advertises.

        No adapter advertises capabilities yet, so the fallback below is an
        assumption about the emulator family rather than an advertisement. Giving
        `EmulatorAdapter` a capability surface is an architecture change and
        needs project-manager review.
        """
        advertised = getattr(self._adapter, "capabilities", None)
        if advertised:
            base = frozenset(str(name) for name in advertised)
        else:
            base = frozenset({CAPABILITY_VISION, CAPABILITY_INPUT, CAPABILITY_FRAME_STEPPING})
        return base | {CAPABILITY_CONTINUOUS}

    @property
    def frames_advanced(self) -> int:
        with self._cv:
            return self._frames

    @property
    def error(self) -> str:
        return self._error

    @property
    def max_gap_ms(self) -> float:
        """Longest observed pause between published snapshots."""
        return self._max_gap_ms

    @property
    def frame_wait_timeouts(self) -> int:
        """How often a caller waited for frames that did not arrive."""
        return self._frame_wait_timeouts

    @property
    def owner_thread_name(self) -> str:
        return self._owner_thread_name

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._started:
            raise RuntimeStartupError("runtime already started; create a new runtime")
        self._started = True
        self._thread = threading.Thread(target=self._run, name="memnara-runtime", daemon=True)
        self._thread.start()
        with self._cv:
            ready = self._cv.wait_for(
                lambda: self._snapshot is not None or self._error or self._stopped.is_set(),
                timeout=DEFAULT_FRAME_WAIT_TIMEOUT_S,
            )
        if self._error:
            self.stop()
            raise RuntimeStartupError(self._error)
        if not ready or self._snapshot is None:
            self.stop()
            raise RuntimeStartupError("runtime published no first snapshot")

    def stop(self, *, timeout_s: float = 5.0) -> None:
        """Signal the owner thread and wait for it. Raises if it will not leave.

        The owner thread releases input and closes the runtime itself, so a
        caller must not tear the emulator down after an abandoned join.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_s)
            if thread.is_alive():
                self._error = self._error or "RuntimeShutdownError: owner thread did not stop"
                raise RuntimeShutdownError(
                    f"runtime owner thread still running after {timeout_s:g}s; "
                    "the emulator must not be torn down from another thread"
                )
        self._thread = None
        with self._cv:
            self._advancing = False
            self._cv.notify_all()

    def latest_snapshot(self) -> RuntimeSnapshot:
        if self._error:
            raise RuntimeStoppedError(self._error)
        with self._cv:
            if self._snapshot is None:
                raise RuntimeStartupError("runtime has no snapshot yet")
            return self._snapshot

    def wait_for_frames(
        self, count: int, *, timeout_s: float = DEFAULT_FRAME_WAIT_TIMEOUT_S
    ) -> tuple[RuntimeSnapshot, bool]:
        """Wait for the runtime to advance. A frozen runtime is not an error.

        `PAUSED` legitimately advances nothing, so a timeout is reported rather
        than raised. An owner thread that died is raised.
        """
        if count < 1:
            raise ValueError("count must be >= 1")
        if self._error:
            raise RuntimeStoppedError(self._error)
        with self._cv:
            target = self._frames + count
            self._cv.wait_for(
                lambda: self._frames >= target or self._stopped.is_set(),
                timeout=timeout_s,
            )
            # A clean stop ends the wait without the frames arriving.
            arrived = self._frames >= target
            snapshot = self._snapshot
        if self._error:
            raise RuntimeStoppedError(self._error)
        if snapshot is None:
            raise RuntimeStartupError("runtime has no snapshot yet")
        if not arrived:
            self._frame_wait_timeouts += 1
        return snapshot, arrived

    def submit(self, command: ActionCommand, *, timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S) -> CommandResult:
        """Queue one action and wait for the owner thread to apply it.

        The queue holds one item. A second pending action would be a backlog,
        so it is refused instead of buffered.
        """
        pending = _PendingCommand(command)
        with self._submit_lock:
            if self._stopped.is_set() or self._thread is None:
                return CommandResult(
                    ok=False, executed=False, error="RuntimeStoppedError: runtime is not running"
                )
            try:
                self._queue.put_nowait(pending)
            except Full as exc:
                raise RuntimeBusyError("a gameplay command is already pending") from exc
            if self._stopped.is_set():
                # The owner drained the queue while this was being enqueued.
                self._drain_pending()
        if not pending.done.wait(timeout=timeout_s):
            # The agent has given up on this action, so the owner thread must not
            # press a button for a decision that is now unanswered.
            pending.cancelled = True
            if pending.done.wait(timeout=0.0):
                return pending.result or CommandResult(
                    ok=False, executed=False, error="RuntimeLayerError: command reported no result"
                )
            return CommandResult(
                ok=False, executed=False, error=f"{RuntimeTimeoutError.__name__}: command did not complete"
            )
        return pending.result or CommandResult(
            ok=False, executed=False, error="RuntimeStoppedError: command was discarded"
        )

    def _run(self) -> None:
        self._owner_thread_name = threading.current_thread().name
        opened = False
        try:
            if self._open_runtime is not None:
                self._open_runtime()
            opened = True
            self._publish()
            self._schedule = time.perf_counter()
            advancing = True
            while not self._stop.is_set():
                pending = self._take_command()
                if pending is not None:
                    self._apply(pending)
                    self._publish()
                    continue
                if not self._should_advance():
                    if advancing:
                        advancing = False
                        self._set_advancing(False)
                        self._publish()
                    self._stop.wait(min(self._chunk_frames / self._target_fps, 0.01))
                    self._schedule = time.perf_counter()
                    continue
                if not advancing:
                    advancing = True
                self._set_advancing(True)
                self._adapter.tick(self._chunk_frames, render=self._render)
                self._add_frames(self._chunk_frames)
                self._publish()
                self._pace(self._chunk_frames)
        except BaseException as exc:  # noqa: BLE001 - surfaced through .error
            self._error = f"{type(exc).__name__}: {exc}"
        finally:
            if opened:
                try:
                    self._executor.release_all()
                except Exception as exc:  # noqa: BLE001
                    self._error = self._error or f"ReleaseFailed: {type(exc).__name__}: {exc}"
                if self._close_runtime is not None:
                    try:
                        self._close_runtime()
                    except Exception as exc:  # noqa: BLE001
                        self._error = self._error or f"CloseFailed: {type(exc).__name__}: {exc}"
            self._stopped.set()
            self._drain_pending()
            with self._cv:
                self._advancing = False
                self._cv.notify_all()

    def _pace(self, frames: int) -> None:
        """Hold the emulated clock near the target cadence.

        The vendor emulator runs unthrottled, so every emulated frame is paced
        here, the frames inside an action included. Game time then stays close to
        normal instead of sprinting whenever a button is applied.
        """
        if frames < 1:
            return
        self._schedule += frames / self._target_fps
        delay = self._schedule - time.perf_counter()
        if delay > 0:
            self._stop.wait(delay)
        elif delay < -0.25:
            # Fell far behind. Start fresh rather than banking a debt to repay.
            self._schedule = time.perf_counter()

    def _take_command(self):
        try:
            self._inflight = self._queue.get_nowait()
        except Empty:
            self._inflight = None
        return self._inflight

    def _apply(self, pending: _PendingCommand) -> None:
        """Run one command on the owner thread.

        Semantic freshness is the agent's decision, made before submitting. The
        ownership check is repeated here because this is the only code that can
        actually move a button.

        A command is applied even while `should_advance` is false: that predicate
        governs the free-running clock, not input. A caller that wants a frozen
        runtime to also refuse input must say so through `can_apply_input`.
        """
        before = self.frames_advanced
        if pending.cancelled:
            pending.result = CommandResult(
                ok=False,
                executed=False,
                error="RuntimeTimeoutError: the agent stopped waiting for this action",
            )
            pending.done.set()
            return
        if not self._can_apply_input():
            pending.result = CommandResult(
                ok=False,
                executed=False,
                error="OwnershipDeniedError: the runtime does not accept AI input",
            )
            pending.done.set()
            return
        proposal = ActionProposal(
            action=pending.command.action,
            parameters=dict(pending.command.parameters),
            reason="runtime command",
        )
        try:
            result = self._executor.execute(proposal)
            outcome = CommandResult(
                ok=result.ok,
                executed=result.executed,
                released=result.released,
                detail=result.detail,
                error=result.error,
                frames_applied=self.frames_advanced - before,
                applied_at_observation_id=self._current_observation_id(),
            )
        except Exception as exc:  # noqa: BLE001 - reported to the agent
            released = True
            try:
                self._executor.release_all()
            except Exception:
                released = False
            outcome = CommandResult(
                ok=False,
                executed=False,
                released=released,
                error=f"{type(exc).__name__}: {exc}",
                frames_applied=self.frames_advanced - before,
                applied_at_observation_id=self._current_observation_id(),
            )
        pending.result = outcome
        pending.done.set()

    def _current_observation_id(self) -> str:
        with self._cv:
            return self._snapshot.observation_id if self._snapshot else ""

    def _drain_pending(self) -> None:
        """Fail every command the owner thread will not finish, in flight included."""
        inflight = self._inflight
        if inflight is not None and not inflight.done.is_set():
            inflight.result = CommandResult(
                ok=False, executed=False, error="RuntimeStoppedError: runtime stopped mid-action"
            )
            inflight.done.set()
        while True:
            try:
                pending = self._queue.get_nowait()
            except Empty:
                return
            pending.result = CommandResult(
                ok=False, executed=False, error="RuntimeStoppedError: runtime stopped"
            )
            pending.done.set()

    def _add_frames(self, count: int) -> None:
        with self._cv:
            self._frames += count

    def _set_advancing(self, advancing: bool) -> None:
        with self._cv:
            self._advancing = advancing

    def _publish(self) -> None:
        frame = self._adapter.capture_frame()
        # The same digest the agent uses, so a reader consumes this instead of
        # hashing the frame a second time.
        digest = digest_pixels(frame.pixels)
        now = time.perf_counter()
        with self._cv:
            self._sequence += 1
            # A deliberately frozen runtime is not a freeze, so only measure gaps
            # between publishes while the runtime was advancing.
            if self._last_publish and self._advancing:
                gap = (now - self._last_publish) * 1000
                if gap > self._max_gap_ms:
                    self._max_gap_ms = gap
            self._last_publish = now if self._advancing else 0.0
            self._snapshot = RuntimeSnapshot(
                observation_id=f"r{self._sequence}:{self._frames}",
                frame=frame,
                digest=digest,
                runtime_frame=self._frames,
                captured_at=time.time(),
                advancing=self._advancing,
            )
            self._cv.notify_all()


@dataclass
class _PendingCommand:
    command: ActionCommand
    done: threading.Event = field(default_factory=threading.Event)
    result: CommandResult | None = None
    cancelled: bool = False


class _CountingAdapter:
    """Owner-thread-only proxy that counts and paces emulated frames.

    Only `tick` emulates frames. A button call queues a press and a deferred
    release and advances nothing, so it must not be counted or paced.
    """

    def __init__(self, runtime: ThreadedEmulatorRuntime, adapter: EmulatorAdapter) -> None:
        self._runtime = runtime
        self._adapter = adapter

    def tick(self, count: int = 1, *, render: bool = True) -> bool:
        """Split the advance so snapshots and pacing continue inside a command."""
        chunk = self._runtime._chunk_frames
        remaining = count
        ok = True
        while remaining > 0:
            step = min(chunk, remaining)
            ok = self._adapter.tick(step, render=render) and ok
            self._runtime._add_frames(step)
            remaining -= step
            self._runtime._publish()
            self._runtime._pace(step)
        return ok

    def press_button(self, button, *, delay_frames: int = 1) -> None:
        self._adapter.press_button(button, delay_frames=delay_frames)

    def hold_button(self, button) -> None:
        self._adapter.hold_button(button)

    def release_button(self, button) -> None:
        self._adapter.release_button(button)

    def capture_frame(self) -> Framebuffer:
        return self._adapter.capture_frame()


class RuntimeFrameSource:
    """Frame source the observer reads. Waiting replaces ticking.

    Single-threaded by contract: the agent thread captures a frame and then
    reads `last_observation_id` for the frame it just captured.
    """

    def __init__(self, runtime: ContinuousRuntime, *, wait_timeout_s: float = DEFAULT_FRAME_WAIT_TIMEOUT_S) -> None:
        self._runtime = runtime
        self.wait_timeout_s = wait_timeout_s
        self._last: RuntimeSnapshot | None = None

    @property
    def frames_advanced(self) -> int:
        return getattr(self._runtime, "frames_advanced", 0)

    @property
    def last_observation_id(self) -> str:
        return self._last.observation_id if self._last else ""

    @property
    def last_runtime_frame(self) -> int:
        """Frame counter of the captured frame, not of the runtime right now."""
        return self._last.runtime_frame if self._last else 0

    @property
    def last_captured_at(self) -> float:
        return self._last.captured_at if self._last else 0.0

    @property
    def last_digest(self) -> str:
        """Digest the owner thread already computed for the captured frame."""
        return self._last.digest if self._last else ""

    def latest_snapshot(self) -> RuntimeSnapshot:
        return self._runtime.latest_snapshot()

    def capture_frame(self) -> Framebuffer:
        self._last = self._runtime.latest_snapshot()
        return self._last.frame

    def tick(self, count: int = 1, *, render: bool = True) -> bool:
        """Let the runtime advance `count` frames. The agent does not tick."""
        snapshot, arrived = self._runtime.wait_for_frames(count, timeout_s=self.wait_timeout_s)
        self._last = snapshot
        return arrived


class RuntimeActionExecutor(ActionExecutor):
    """Sends validated actions to the runtime owner. Does not touch the emulator."""

    def __init__(self, runtime: ContinuousRuntime, *, timeout_s: float = DEFAULT_COMMAND_TIMEOUT_S) -> None:
        self._runtime = runtime
        self.timeout_s = timeout_s
        self._observation_id = ""
        self.commands: list[ActionCommand] = []

    def bind_observation(self, observation_id: str) -> None:
        """Record which observation the next action was reasoned from."""
        self._observation_id = observation_id

    def execute(self, proposal: ActionProposal) -> ExecutionResult:
        command = ActionCommand(
            action=proposal.action,
            parameters=dict(proposal.parameters),
            source_observation_id=self._observation_id,
        )
        try:
            result = self._runtime.submit(command, timeout_s=self.timeout_s)
        except RuntimeBusyError:
            # A refused command never reached the runtime, so it is not logged as
            # one that did.
            raise
        self.commands.append(command)
        del self.commands[:-COMMAND_LOG_LIMIT]
        return ExecutionResult(
            ok=result.ok,
            executed=result.executed,
            released=result.released,
            detail=result.detail,
            error=result.error,
            frames_applied=result.frames_applied,
            applied_observation_id=result.applied_at_observation_id,
        )

    def release_all(self) -> None:
        """Input release happens on the owner thread, inside the command."""
        return None
