"""Generic battle interaction view derived from perception.

This is not a combat system. It does not name moves, menus, or title mechanics.
M4 fusion is not modified and does not pick a winning battle source.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from memnara.perception.context import PerceptionContext


class InteractionMode(str, Enum):
    NON_BATTLE = "NON_BATTLE"
    BATTLE_ACTIVE = "BATTLE_ACTIVE"


@dataclass(frozen=True)
class BattleView:
    """Agent-side view. Sources stay on the perception context."""

    mode: InteractionMode
    visual_battle_visible: bool | None
    structured_in_battle: bool | None
    conflict_present: bool


def derive_battle_view(context: PerceptionContext) -> BattleView:
    """Active when either labeled battle signal is affirmatively true.

    ``scene_type`` is not an input. A disagreement already recorded by M4 is
    preserved; this function does not drop either source or declare a winner.
    """
    visual_flag: bool | None
    if context.visual is None:
        visual_flag = None
    else:
        visual_flag = context.visual.battle_visible

    structured_flag: bool | None = None
    state = context.game_state
    if state is not None and state.is_in_battle is not None:
        structured_flag = state.is_in_battle

    active = visual_flag is True or structured_flag is True
    conflict = any(item.concept == "battle" for item in context.conflicts)
    return BattleView(
        mode=InteractionMode.BATTLE_ACTIVE if active else InteractionMode.NON_BATTLE,
        visual_battle_visible=visual_flag,
        structured_in_battle=structured_flag,
        conflict_present=conflict,
    )


BATTLE_PROMPT_BLOCK = """INTERACTION_MODE: BATTLE
You are currently in a battle/combat interaction.
Use only the visible/permitted information supplied.
Choose ONE allowlisted action that safely advances or resolves the battle.
Do not invent game-specific controls or mechanics.
If a menu is visible, reason from the visible menu.
If text/dialogue is visible, advance appropriately.
If sources disagree, neither source is silently correct.
If uncertain, choose a bounded safe exploratory action."""


def mode_label(mode: str) -> str:
    """CLI label. ``BATTLE_ACTIVE`` prints as ``BATTLE``."""
    if mode == InteractionMode.BATTLE_ACTIVE.value:
        return "BATTLE"
    if mode == InteractionMode.NON_BATTLE.value:
        return "NON_BATTLE"
    return mode


def mode_transition(previous_mode: str | None, mode: str) -> str:
    """Step-to-step transition. Empty on the first step and when the mode is unchanged."""
    if previous_mode is None or previous_mode == mode:
        return ""
    if mode == InteractionMode.BATTLE_ACTIVE.value:
        return "entry"
    if previous_mode == InteractionMode.BATTLE_ACTIVE.value:
        return "exit"
    return ""
