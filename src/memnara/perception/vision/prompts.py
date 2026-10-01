"""Controlled vision prompt. No RAM hints. No gameplay actions."""

from __future__ import annotations

import copy

from memnara.perception.vision.models import SceneType

SCENE_VALUES = [item.value for item in SceneType]

SYSTEM_PROMPT = """You are a visual observer for a video-game screenshot.

Rules:
- Describe only what is visible in the image.
- Do not invent hidden game state.
- Do not use RAM, memory maps, coordinates, party counts, or other non-visual knowledge.
- Do not infer unseen events.
- If you are unsure, say so and use scene_type UNKNOWN rather than guessing.
- This is a game screenshot. Do not take actions.
- Do not suggest buttons, moves, navigation, or what the player should do.
- Your output is VISUAL observation only, never RAM.

Return JSON matching the provided schema.
Keep description to a short actionable sentence unless the caller asks for richer detail.
Do not catalogue repeated tiles, scenery, or decorative objects.
"""

COMPACT_SYSTEM_PROMPT = """You are a visual observer for a video-game screenshot.
Describe only what is visible. No RAM, no actions, no invented hidden state.
If unsure, scene_type UNKNOWN. JSON only.
description: one short actionable sentence for navigation/UI, not a scenery catalogue.
visible_text only if readable, else empty.
"""

LIGHT_SYSTEM_PROMPT = """Visual observer. Visible facts only. No RAM. No actions.
JSON fields: scene_type, menu_visible, dialogue_visible, battle_visible, visible_text, notable_changes, description, confidence.
description: one short sentence such as "Character in traversable area; obstacle visible right."
Do not list tiles, furniture, or background objects.
"""

USER_PROMPT = (
    "Observe this game screenshot. Extract visible text only if you can read it. "
    "If text is unreadable, leave visible_text empty rather than inventing words. "
    "Keep description short and actionable."
)

COMPACT_USER_PROMPT = (
    "JSON only. Short actionable description, not a tile catalog. "
    "visible_text only if readable, else empty. notable_changes empty if none. No actions."
)

LIGHT_USER_PROMPT = (
    "JSON only. One-line description. Flags and readable text only. No scenery list."
)


OBSERVATION_FORMAT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scene_type": {"type": "string", "enum": SCENE_VALUES},
        "description": {"type": "string"},
        "visible_text": {"type": "array", "items": {"type": "string"}},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "menu_visible": {"type": "boolean"},
        "dialogue_visible": {"type": "boolean"},
        "battle_visible": {"type": "boolean"},
        "confidence": {"type": "number"},
        "notable_changes": {"type": "string"},
    },
    "required": [
        "scene_type",
        "description",
        "menu_visible",
        "dialogue_visible",
        "battle_visible",
        "confidence",
    ],
}

_LIGHT_PROPERTIES = (
    "scene_type",
    "description",
    "visible_text",
    "menu_visible",
    "dialogue_visible",
    "battle_visible",
    "confidence",
    "notable_changes",
)


def observation_format_for(
    *,
    include_entities: bool = True,
    description_limit: int | None = None,
) -> dict:
    """Schema for one vision call. LIGHT omits entities so the model does not list scenery."""
    payload = copy.deepcopy(OBSERVATION_FORMAT)
    if not include_entities:
        properties = {key: payload["properties"][key] for key in _LIGHT_PROPERTIES}
        payload["properties"] = properties
    if description_limit is not None:
        payload["properties"]["description"]["maxLength"] = int(description_limit)
    return payload


def system_prompt_for(*, compact: bool, light: bool = False) -> str:
    if light:
        return LIGHT_SYSTEM_PROMPT
    if compact:
        return COMPACT_SYSTEM_PROMPT
    return SYSTEM_PROMPT


def user_prompt_for(*, compact: bool, light: bool = False) -> str:
    if light:
        return LIGHT_USER_PROMPT
    if compact:
        return COMPACT_USER_PROMPT
    return USER_PROMPT
