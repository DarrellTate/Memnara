"""Synthetic structured state for public tests. No commercial-title data."""

from __future__ import annotations

from dataclasses import dataclass

from memnara.perception.context import StructuredFact, StructuredGameState


@dataclass
class SyntheticSnapshot:
    map_id: int = 12
    map_id_confidence: str = "VERIFIED"
    party_count: int = 0
    party_count_confidence: str = "SOURCE_DOCUMENTED"
    mode: str = "OVERWORLD"
    mode_confidence: str = "INFERRED"
    is_in_battle: int | bool | None = 0
    is_in_battle_confidence: str = "SOURCE_DOCUMENTED"
    player_x: int = 3
    player_x_confidence: str = "SOURCE_DOCUMENTED"
    fairness: str = "PLAYER_AVAILABLE"


def wrap_snapshot(snap: SyntheticSnapshot) -> StructuredGameState:
    raw = snap.is_in_battle
    if raw is None:
        battle: bool | None = None
    elif isinstance(raw, bool):
        battle = raw
    elif isinstance(raw, int):
        battle = raw != 0
    else:
        battle = None
    facts = (
        StructuredFact(
            key="map_id",
            value=snap.map_id,
            source="RAM",
            confidence=snap.map_id_confidence,
            fairness=snap.fairness,
        ),
        StructuredFact(
            key="party_count",
            value=snap.party_count,
            source="RAM",
            confidence=snap.party_count_confidence,
            fairness=snap.fairness,
        ),
        StructuredFact(
            key="mode",
            value=snap.mode,
            source="RAM",
            confidence=snap.mode_confidence,
            fairness=snap.fairness,
        ),
    )
    return StructuredGameState(
        source="RAM",
        adapter_id="synthetic",
        is_in_battle=battle,
        is_in_battle_confidence=snap.is_in_battle_confidence,
        facts=facts,
        payload=snap,
    )
