"""Generic structured action proposal. No emulator or RAM imports."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActionProposal:
    """One bounded gameplay decision. Execution is machine-validated separately."""

    action: str
    parameters: dict[str, object] = field(default_factory=dict)
    reason: str = ""
    confidence: float | None = None
    metadata: dict[str, object] = field(default_factory=dict)  # application-owned; never model-populated


@dataclass(frozen=True)
class ActionRegistry:
    """Allowlist of action names for the current runtime/session."""

    allowed: frozenset[str]

    def contains(self, name: str) -> bool:
        return name in self.allowed


# Default Game Boy / current emulator vocabulary. Native runtimes will inject their own.
DEFAULT_GAMEPLAY_ACTIONS: frozenset[str] = frozenset(
    {
        "MOVE_UP",
        "MOVE_DOWN",
        "MOVE_LEFT",
        "MOVE_RIGHT",
        "PRESS_A",
        "PRESS_B",
        "PRESS_START",
        "PRESS_SELECT",
        "WAIT",
    }
)
