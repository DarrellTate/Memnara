"""Action executor contract. Implementations map validated names to runtime input."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from memnara.agent.actions import ActionProposal


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    executed: bool
    released: bool = True
    detail: str = ""
    error: str = ""
    # Runtimes that advance on their own clock report what the action actually
    # cost and which published observation it landed on. Zero and empty mean the
    # executor does not measure them, not that nothing happened.
    frames_applied: int = 0
    applied_observation_id: str = ""


class ActionExecutor(ABC):
    @abstractmethod
    def execute(self, proposal: ActionProposal) -> ExecutionResult:
        """Apply one validated action. Must release held input before returning."""

    def release_all(self) -> None:
        """Best-effort input release. Default is no-op."""
