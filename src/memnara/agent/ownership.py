"""Minimal control-ownership gate. M13 owns polished takeover UX."""

from __future__ import annotations

from enum import Enum


class ControlOwner(str, Enum):
    AI_CONTROL = "AI_CONTROL"
    USER_CONTROL = "USER_CONTROL"
    CONVERSATION = "CONVERSATION"
    PAUSED = "PAUSED"


class ControlGate:
    """Autonomous gameplay input is allowed only while owner is AI_CONTROL."""

    def __init__(self, owner: ControlOwner = ControlOwner.AI_CONTROL) -> None:
        self.owner = owner

    def allows_gameplay(self) -> bool:
        return self.owner is ControlOwner.AI_CONTROL

    def set_owner(self, owner: ControlOwner) -> None:
        self.owner = owner
