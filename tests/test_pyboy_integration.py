"""Live PyBoy tests. Skip cleanly when the operator ROM is absent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memnara.config import load_config
from memnara.emulators.pyboy_adapter import PyBoyAdapter
from memnara.rom_identity import inspect_rom

pytestmark = pytest.mark.integration


def _rom_path() -> Path:
    return load_config().rom_path


@pytest.fixture(scope="module")
def rom_file() -> Path:
    path = _rom_path()
    if not path.is_file():
        pytest.skip(f"Operator ROM not present at {path}")
    return path


@pytest.fixture
def data_cfg(tmp_path: Path, rom_file: Path):
    cfg = load_config(rom_path=rom_file, data_root=tmp_path)
    cfg.ensure_runtime_dirs()
    return cfg


def test_pyboy_harness_roundtrip(data_cfg, rom_file: Path) -> None:
    adapter = PyBoyAdapter(window=data_cfg.pyboy_window, sound_emulated=False)
    live = load_config(rom_path=rom_file)
    live.ensure_runtime_dirs()
    try:
        adapter.start(rom_file)
        assert adapter.is_open
        assert adapter.backend_version == "2.7.0"
        assert adapter.native_resolution == (160, 144)
        assert adapter.cartridge_title

        running = adapter.tick(600, render=True)
        assert running is True

        adapter.set_speed(0)
        adapter.tick(1, render=True)
        frame_saved = adapter.capture_frame()
        assert frame_saved.width == 160
        assert frame_saved.height == 144
        assert frame_saved.pixel_format == "RGBA"
        assert len(frame_saved.pixels) == 160 * 144 * 4
        assert frame_saved.source == "pyboy.screen.ndarray"

        state_path = live.states_dir / "m1_roundtrip.state"
        adapter.save_state(state_path)
        assert state_path.is_file()
        assert state_path.stat().st_size > 0

        adapter.press_button("start")
        adapter.tick(90, render=True)
        adapter.press_button("a")
        adapter.tick(90, render=True)
        adapter.hold_button("right")
        adapter.tick(60, render=True)
        adapter.release_button("right")
        adapter.tick(60, render=True)
        frame_changed = adapter.capture_frame()
        assert frame_changed.pixels != frame_saved.pixels, (
            "Framebuffer did not change after save; cannot prove load restored prior state"
        )

        adapter.load_state(state_path)
        frame_restored = adapter.capture_frame()
        assert frame_restored.pixels == frame_saved.pixels
    finally:
        adapter.stop()
        assert adapter.is_open is False


def test_capture_persisted_under_data_root(data_cfg, rom_file: Path) -> None:
    live = load_config(rom_path=rom_file)
    live.ensure_runtime_dirs()
    adapter = PyBoyAdapter(window="null", sound_emulated=False)
    capture_path = live.captures_dir / "m1_proof.png"
    try:
        adapter.start(rom_file)
        adapter.tick(600, render=True)
        frame = adapter.capture_frame()
        try:
            from PIL import Image
        except ImportError:
            raw_path = live.captures_dir / "m1_proof.rgba"
            raw_path.write_bytes(frame.pixels)
            meta = live.captures_dir / "m1_proof.json"
            meta.write_text(
                f'{{"width": {frame.width}, "height": {frame.height}, "format": "{frame.pixel_format}"}}',
                encoding="utf-8",
            )
            assert raw_path.is_file()
            assert frame.width == 160 and frame.height == 144
            return
        image = Image.frombytes("RGBA", (frame.width, frame.height), frame.pixels)
        image.save(capture_path)
        assert capture_path.is_file()
        assert image.size == (160, 144)
    finally:
        adapter.stop()


def test_rom_identity_record(rom_file: Path) -> None:
    identity = inspect_rom(rom_file)
    live = load_config(rom_path=rom_file)
    live.ensure_runtime_dirs()
    out = {
        "path": identity.path,
        "filename": identity.filename,
        "size_bytes": identity.size_bytes,
        "sha1": identity.sha1,
        "sha256": identity.sha256,
        "header_title": identity.header_title,
        "cartridge_type": identity.cartridge_type,
        "header_checksum": identity.header_checksum,
        "header_checksum_valid": identity.header_checksum_valid,
    }
    dest = live.identity_dir / "rom_identity.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    assert dest.is_file()
    assert identity.size_bytes > 0
    assert identity.header_title
    assert identity.header_checksum_valid is True
    assert len(identity.sha1) == 40
    assert len(identity.sha256) == 64
