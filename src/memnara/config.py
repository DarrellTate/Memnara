"""Milestone 1–5 configuration. ROM path is not hard-coded in the adapter.

Canonical defaults are D:\\Memnara-Data and D:\\Memnara_Roms.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from urllib.parse import urlparse

from memnara.perception.vision.exceptions import LocalOnlyEndpointError
from memnara.perception.vision.images import DEFAULT_SCALE
from memnara.perception.vision.ollama import DEFAULT_ENDPOINT, DEFAULT_MODEL, assert_local_endpoint

DEFAULT_DATA_ROOT = Path(r"D:\Memnara-Data")
DEFAULT_ROM_PATH = Path(r"D:\Memnara_Roms\reference.gb")
DEFAULT_VISION_TIMEOUT_S = 120.0
DEFAULT_CHANGE_THRESHOLD = 0.015
BIND_ALL_HOSTS = frozenset({"0.0.0.0", "::", "*"})


@dataclass(frozen=True)
class MemnaraConfig:
    data_root: Path
    rom_path: Path
    pyboy_window: str = "null"
    ollama_host: str = DEFAULT_ENDPOINT
    vision_model: str = DEFAULT_MODEL
    vision_scale: int = DEFAULT_SCALE
    vision_timeout_s: float = DEFAULT_VISION_TIMEOUT_S
    vision_change_threshold: float = DEFAULT_CHANGE_THRESHOLD
    reasoning_timeout_s: float = DEFAULT_VISION_TIMEOUT_S

    @property
    def emulator_root(self) -> Path:
        return self.data_root / "emulator"

    @property
    def captures_dir(self) -> Path:
        return self.emulator_root / "captures"

    @property
    def states_dir(self) -> Path:
        return self.emulator_root / "states"

    @property
    def identity_dir(self) -> Path:
        return self.emulator_root / "identity"

    @property
    def battery_dir(self) -> Path:
        return self.emulator_root / "battery"

    @property
    def perception_dir(self) -> Path:
        return self.data_root / "perception"

    @property
    def vision_dir(self) -> Path:
        return self.perception_dir / "vision"

    @property
    def autonomy_dir(self) -> Path:
        return self.data_root / "autonomy"

    def ensure_runtime_dirs(self) -> None:
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.states_dir.mkdir(parents=True, exist_ok=True)
        self.identity_dir.mkdir(parents=True, exist_ok=True)
        self.battery_dir.mkdir(parents=True, exist_ok=True)
        self.vision_dir.mkdir(parents=True, exist_ok=True)
        self.autonomy_dir.mkdir(parents=True, exist_ok=True)


def load_config(
    *,
    rom_path: str | Path | None = None,
    data_root: str | Path | None = None,
    pyboy_window: str | None = None,
    ollama_host: str | None = None,
    vision_model: str | None = None,
    vision_scale: int | None = None,
) -> MemnaraConfig:
    resolved_rom = Path(
        rom_path
        or os.environ.get("MEMNARA_ROM_PATH")
        or DEFAULT_ROM_PATH
    )
    resolved_data = Path(
        data_root
        or os.environ.get("MEMNARA_DATA")
        or DEFAULT_DATA_ROOT
    )
    window = pyboy_window or os.environ.get("MEMNARA_PYBOY_WINDOW") or "null"
    host = _resolve_ollama_host(ollama_host)
    model = vision_model or os.environ.get("MEMNARA_MODEL") or DEFAULT_MODEL
    scale_raw = vision_scale if vision_scale is not None else os.environ.get("MEMNARA_VISION_SCALE")
    scale = DEFAULT_SCALE if scale_raw is None else int(scale_raw)
    return MemnaraConfig(
        data_root=resolved_data,
        rom_path=resolved_rom,
        pyboy_window=window,
        ollama_host=host,
        vision_model=model,
        vision_scale=scale,
    )


def _normalize_endpoint(value: str) -> str:
    text = value.strip()
    if "://" not in text:
        text = "http://" + text
    return text


def _resolve_ollama_host(explicit: str | None) -> str:
    if explicit:
        return assert_local_endpoint(_normalize_endpoint(explicit))
    memnara_host = os.environ.get("MEMNARA_OLLAMA_HOST")
    if memnara_host:
        return assert_local_endpoint(_normalize_endpoint(memnara_host))
    ollama = os.environ.get("OLLAMA_HOST")
    if ollama:
        text = _normalize_endpoint(ollama)
        host = (urlparse(text).hostname or "").lower()
        if host not in BIND_ALL_HOSTS:
            try:
                return assert_local_endpoint(text)
            except LocalOnlyEndpointError:
                pass
    return DEFAULT_ENDPOINT
