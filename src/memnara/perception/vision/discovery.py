"""Installed Ollama models vs Memnara-compatible vision models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from memnara.perception.vision.exceptions import ModelUnavailableError, OllamaUnavailableError

HttpGet = Callable[[str], dict[str, Any]]
HttpPost = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class InstalledModel:
    name: str
    installed: bool
    vision_capable: bool
    thinking: bool
    capabilities: tuple[str, ...]
    family: str = ""


def list_installed_names(payload: dict[str, Any]) -> tuple[str, ...]:
    models = payload.get("models") or []
    names: list[str] = []
    for item in models:
        name = item.get("name") if isinstance(item, dict) else None
        if name:
            names.append(str(name))
    return tuple(names)


def parse_show(name: str, payload: dict[str, Any]) -> InstalledModel:
    caps_raw = payload.get("capabilities") or []
    caps = tuple(str(item) for item in caps_raw)
    details = payload.get("details") or {}
    family = str(details.get("family") or "")
    return InstalledModel(
        name=name,
        installed=True,
        vision_capable="vision" in caps,
        thinking="thinking" in caps,
        capabilities=caps,
        family=family,
    )


def is_memnara_vision_model(info: InstalledModel) -> bool:
    return info.installed and info.vision_capable


def require_vision_model(
    name: str,
    *,
    get_json: HttpGet,
    post_json: HttpPost,
) -> InstalledModel:
    try:
        tags = get_json("/api/tags")
    except OSError as exc:
        raise OllamaUnavailableError(f"Ollama tags query failed: {exc}") from exc
    names = list_installed_names(tags)
    if name not in names:
        raise ModelUnavailableError(f"Model {name!r} is not installed on the local Ollama server")
    try:
        shown = post_json("/api/show", {"name": name})
    except OSError as exc:
        raise OllamaUnavailableError(f"Ollama show query failed: {exc}") from exc
    info = parse_show(name, shown)
    if not is_memnara_vision_model(info):
        raise ModelUnavailableError(
            f"Model {name!r} is installed but not Memnara-compatible vision "
            f"(capabilities={info.capabilities})"
        )
    return info
