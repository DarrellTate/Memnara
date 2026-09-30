"""Parse model JSON into VisualObservation. Stamp VISUAL. Reject action payloads."""

from __future__ import annotations

import json
import math
from typing import Any

from memnara.perception.vision.exceptions import VisionParseError
from memnara.perception.vision.models import SceneType, VisualEntity, VisualObservation

ACTION_KEYS = frozenset(
    {
        "press_button",
        "hold_button",
        "release_button",
        "navigate",
        "use_move",
        "action",
        "actions",
        "button",
    }
)


def parse_observation(
    raw_text: str,
    *,
    model: str,
    scale: int,
    image_width: int,
    image_height: int,
    latency_ms: float | None = None,
    eval_count: int | None = None,
) -> VisualObservation:
    if not raw_text or not raw_text.strip():
        raise VisionParseError("empty model content")
    try:
        payload = json.loads(raw_text, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise VisionParseError(f"model content is not JSON: {exc}") from exc
    except ValueError as exc:
        raise VisionParseError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise VisionParseError("model JSON must be an object")
    leaked = ACTION_KEYS.intersection(payload)
    if leaked:
        payload = {key: value for key, value in payload.items() if key not in ACTION_KEYS}
    return _from_dict(
        payload,
        model=model,
        scale=scale,
        image_width=image_width,
        image_height=image_height,
        latency_ms=latency_ms,
        eval_count=eval_count,
        notes=f"ignored_action_keys={sorted(leaked)}" if leaked else "",
    )


def _from_dict(
    payload: dict[str, Any],
    *,
    model: str,
    scale: int,
    image_width: int,
    image_height: int,
    latency_ms: float | None,
    eval_count: int | None,
    notes: str,
) -> VisualObservation:
    scene_raw = str(payload.get("scene_type") or "UNKNOWN")
    try:
        scene = SceneType(scene_raw)
    except ValueError:
        scene = SceneType.UNKNOWN
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        raise VisionParseError("description is required")
    visible = payload.get("visible_text") or []
    if not isinstance(visible, list) or not all(isinstance(item, str) for item in visible):
        raise VisionParseError("visible_text must be an array of strings")
    entities_raw = payload.get("entities") or []
    if not isinstance(entities_raw, list):
        raise VisionParseError("entities must be an array")
    entities: list[VisualEntity] = []
    for item in entities_raw:
        if not isinstance(item, dict) or not item.get("name"):
            raise VisionParseError("each entity needs a name")
        entities.append(
            VisualEntity(
                name=str(item["name"]),
                kind=str(item.get("kind") or ""),
                notes=str(item.get("notes") or ""),
            )
        )
    for flag in ("menu_visible", "dialogue_visible", "battle_visible"):
        if not isinstance(payload.get(flag), bool):
            raise VisionParseError(f"{flag} must be a boolean")
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise VisionParseError("confidence must be a number")
    confidence_f = float(confidence)
    if not math.isfinite(confidence_f):
        raise VisionParseError("confidence must be a finite number")
    extra_notes = notes
    if confidence_f < 0 or confidence_f > 1:
        extra_notes = (
            f"{notes}; confidence_clamped_from={confidence_f}" if notes else f"confidence_clamped_from={confidence_f}"
        )
        confidence_f = 0.0 if confidence_f < 0 else 1.0
    notable = payload.get("notable_changes")
    if notable is None:
        notable = ""
    if not isinstance(notable, str):
        raise VisionParseError("notable_changes must be a string")
    return VisualObservation(
        scene_type=scene,
        description=description.strip(),
        visible_text=tuple(visible),
        entities=tuple(entities),
        menu_visible=bool(payload["menu_visible"]),
        dialogue_visible=bool(payload["dialogue_visible"]),
        battle_visible=bool(payload["battle_visible"]),
        confidence=confidence_f,
        notable_changes=notable,
        source="VISUAL",
        model=model,
        scale=scale,
        image_width=image_width,
        image_height=image_height,
        latency_ms=latency_ms,
        eval_count=eval_count,
        notes=extra_notes,
    )


def _reject_json_constant(name: str) -> None:
    raise ValueError(f"non-standard JSON constant: {name}")
