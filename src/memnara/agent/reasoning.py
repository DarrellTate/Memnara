"""Reasoning prompt and JSON parse. Explicit structured decision only."""

from __future__ import annotations

from abc import ABC, abstractmethod

from memnara.agent.actions import ActionProposal
from memnara.agent.battle import BATTLE_PROMPT_BLOCK, InteractionMode, derive_battle_view
from memnara.agent.validator import ActionValidator
from memnara.perception.context import PerceptionContext
from memnara.perception.fusion import compact_summary

PROPOSAL_FORMAT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"type": "string"},
        "parameters": {"type": "object"},
        "reason": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["action", "reason"],
}

SYSTEM_PROMPT = """You are Memnara, a local agent controlling a video game through a constrained action interface.

Rules:
- You receive fused current evidence (visual interpretation plus optional labeled game state).
- Use only that evidence. Do not claim hidden knowledge, walkthroughs, memory addresses, or emulator internals.
- Propose exactly ONE gameplay action from the allowed list.
- Unsupported action names are invalid.
- Uncertainty is acceptable. Prefer a short-term exploratory action over invented certainty.
- Do not output multiple actions, scripts, shell commands, or code.
- Do not write RAM or suggest privileged state.
- Short reason only: why this one action might make progress.
- If the scene looks like a menu or dialogue, PRESS_A or PRESS_B or WAIT may be more appropriate than walking.
- If evidence shows a battle, you may still use generic buttons; you do not have battle strategy.
- If the goal is to explore or move through terrain to trigger an encounter, prefer a movement action. Do not choose WAIT only because standing still might cause a movement-triggered encounter. WAIT remains valid when visible evidence shows waiting is useful, such as dialogue, a menu, or an animation that is still changing.

Return JSON matching the schema: action, optional parameters, reason, optional confidence (0-1).
"""


def build_user_prompt(
    *,
    context: PerceptionContext,
    goal: str,
    allowed: frozenset[str],
    stuck_state: str,
    discouraged: tuple[str, ...],
    history_lines: tuple[str, ...],
) -> str:
    summary = compact_summary(context)
    allowed_text = ", ".join(sorted(allowed))
    hist = "\n".join(history_lines) if history_lines else "(none)"
    discouraged_text = ", ".join(discouraged) if discouraged else "(none)"
    view = derive_battle_view(context)
    battle_block = ""
    if view.mode is InteractionMode.BATTLE_ACTIVE:
        battle_block = BATTLE_PROMPT_BLOCK + "\n"
    return (
        f"{battle_block}"
        f"GOAL: {goal}\n"
        f"ALLOWED_ACTIONS: {allowed_text}\n"
        f"STUCK_STATE: {stuck_state}\n"
        f"DISCOURAGED_ACTIONS: {discouraged_text}\n"
        f"RECENT_STEPS:\n{hist}\n"
        f"CURRENT_EVIDENCE:\n{summary}\n"
        "Propose exactly one allowed action. For WAIT you may set parameters.frames (1-180). "
        "Other actions take no parameters."
    )


class ReasoningProvider(ABC):
    @abstractmethod
    def propose(
        self,
        *,
        context: PerceptionContext,
        goal: str,
        stuck_state: str,
        discouraged: tuple[str, ...],
        history_lines: tuple[str, ...],
        validator: ActionValidator,
    ) -> ActionProposal:
        """Return one validated proposal. Must not execute input."""
