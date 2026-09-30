"""Live vision against operator ROM + local Ollama. Skip if either is missing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memnara.config import load_config
from memnara.emulators.pyboy_adapter import PyBoyAdapter
from memnara.perception.vision.change import FrameChangeDetector
from memnara.perception.vision.exceptions import ModelUnavailableError, OllamaUnavailableError
from memnara.perception.vision.images import encode_framebuffer_png
from memnara.perception.vision.ollama import OllamaVisionProvider

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def rom_file() -> Path:
    path = load_config().rom_path
    if not path.is_file():
        pytest.skip(f"Operator ROM not present at {path}")
    return path


def test_live_vision_scenes(rom_file: Path) -> None:
    cfg = load_config(rom_path=rom_file)
    cfg.ensure_runtime_dirs()
    provider = OllamaVisionProvider(
        endpoint=cfg.ollama_host,
        model=cfg.vision_model,
        scale=cfg.vision_scale,
        timeout_s=cfg.vision_timeout_s,
        think=False,
    )
    try:
        provider.ensure_model()
    except (OllamaUnavailableError, ModelUnavailableError) as exc:
        pytest.skip(str(exc))

    adapter = PyBoyAdapter(window="null", sound_emulated=False)
    gate = FrameChangeDetector(threshold=cfg.vision_change_threshold)
    evidence: dict = {
        "model": cfg.vision_model,
        "endpoint": cfg.ollama_host,
        "scale": cfg.vision_scale,
        "think": False,
        "samples": [],
        "change_gate": {},
    }
    try:
        adapter.start(rom_file)
        adapter.tick(600, render=True)
        boot = adapter.capture_frame()
        boot_png, _, _ = encode_framebuffer_png(boot, scale=1)
        (cfg.vision_dir / "m3_boot.png").write_bytes(boot_png)

        adapter.tick(900, render=True)
        title = adapter.capture_frame()
        (cfg.vision_dir / "m3_title.png").write_bytes(encode_framebuffer_png(title, scale=1)[0])

        for _ in range(400):
            adapter.press_button("a", delay_frames=1)
            adapter.tick(8, render=True)
        overworld = adapter.capture_frame()
        (cfg.vision_dir / "m3_overworld.png").write_bytes(encode_framebuffer_png(overworld, scale=1)[0])

        adapter.press_button("start", delay_frames=1)
        adapter.tick(90, render=True)
        menu = adapter.capture_frame()
        (cfg.vision_dir / "m3_menu.png").write_bytes(encode_framebuffer_png(menu, scale=1)[0])

        scenes = (
            ("boot_or_title_early", boot, "Boot logos or copyright screen if present"),
            ("title_or_intro", title, "Title or continuing intro; no RAM hints"),
            ("overworld_after_intro", overworld, "Indoor overworld after new-game mash; furniture/player if visible"),
            ("start_menu_attempt", menu, "Start menu overlay if START opened it"),
        )
        latencies: list[float] = []
        for name, frame, expected in scenes:
            obs = provider.observe(frame)
            latency = obs.latency_ms or 0.0
            latencies.append(latency)
            evidence["samples"].append(
                {
                    "scene": name,
                    "expected_visible": expected,
                    "scene_type": obs.scene_type.value,
                    "description": obs.description,
                    "visible_text": list(obs.visible_text),
                    "entities": [
                        {"name": ent.name, "kind": ent.kind, "notes": ent.notes} for ent in obs.entities
                    ],
                    "menu_visible": obs.menu_visible,
                    "dialogue_visible": obs.dialogue_visible,
                    "battle_visible": obs.battle_visible,
                    "confidence": obs.confidence,
                    "source": obs.source,
                    "model": obs.model,
                    "scale": obs.scale,
                    "image_size": [obs.image_width, obs.image_height],
                    "latency_ms": obs.latency_ms,
                    "eval_count": obs.eval_count,
                    "notes": obs.notes,
                    "quality": "SEE_DOCS",
                }
            )
            assert obs.source == "VISUAL"
            assert obs.model == cfg.vision_model
            assert isinstance(obs.description, str) and obs.description
            assert 0.0 <= obs.confidence <= 1.0

        assert gate.should_observe(overworld) is True
        assert gate.should_observe(overworld) is False
        evidence["change_gate"] = {
            "identical_overworld_suppressed": True,
            "threshold": cfg.vision_change_threshold,
        }
        evidence["latency_ms"] = {
            "first_call_coldish": latencies[0] if latencies else None,
            "warm_calls": latencies[1:],
            "mean": sum(latencies) / len(latencies) if latencies else None,
        }
        log_path = cfg.vision_dir / "m3_live_vision.json"
        log_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        assert log_path.is_file()
    finally:
        adapter.stop()
