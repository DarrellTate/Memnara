"""Bounded stuck detection and early recovery. Coordinates are optional."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StuckState(str, Enum):
    NORMAL = "NORMAL"
    SUSPECTED_STUCK = "SUSPECTED_STUCK"
    CHANGE_STRATEGY = "CHANGE_STRATEGY"
    EXPLORE = "EXPLORE"
    INTERVENTION_REQUIRED = "INTERVENTION_REQUIRED"


@dataclass(frozen=True)
class StuckConfig:
    unchanged_limit: int = 3
    same_action_limit: int = 3
    max_recovery_attempts: int = 3


class StuckDetector:
    def __init__(self, config: StuckConfig | None = None) -> None:
        self.config = config or StuckConfig()
        self.state = StuckState.NORMAL
        self.discouraged: tuple[str, ...] = ()
        self._unchanged = 0
        self._same_action = 0
        self._recovery = 0
        self._last_fingerprint: str | None = None
        self._last_action: str | None = None

    def update(self, *, fingerprint: str, action: str | None, progressed: bool) -> StuckState:
        if progressed:
            self._unchanged = 0
            self._same_action = 0
            self._recovery = 0
            self.state = StuckState.NORMAL
            self.discouraged = ()
            self._last_fingerprint = fingerprint
            self._last_action = action
            return self.state

        if self._last_fingerprint is not None and fingerprint == self._last_fingerprint:
            self._unchanged += 1
        else:
            self._unchanged = 1 if self._last_fingerprint is not None else 0
        if action and action == self._last_action:
            self._same_action += 1
        else:
            self._same_action = 1 if action else 0
        self._last_fingerprint = fingerprint
        if action:
            self._last_action = action

        stuckish = (
            self._unchanged >= self.config.unchanged_limit
            or self._same_action >= self.config.same_action_limit
        )
        if self.state is StuckState.NORMAL:
            if stuckish:
                self.state = StuckState.SUSPECTED_STUCK
                self.discouraged = (action,) if action else ()
                self._recovery = 1
        elif self.state is StuckState.SUSPECTED_STUCK:
            self.state = StuckState.CHANGE_STRATEGY
            if action and action not in self.discouraged:
                self.discouraged = self.discouraged + (action,)
            self._recovery += 1
        elif self.state is StuckState.CHANGE_STRATEGY:
            self.state = StuckState.EXPLORE
            self._recovery += 1
        elif self.state is StuckState.EXPLORE:
            self._recovery += 1
            if self._recovery > self.config.max_recovery_attempts:
                self.state = StuckState.INTERVENTION_REQUIRED
        return self.state
