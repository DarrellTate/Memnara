"""Live PyBoy continuous runtime. Skips cleanly when the operator ROM is absent.

These tests answer one question the synthetic suite cannot: does a real,
single-threaded emulator stay safe and keep advancing while a slow caller
thinks, with every emulator call on the owner thread.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

# `memnara.agent` must initialize before `memnara.config`, which otherwise enters a
# pre-existing package import cycle through `memnara.perception`.
import memnara.agent  # noqa: F401
from memnara.config import load_config
from memnara.emulators.base import Button
from memnara.emulators.gameplay import GameBoyActionExecutor
from memnara.emulators.pyboy_adapter import PyBoyAdapter
from memnara.runtime.continuous import (
    ActionCommand,
    RuntimeFrameSource,
    ThreadedEmulatorRuntime,
)

pytestmark = pytest.mark.integration

TARGET_FPS = 60.0
HEADLESS_WINDOW = "null"
VISIBLE_WINDOW = "SDL2"


@pytest.fixture(scope="module")
def rom_file() -> Path:
    path = load_config().rom_path
    if not path.is_file():
        pytest.skip(f"Operator ROM not present at {path}")
    return path


class WatchedAdapter(PyBoyAdapter):
    """Real adapter that records which thread made each emulator call."""

    def __init__(self, *, window: str = HEADLESS_WINDOW) -> None:
        super().__init__(window=window, sound_emulated=False)
        self.threads: set[str] = set()
        self.overlaps = 0
        self._busy = False
        self._guard = threading.Lock()

    @property
    def frame_count(self) -> int:
        """PyBoy's own frame counter, read for test evidence only."""
        return int(self._pyboy.frame_count)

    def _note(self) -> None:
        self.threads.add(threading.current_thread().name)
        with self._guard:
            if self._busy:
                self.overlaps += 1

    def start(self, rom):  # type: ignore[override]
        self._note()
        return super().start(rom)

    def stop(self) -> None:  # type: ignore[override]
        self._note()
        return super().stop()

    def tick(self, count: int = 1, *, render: bool = True) -> bool:  # type: ignore[override]
        self._note()
        with self._guard:
            self._busy = True
        try:
            return super().tick(count, render=render)
        finally:
            with self._guard:
                self._busy = False

    def capture_frame(self):  # type: ignore[override]
        self._note()
        return super().capture_frame()

    def press_button(self, button, *, delay_frames: int = 1) -> None:  # type: ignore[override]
        self._note()
        return super().press_button(button, delay_frames=delay_frames)

    def release_button(self, button) -> None:  # type: ignore[override]
        self._note()
        return super().release_button(button)


def _runtime(adapter: WatchedAdapter, rom: Path) -> ThreadedEmulatorRuntime:
    return ThreadedEmulatorRuntime(
        adapter,
        target_fps=TARGET_FPS,
        render=False,
        open_runtime=lambda: adapter.start(rom),
        close_runtime=adapter.stop,
    )


def test_real_pyboy_is_only_ever_touched_by_the_owner_thread(rom_file: Path) -> None:
    adapter = WatchedAdapter()
    runtime = _runtime(adapter, rom_file)
    runtime.start()
    try:
        source = RuntimeFrameSource(runtime)
        for _ in range(4):
            source.capture_frame()
            source.tick(6)
        runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=10.0)
    finally:
        runtime.stop()
    assert adapter.threads == {"memnara-runtime"}, adapter.threads
    assert adapter.overlaps == 0
    assert adapter.is_open is False
    assert runtime.error == ""


def test_real_pyboy_keeps_advancing_while_a_slow_caller_thinks(rom_file: Path) -> None:
    adapter = WatchedAdapter()
    runtime = _runtime(adapter, rom_file)
    runtime.start()
    try:
        source = RuntimeFrameSource(runtime)
        first = source.capture_frame()
        before = runtime.frames_advanced
        time.sleep(1.0)  # stands in for a local model call
        advanced = runtime.frames_advanced - before
        later = source.capture_frame()
    finally:
        runtime.stop()
    # One wall-clock second at 60 fps, with generous slack for a loaded machine.
    assert 30 <= advanced <= 120, advanced
    assert first.pixels != later.pixels, "the emulator produced identical frames"


