"""Source-labeled disagreement between perception sources. Does not pick a winner."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PerceptionConflict:
    concept: str
    left_source: str
    left_value: str
    right_source: str
    right_value: str
    category: str = "disagreement"
    severity: str = "explicit"
