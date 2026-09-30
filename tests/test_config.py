from pathlib import Path

import pytest

from memnara.config import MemnaraConfig, load_config
from memnara.perception.vision.exceptions import LocalOnlyEndpointError


def test_load_config_env(monkeypatch: object, tmp_path: Path) -> None:
    rom = tmp_path / "game.gb"
    data = tmp_path / "data"
    monkeypatch.setenv("MEMNARA_ROM_PATH", str(rom))
    monkeypatch.setenv("MEMNARA_DATA", str(data))
    monkeypatch.setenv("MEMNARA_PYBOY_WINDOW", "null")
    cfg = load_config()
    assert cfg.rom_path == rom
    assert cfg.data_root == data
    assert cfg.captures_dir == data / "emulator" / "captures"


def test_explicit_overrides_env(monkeypatch: object, tmp_path: Path) -> None:
    monkeypatch.setenv("MEMNARA_ROM_PATH", str(tmp_path / "env.gb"))
    cfg = load_config(rom_path=tmp_path / "arg.gb", data_root=tmp_path / "out")
    assert cfg.rom_path == tmp_path / "arg.gb"
    assert cfg.data_root == tmp_path / "out"


def test_rejects_remote_ollama_host(monkeypatch: object) -> None:
    monkeypatch.setenv("MEMNARA_OLLAMA_HOST", "http://8.8.8.8:11434")
    with pytest.raises(LocalOnlyEndpointError):
        load_config()


def test_ensure_runtime_dirs(tmp_path: Path) -> None:
    cfg = MemnaraConfig(data_root=tmp_path, rom_path=tmp_path / "x.gb")
    cfg.ensure_runtime_dirs()
    assert cfg.captures_dir.is_dir()
    assert cfg.states_dir.is_dir()
    assert cfg.identity_dir.is_dir()
    assert cfg.battery_dir.is_dir()
    assert cfg.vision_dir.is_dir()
    assert cfg.autonomy_dir.is_dir()
