"""Cheap perception-tier and reuse policy. No model calls.

Tiers are an execution concern, like thinking depth. They are not AI identity,
model identity, voice identity, or runtime identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from memnara.agent.movement import is_locomotion
from memnara.agent.thinking import ThinkingProfile, ThinkingSettings
from memnara.perception.vision.models import SceneType, VisualObservation

_UI_SCENES = frozenset(
    {
        SceneType.MENU,
        SceneType.DIALOGUE,
        SceneType.BATTLE,
        SceneType.STATUS_OR_PARTY,
    }
)


class PerceptionTier(str, Enum):
    LIGHT = "light"
    NORMAL = "normal"
    RICH = "rich"


@dataclass(frozen=True)
class PerceptionRequest:
    """Budgets for one vision call. Providers consume numbers, not UI names."""

    tier: PerceptionTier
    description_limit: int
    num_predict: int
    compact_prompt: bool
    include_entities: bool
    light_prompt: bool = False


def ui_locked_visual(visual: VisualObservation | None) -> bool:
    """True when similar reuse would hide menu, dialogue, battle, or on-screen text."""
    if visual is None or not isinstance(visual, VisualObservation):
        return True
    if visual.menu_visible or visual.dialogue_visible or visual.battle_visible:
        return True
    if visual.scene_type in _UI_SCENES:
        return True
    if visual.visible_text:
        return True
    return False


def similar_reuse_allowed(
    *,
    reuse_policy: str,
    visual: VisualObservation | None,
    stable: bool,
    meaningfully_changed: bool,
) -> bool:
    """Idle-animation reuse. Exact digest matching is decided by the caller."""
    from memnara.agent.thinking import REUSE_SIMILAR

    return (
        reuse_policy == REUSE_SIMILAR
        and stable
        and visual is not None
        and not ui_locked_visual(visual)
        and not meaningfully_changed
    )


def select_perception_tier(
    *,
    stuck_state: str,
    saw_transition: bool,
    prior_visual: VisualObservation | None,
    meaningfully_changed: bool,
    prefer_light: bool,
) -> PerceptionTier:
    """Pick a vision depth from signals the loop already has. No extra model call."""
    if stuck_state and stuck_state != "NORMAL":
        return PerceptionTier.RICH
    if saw_transition:
        return PerceptionTier.NORMAL
    if ui_locked_visual(prior_visual) and prior_visual is not None:
        return PerceptionTier.NORMAL
    if prior_visual is None:
        return PerceptionTier.LIGHT if prefer_light else PerceptionTier.NORMAL
    if meaningfully_changed:
        return PerceptionTier.NORMAL
    return PerceptionTier.LIGHT


def vision_request_for(settings: ThinkingSettings, tier: PerceptionTier) -> PerceptionRequest:
    """Map a tier onto provider budgets. DELIBERATE does not stay on LIGHT."""
    effective = tier
    if settings.profile is ThinkingProfile.DELIBERATE and tier is PerceptionTier.LIGHT:
        effective = PerceptionTier.NORMAL
    include_entities = effective is PerceptionTier.RICH
    compact = settings.vision_compact_prompt or effective is PerceptionTier.LIGHT
    description_limit = settings.vision_description_limit
    num_predict = settings.vision_num_predict
    if effective is PerceptionTier.LIGHT:
        description_limit = min(description_limit, 120)
        num_predict = min(num_predict, 128)
        compact = True
    elif effective is PerceptionTier.RICH:
        description_limit = max(description_limit, settings.vision_description_limit)
        num_predict = max(num_predict, settings.vision_num_predict)
        compact = False if settings.profile is ThinkingProfile.DELIBERATE else compact
    return PerceptionRequest(
        tier=effective,
        description_limit=description_limit,
        num_predict=num_predict,
        compact_prompt=compact,
        include_entities=include_entities,
        light_prompt=effective is PerceptionTier.LIGHT,
    )


def can_skip_post_semantic_vision(
    *,
    action: str | None,
    stuck_state: str,
    saw_transition: bool,
    stable: bool,
    digest_identical: bool,
    meaningfully_changed: bool,
    prior_visual: VisualObservation | None,
) -> bool:
    """Whether post-action outcomes can use pixels/flags already in hand.

    Identical frames never need a second VLM. Locomotion and WAIT may defer a
    semantic reread until the next decision when the prior reading was not UI.
    A changed PRESS_* frame still needs vision so Patch #4 can see ADVANCED.
    """
    if not stable or saw_transition:
        return False
    if stuck_state and stuck_state != "NORMAL":
        return False
    if prior_visual is None:
        return False
    if digest_identical:
        return True
    if ui_locked_visual(prior_visual):
        return False
    if action and is_locomotion(action):
        return True
    if action == "WAIT" and not meaningfully_changed:
        return True
    return False
