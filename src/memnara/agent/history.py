"""In-memory recent-step history. Not persistent memory."""

from __future__ import annotations

from dataclasses import dataclass

from memnara.agent.actions import ActionProposal


@dataclass(frozen=True)
class RecentStep:
    step: int
    before_summary: str
    before_fingerprint: str
    proposal: ActionProposal | None
    validation_ok: bool
    executed: bool
    execution_ok: bool
    after_summary: str
    after_fingerprint: str
    screen_changed: bool
    state_changed: bool
    stuck_state: str
    progress: bool
    error: str = ""
    perception_ms: float | None = None
    reasoning_ms: float | None = None
    execution_ms: float | None = None
    total_ms: float | None = None
    interaction_mode: str = "NON_BATTLE"
    movement_outcome: str = "NOT_APPLICABLE"


class StepHistory:
    def __init__(self, *, maxlen: int = 16) -> None:
        self.maxlen = maxlen
        self._items: list[RecentStep] = []

    def append(self, step: RecentStep) -> None:
        self._items.append(step)
        if len(self._items) > self.maxlen:
            del self._items[0 : len(self._items) - self.maxlen]

    @property
    def items(self) -> tuple[RecentStep, ...]:
        return tuple(self._items)

    def action_lines(self, *, limit: int = 4) -> tuple[str, ...]:
        lines: list[str] = []
        for item in self._items[-limit:]:
            action = item.proposal.action if item.proposal else "NONE"
            lines.append(f"{action} → {item.movement_outcome}")
        return tuple(lines)
