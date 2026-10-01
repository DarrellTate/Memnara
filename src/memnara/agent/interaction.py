"""Generic outcome of a non-movement gameplay action.

Button names are not given meanings here. The outcome is whatever the next
observation shows. Locomotion stays in MovementOutcome.
"""

from __future__ import annotations

from enum import Enum

from memnara.agent.movement import is_locomotion
from memnara.agent.observe import ObservedState


class InteractionOutcome(str, Enum):
    ADVANCED = "ADVANCED"
    CHANGED = "CHANGED"
    NO_EFFECT = "NO_EFFECT"
    UNCERTAIN = "UNCERTAIN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def interaction_signature(state: ObservedState) -> tuple:
    """Flags, on-screen text, and structured token. Free-form wording is excluded."""
    visual = state.context.visual
    if visual is None:
        flags = (False, False, False, ())
    else:
        flags = (
            bool(visual.menu_visible),
            bool(visual.dialogue_visible),
            bool(visual.battle_visible),
            tuple(visual.visible_text),
        )
    return (flags, state.progress_token or "")


def classify_interaction(
    *,
    action: str | None,
    executed: bool,
    before: ObservedState,
    after: ObservedState,
    transient: bool,
) -> InteractionOutcome:
    """Classify one non-movement attempt from observations the loop already has.

    A transient frame is UNCERTAIN: a fade is not evidence the button did nothing
    and not evidence it advanced the interaction. MOVE_* is NOT_APPLICABLE.
    """
    if not executed or not action or is_locomotion(action):
        return InteractionOutcome.NOT_APPLICABLE
    if transient:
        return InteractionOutcome.UNCERTAIN
    if interaction_signature(before) != interaction_signature(after):
        return InteractionOutcome.ADVANCED
    if before.screen_digest and before.screen_digest == after.screen_digest:
        return InteractionOutcome.NO_EFFECT
    if before.screen_digest != after.screen_digest:
        return InteractionOutcome.CHANGED
    return InteractionOutcome.UNCERTAIN
