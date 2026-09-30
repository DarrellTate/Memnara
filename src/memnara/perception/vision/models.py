"""Structured visual observation. Provenance is VISUAL, never RAM."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SceneType(str, Enum):
    BOOT_OR_TITLE = "BOOT_OR_TITLE"
    OVERWORLD = "OVERWORLD"
    DIALOGUE = "DIALOGUE"
    MENU = "MENU"
    BATTLE = "BATTLE"
    STATUS_OR_PARTY = "STATUS_OR_PARTY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class VisualEntity:
    name: str
    kind: str = ""
    notes: str = ""


@dataclass(frozen=True)
class VisualObservation:
    scene_type: SceneType
    description: str
    visible_text: tuple[str, ...]
    entities: tuple[VisualEntity, ...]
    menu_visible: bool
    dialogue_visible: bool
    battle_visible: bool
    confidence: float
    notable_changes: str
    source: str = "VISUAL"
    model: str = ""
    scale: int = 1
    image_width: int = 0
    image_height: int = 0
    latency_ms: float | None = None
    eval_count: int | None = None
    notes: str = ""