def test_real_pyboy_emulates_the_frames_the_runtime_counts(rom_file: Path) -> None:
    """A button call queues a deferred release and emulates nothing itself.

    The real emulator's own frame counter is the authority here, so this proves
    emulation rather than the runtime agreeing with its own bookkeeping.
    """
    adapter = WatchedAdapter()
    emulated: list[int] = []
    runtime = ThreadedEmulatorRuntime(
        adapter,
        target_fps=1000.0,
        render=False,
        should_advance=lambda: False,
        open_runtime=lambda: (adapter.start(rom_file), emulated.append(adapter.frame_count)),
        close_runtime=adapter.stop,
    )
    runtime.start()
    try:
        before = runtime.frames_advanced
        result = runtime.submit(ActionCommand(action="PRESS_A"), timeout_s=10.0)
        counted = runtime.frames_advanced - before
        emulated.append(adapter.frame_count)
    finally:
        runtime.stop()
    settle = GameBoyActionExecutor(adapter).settle_frames
    assert result.ok is True
    assert result.frames_applied == counted
    # Settle ticks only. The tap delay is a release schedule, not emulation.
    assert counted == settle, counted
    # PyBoy's own counter moved by the same amount the runtime claimed.
    assert emulated[1] - emulated[0] == settle, emulated


def test_a_visible_window_runs_on_the_owner_thread_too(rom_file: Path) -> None:
    """The visible window must be the controlled runtime, created where it is pumped.

    SDL2 has thread affinity, so creating the window on one thread and pumping it
    on another is the failure this guards against.
    """
    adapter = WatchedAdapter(window=VISIBLE_WINDOW)
    runtime = ThreadedEmulatorRuntime(
        adapter,
        target_fps=TARGET_FPS,
        render=True,
        open_runtime=lambda: adapter.start(rom_file),
        close_runtime=adapter.stop,
    )
    runtime.start()
    try:
        first = runtime.latest_snapshot()
        time.sleep(1.0)
        later = runtime.latest_snapshot()
    finally:
        runtime.stop()
    assert adapter.threads == {"memnara-runtime"}, adapter.threads
    assert later.runtime_frame - first.runtime_frame >= 30
    assert later.digest != first.digest, "the visible window published no new frame"
    assert runtime.error == ""


def test_a_slow_decision_does_not_freeze_the_real_runtime(rom_file: Path) -> None:
    """The authorized before/after measurement, against the real emulator.

    This is the committed form of the headline claim: three seconds of model
    latency must not mean zero frames advanced.
    """
    model_latency_s = 3.0
    adapter = WatchedAdapter()
    runtime = _runtime(adapter, rom_file)
    runtime.start()
    try:
        started = time.perf_counter()
        before = runtime.frames_advanced
        time.sleep(model_latency_s)
        advanced = runtime.frames_advanced - before
        elapsed = time.perf_counter() - started
        longest_freeze_ms = runtime.max_gap_ms
    finally:
        runtime.stop()
    effective_fps = advanced / elapsed
    print(
        f"\ncontinuous runtime over {model_latency_s:g}s of model latency: "
        f"{advanced} frames, {effective_fps:.1f} effective emulated fps, "
        f"longest freeze {longest_freeze_ms:.0f} ms"
    )
    # Frame-stepped, this window advances exactly 0 frames.
    assert advanced > 0
    assert advanced >= TARGET_FPS * model_latency_s * 0.5, advanced
    assert longest_freeze_ms < 500, longest_freeze_ms


def test_real_pyboy_shuts_down_without_a_held_button(rom_file: Path) -> None:
    """Release must happen while the emulator is still open, or it does nothing.

    `GameBoyActionExecutor.release_all` swallows an adapter-closed error, so the
    open flag is recorded with each release rather than only the button name.
    """
    adapter = WatchedAdapter()
    released: list[tuple[str, bool]] = []
    original = adapter.release_button

    def record(button) -> None:
        name = button.value if isinstance(button, Button) else str(button)
        released.append((name, adapter.is_open))
        original(button)

    adapter.release_button = record  # type: ignore[method-assign]
    runtime = _runtime(adapter, rom_file)
    runtime.start()
    try:
        runtime.wait_for_frames(4, timeout_s=5.0)
    finally:
        runtime.stop()
    assert {name for name, _ in released} == {button.value for button in Button}
    assert all(was_open for _, was_open in released), "a button was released after close"
    assert runtime.running is False
    assert adapter.is_open is False
