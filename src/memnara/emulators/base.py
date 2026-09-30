"""Generic emulator adapter. No PyBoy types, no game-specific RAM maps."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memnara.emulators.buttons import Button


@dataclass(frozen=True)
class Framebuffer:
    width: int
    height: int
    pixel_format: str
    pixels: bytes
    source: str


class EmulatorAdapter(ABC):
    """Replaceable emulator backend. Implementations must not leak vendor types."""

    @abstractmethod
    def start(self, rom_path: str | Path) -> None:
        """Load a user-provided ROM and start emulation."""

    @abstractmethod
    def stop(self) -> None:
        """Shut down the emulator and release resources."""

    @abstractmethod
    def tick(self, count: int = 1, *, render: bool = True) -> bool:
        """Advance one or more frames. Returns True while emulation is running."""

    @abstractmethod
    def capture_frame(self) -> Framebuffer:
        """Copy the current framebuffer. Caller owns the returned bytes."""

    @abstractmethod
    def press_button(self, button: Button | str, *, delay_frames: int = 1) -> None:
        """Press then auto-release after delay_frames ticks."""

    @abstractmethod
    def hold_button(self, button: Button | str) -> None:
        """Hold a button until release_button."""

    @abstractmethod
    def release_button(self, button: Button | str) -> None:
        """Release a held button."""

    @abstractmethod
    def set_speed(self, speed: int) -> None:
        """Set emulation speed multiplier. 0 means unlimited."""

    @property
    @abstractmethod
    def native_resolution(self) -> tuple[int, int]:
        """(width, height) of the native framebuffer."""

    @abstractmethod
    def save_state(self, path: str | Path) -> None:
        """Write a backend-specific save state to path."""

    @abstractmethod
    def load_state(self, path: str | Path) -> None:
        """Restore a backend-specific save state from path."""

    @abstractmethod
    def read_bytes(self, address: int, length: int) -> bytes:
        """Read-only copy of `length` bytes from a 16-bit bus address."""

    def read_byte(self, address: int) -> int:
        data = self.read_bytes(address, 1)
        return data[0]

    @property
    @abstractmethod
    def is_open(self) -> bool:
        """True while the emulator session is active."""

    @property
    @abstractmethod
    def backend_version(self) -> str:
        """Recorded emulator library version."""

    @property
    @abstractmethod
    def cartridge_title(self) -> str | None:
        """Header title if the backend exposes it. Not a RAM map."""

    def __enter__(self) -> EmulatorAdapter:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.stop()
