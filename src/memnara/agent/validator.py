"""Validate one structured action proposal. Never treats prose as a command."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from memnara.agent.actions import ActionProposal, ActionRegistry
from memnara.agent.exceptions import InvalidActionError, MalformedProposalError

FORBIDDEN_KEYS = frozenset(
    {
        "shell",
        "code",
        "python",
        "command",
        "commands",
        "script",
        "ram_write",
        "write_ram",
        "execute",
        "eval",
    }
)
ALLOWED_MODEL_KEYS = frozenset({"action", "parameters", "reason", "confidence"})
_ACTION_RE = re.compile(r"[^A-Z0-9_]+")


def normalize_action_name(raw: str) -> str:
    text = str(raw).strip().replace("-", "_").replace(" ", "_").upper()
    return _ACTION_RE.sub("", text)


class ActionValidator:
    def __init__(self, registry: ActionRegistry) -> None:
        self.registry = registry

    def parse_and_validate(self, raw: str | dict[str, Any]) -> ActionProposal:
        payload = _coerce_object(raw)
        leaked = FORBIDDEN_KEYS.intersection(payload)
        if leaked:
            raise InvalidActionError(f"proposal contains forbidden keys: {sorted(leaked)}")
        extra = set(payload) - ALLOWED_MODEL_KEYS
        if extra:
            raise MalformedProposalError(f"unknown proposal fields: {sorted(extra)}")
        action_raw = payload.get("action")
        if isinstance(action_raw, list):
            raise MalformedProposalError("action must be a single name, not a list")
        if not isinstance(action_raw, str) or not action_raw.strip():
            raise MalformedProposalError("action is required")
        action = normalize_action_name(action_raw)
        if not action:
            raise MalformedProposalError("action is empty after normalization")
        if not self.registry.contains(action):
            raise InvalidActionError(f"unknown or unsupported action: {action_raw!r}")
        parameters = payload.get("parameters")
        if parameters is None:
            parameters = {}
        if not isinstance(parameters, dict):
            raise InvalidActionError("parameters must be an object")
        cleaned = _validate_parameters(action, parameters)
        reason = payload.get("reason")
        if reason is None:
            reason = ""
        if not isinstance(reason, str):
            raise MalformedProposalError("reason must be a string")
        confidence = payload.get("confidence")
        if confidence is None:
            conf_value: float | None = None
        elif isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise MalformedProposalError("confidence must be a number")
        else:
            conf_value = float(confidence)
            if not math.isfinite(conf_value):
                raise MalformedProposalError("confidence must be a finite number")
            if conf_value < 0.0 or conf_value > 1.0:
                raise MalformedProposalError("confidence must be between 0 and 1")
        return ActionProposal(
            action=action,
            parameters=cleaned,
            reason=reason.strip()[:500],
            confidence=conf_value,
            metadata={},
        )


def extract_json_object_text(raw: str) -> str:
    """Use a JSON object in model text; discard any surrounding non-JSON prefix/suffix."""
    stripped = raw.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        return stripped
    return stripped[start : end + 1]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate JSON key: {key}")
        seen.add(key)
        out[key] = value
    return out


def _reject_json_constant(name: str) -> None:
    raise ValueError(f"non-standard JSON constant: {name}")


def _loads_strict_object(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            extract_json_object_text(raw),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise MalformedProposalError(f"model content is not JSON: {exc}") from exc
    except ValueError as exc:
        raise MalformedProposalError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise MalformedProposalError("model JSON must be an object")
    return payload


def _coerce_object(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise MalformedProposalError("empty model content")
    return _loads_strict_object(raw)


def _validate_parameters(action: str, parameters: dict[str, Any]) -> dict[str, object]:
    if action == "WAIT":
        extra = set(parameters) - {"frames"}
        if extra:
            raise InvalidActionError(f"WAIT rejects parameters {sorted(extra)}")
        if "frames" not in parameters:
            return {}
        frames = parameters["frames"]
        if isinstance(frames, bool) or not isinstance(frames, int):
            raise InvalidActionError("WAIT frames must be an integer")
        if frames < 1 or frames > 180:
            raise InvalidActionError("WAIT frames must be between 1 and 180")
        return {"frames": frames}
    if parameters:
        raise InvalidActionError(f"{action} does not accept parameters")
    return {}
