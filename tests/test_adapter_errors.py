from pathlib import Path
from types import SimpleNamespace

import pytest

from memnara.emulators.exceptions import (
    AdapterClosedError,
    CaptureUnavailableError,
    LoadStateError,
    MemoryReadError,
    RomNotFoundError,
    SaveStateError,
)
from memnara.emulators.pyboy_adapter import PyBoyAdapter


def test_start_missing_rom(tmp_path: Path) -> None:
    adapter = PyBoyAdapter()
    with pytest.raises(RomNotFoundError):
        adapter.start(tmp_path / "nope.gb")


def test_ops_when_closed() -> None:
    adapter = PyBoyAdapter()
    with pytest.raises(AdapterClosedError):
        adapter.tick()
    with pytest.raises(AdapterClosedError):
        adapter.capture_frame()
    with pytest.raises(AdapterClosedError):
        adapter.press_button("a")
    with pytest.raises(AdapterClosedError):
        adapter.save_state("x.state")
    with pytest.raises(AdapterClosedError):
        adapter.load_state("x.state")
    with pytest.raises(AdapterClosedError):
        adapter.read_bytes(0xC000, 1)


def test_load_state_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    adapter = PyBoyAdapter()
    adapter._open = True
    adapter._pyboy = SimpleNamespace()
    with pytest.raises(LoadStateError):
        adapter.load_state(tmp_path / "missing.state")


def test_save_state_path_failure(tmp_path: Path) -> None:
    adapter = PyBoyAdapter()
    adapter._open = True

    class Boom:
        def save_state(self, handle) -> None:  # noqa: ANN001
            raise OSError("disk full")

    adapter._pyboy = Boom()
    # Directory that cannot be created: use a file as parent.
    blocker = tmp_path / "notdir"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(SaveStateError):
        adapter.save_state(blocker / "x.state")


def test_capture_when_screen_missing() -> None:
    adapter = PyBoyAdapter()
    adapter._open = True
    adapter._pyboy = SimpleNamespace(screen=SimpleNamespace(ndarray=None))
    with pytest.raises(CaptureUnavailableError):
        adapter.capture_frame()


def test_stop_is_idempotent() -> None:
    adapter = PyBoyAdapter()
    adapter.stop()
    adapter.stop()
    assert adapter.is_open is False


def test_tick_requires_positive_count() -> None:
    adapter = PyBoyAdapter()
    adapter._open = True
    adapter._pyboy = object()
    with pytest.raises(ValueError):
        adapter.tick(0)


def test_read_bytes_bounds() -> None:
    adapter = PyBoyAdapter()
    adapter._open = True
    adapter._pyboy = object()
    with pytest.raises(MemoryReadError):
        adapter.read_bytes(-1, 1)
    with pytest.raises(MemoryReadError):
        adapter.read_bytes(0xFFFF, 2)
