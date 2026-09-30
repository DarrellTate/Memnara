"""PyBoy-backed EmulatorAdapter. All PyBoy imports stay in this module."""

from __future__ import annotations

from pathlib import Path

from memnara.emulators.base import EmulatorAdapter, Framebuffer
from memnara.emulators.buttons import Button, normalize_button
from memnara.emulators.exceptions import (
    AdapterClosedError,
    CaptureUnavailableError,
    EmulatorStartupError,
    InvalidButtonError,
    LoadStateError,
    MemoryReadError,
    RomNotFoundError,
    RomUnreadableError,
    SaveStateError,
)

NATIVE_WIDTH = 160
NATIVE_HEIGHT = 144


class PyBoyAdapter(EmulatorAdapter):
    def __init__(
        self,
        *,
        window: str = "null",
        sound_emulated: bool = False,
        ram_file: str | Path | None = None,
    ) -> None:
        self._window = window
        self._sound_emulated = sound_emulated
        self._ram_file = Path(ram_file) if ram_file is not None else None
        self._ram_handle = None
        self._pyboy = None
        self._version = ""
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open and self._pyboy is not None

    @property
    def backend_version(self) -> str:
        return self._version

    @property
    def native_resolution(self) -> tuple[int, int]:
        return (NATIVE_WIDTH, NATIVE_HEIGHT)

    @property
    def cartridge_title(self) -> str | None:
        self._require_open()
        title = getattr(self._pyboy, "cartridge_title", None)
        return str(title) if title else None

    def start(self, rom_path: str | Path) -> None:
        path = Path(rom_path)
        if not path.exists():
            raise RomNotFoundError(f"ROM not found: {path}")
        if not path.is_file():
            raise RomUnreadableError(f"ROM path is not a file: {path}")
        if self._open:
            self.stop()
        try:
            from pyboy import PyBoy
        except ImportError as exc:
            raise EmulatorStartupError("pyboy is not installed") from exc
        try:
            from pyboy.utils import PyBoyException, PyBoyInvalidInputException
        except ImportError:
            PyBoyException = Exception
            PyBoyInvalidInputException = Exception
        try:
            import importlib.metadata as metadata

            self._version = metadata.version("pyboy")
        except Exception:
            self._version = "unknown"
        try:
            kwargs: dict = {
                "window": self._window,
                "sound_emulated": self._sound_emulated,
            }
            if self._ram_file is not None:
                if not self._ram_file.is_file() or self._ram_file.stat().st_size <= 0:
                    raise EmulatorStartupError(
                        "ram_file must be an existing non-empty battery file "
                        "(PyBoy 2.7.0 needs a file-like handle; do not use a path string)"
                    )
                self._ram_file.parent.mkdir(parents=True, exist_ok=True)
                self._ram_handle = self._ram_file.open("r+b")
                kwargs["ram_file"] = self._ram_handle
            self._pyboy = PyBoy(str(path), **kwargs)
        except FileNotFoundError as exc:
            if self._ram_handle is not None:
                self._ram_handle.close()
                self._ram_handle = None
            raise RomNotFoundError(str(exc)) from exc
        except (OSError, ValueError, PyBoyException, PyBoyInvalidInputException) as exc:
            if self._ram_handle is not None:
                self._ram_handle.close()
                self._ram_handle = None
            raise EmulatorStartupError(f"PyBoy failed to start: {exc}") from exc
        except Exception as exc:
            if self._ram_handle is not None:
                self._ram_handle.close()
                self._ram_handle = None
            raise EmulatorStartupError(f"PyBoy failed to start: {exc}") from exc
        try:
            self._pyboy.set_emulation_speed(0)
            self._open = True
        except Exception as exc:
            try:
                self._pyboy.stop(save=False)
            except Exception:
                pass
            if self._ram_handle is not None:
                self._ram_handle.close()
                self._ram_handle = None
            self._pyboy = None
            self._open = False
            raise EmulatorStartupError(f"PyBoy started but could not be configured: {exc}") from exc

    def stop(self) -> None:
        pyboy = self._pyboy
        handle = self._ram_handle
        self._pyboy = None
        self._ram_handle = None
        self._open = False
        if pyboy is not None:
            pyboy.stop(save=False)
        if handle is not None:
            handle.close()

    def tick(self, count: int = 1, *, render: bool = True) -> bool:
        self._require_open()
        if count < 1:
            raise ValueError("tick count must be >= 1")
        return bool(self._pyboy.tick(count, render=render, sound=False))

    def capture_frame(self) -> Framebuffer:
        self._require_open()
        try:
            array = self._pyboy.screen.ndarray
            if array is None:
                raise CaptureUnavailableError("PyBoy screen ndarray is unavailable")
            pixels = bytes(array.copy().tobytes())
            height, width = int(array.shape[0]), int(array.shape[1])
            return Framebuffer(
                width=width,
                height=height,
                pixel_format="RGBA",
                pixels=pixels,
                source="pyboy.screen.ndarray",
            )
        except CaptureUnavailableError:
            raise
        except Exception as exc:
            raise CaptureUnavailableError(f"Framebuffer capture failed: {exc}") from exc

    def press_button(self, button: Button | str, *, delay_frames: int = 1) -> None:
        self._require_open()
        name = normalize_button(button)
        try:
            self._pyboy.button(name, delay=delay_frames)
        except Exception as exc:
            raise InvalidButtonError(f"PyBoy rejected button {name!r}: {exc}") from exc

    def hold_button(self, button: Button | str) -> None:
        self._require_open()
        name = normalize_button(button)
        try:
            self._pyboy.button_press(name)
        except Exception as exc:
            raise InvalidButtonError(f"PyBoy rejected button press {name!r}: {exc}") from exc

    def release_button(self, button: Button | str) -> None:
        self._require_open()
        name = normalize_button(button)
        try:
            self._pyboy.button_release(name)
        except Exception as exc:
            raise InvalidButtonError(f"PyBoy rejected button release {name!r}: {exc}") from exc

    def set_speed(self, speed: int) -> None:
        self._require_open()
        if speed < 0:
            raise ValueError("speed must be >= 0")
        self._pyboy.set_emulation_speed(int(speed))

    def save_state(self, path: str | Path) -> None:
        self._require_open()
        dest = Path(path)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as handle:
                self._pyboy.save_state(handle)
        except OSError as exc:
            raise SaveStateError(f"Could not write save state {dest}: {exc}") from exc
        except Exception as exc:
            raise SaveStateError(f"Save state failed: {exc}") from exc

    def load_state(self, path: str | Path) -> None:
        self._require_open()
        source = Path(path)
        if not source.exists():
            raise LoadStateError(f"Save-state file missing: {source}")
        try:
            with source.open("rb") as handle:
                self._pyboy.load_state(handle)
        except LoadStateError:
            raise
        except OSError as exc:
            raise LoadStateError(f"Could not read save state {source}: {exc}") from exc
        except Exception as exc:
            raise LoadStateError(f"Load state failed: {exc}") from exc

    def read_bytes(self, address: int, length: int) -> bytes:
        self._require_open()
        if length < 1:
            raise MemoryReadError("read length must be >= 1")
        if address < 0 or address > 0xFFFF:
            raise MemoryReadError(f"address out of range: {address:#x}")
        end = address + length
        if end > 0x10000:
            raise MemoryReadError(f"read {length} bytes from {address:#x} exceeds 16-bit bus")
        try:
            region = self._pyboy.memory[address:end]
            data = bytes(region)
        except Exception as exc:
            raise MemoryReadError(f"PyBoy memory read failed at {address:#x}: {exc}") from exc
        if len(data) != length:
            raise MemoryReadError(
                f"short read at {address:#x}: expected {length}, got {len(data)}"
            )
        return data

    def _require_open(self) -> None:
        if not self.is_open:
            raise AdapterClosedError("PyBoyAdapter is closed")
