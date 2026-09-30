"""Generic perception context. Sources stay labeled. RAM and window may be absent."""

from __future__ import annotations

from dataclasses import dataclass

from memnara.perception.conflicts import PerceptionConflict
from memnara.perception.vision.models import VisualObservation


@dataclass(frozen=True)
class WindowState:
    """Reserved for native PC window/process metadata. Unused in M4; do not invent values."""

    source: str = "WINDOW"


@dataclass(frozen=True)
class StructuredFact:
    """Adapter-chosen, source-labeled fact. Generic fusion does not interpret the key."""

    key: str
    value: object
    source: str
    confidence: str
    fairness: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class StructuredGameState:
    """Optional structured state. Payload stays opaque; facts are supplied at the game/runtime edge."""

    source: str = "RAM"
    adapter_id: str = ""
    is_in_battle: bool | None = None
    is_in_battle_confidence: str | None = None
    facts: tuple[StructuredFact, ...] = ()
    payload: object | None = None


@dataclass(frozen=True)
class PerceptionMetadata:
    sources: tuple[str, ...]
    fusion: str = "deterministic"
    notes: str = ""


@dataclass(frozen=True)
class PerceptionContext:
    visual: VisualObservation | None
    game_state: StructuredGameState | None
    window_state: WindowState | None
    conflicts: tuple[PerceptionConflict, ...]
    metadata: PerceptionMetadata
