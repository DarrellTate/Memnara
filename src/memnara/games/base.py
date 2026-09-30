"""Generic game adapter. No title-specific RAM addresses."""

from __future__ import annotations

from abc import ABC, abstractmethod

from memnara.emulators.base import EmulatorAdapter
from memnara.rom_identity import RomIdentity


class GameAdapter(ABC):
    @property
    @abstractmethod
    def game_id(self) -> str:
        """Stable adapter id for a locally installed integration."""

    @abstractmethod
    def compatible(self, identity: RomIdentity) -> bool:
        """True only when this adapter's structured map may be applied."""

    @abstractmethod
    def require_compatible(self, identity: RomIdentity) -> None:
        """Raise if the ROM identity is unsupported."""

    @abstractmethod
    def get_state(self, emulator: EmulatorAdapter):
        """Read-only structured state. Values retain source provenance."""

    @abstractmethod
    def detect_mode(self, emulator: EmulatorAdapter):
        """Best-effort mode. May be INFERRED."""
