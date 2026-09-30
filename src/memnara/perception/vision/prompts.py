"""Controlled vision prompt. No RAM hints. No gameplay actions."""

from __future__ import annotations

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
"""

USER_PROMPT = (
    "Observe this game screenshot. Extract visible text only if you can read it. "
    "If text is unreadable, leave visible_text empty rather than inventing words."
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
