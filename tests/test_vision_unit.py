from __future__ import annotations

import json

import pytest

from memnara.emulators.base import Framebuffer
from memnara.perception.vision.change import FrameChangeDetector, changed_pixel_ratio
from memnara.perception.vision.discovery import is_memnara_vision_model, parse_show, require_vision_model
from memnara.perception.vision.exceptions import (
    LocalOnlyEndpointError,
    ModelUnavailableError,
    OllamaUnavailableError,
    VisionError,
    VisionParseError,
    VisionTimeoutError,
)
from memnara.perception.vision.images import encode_framebuffer_png
from memnara.perception.vision.models import SceneType
from memnara.perception.vision.ollama import OllamaVisionProvider, assert_local_endpoint
from memnara.perception.vision.parse import parse_observation


def _rgba_frame(width: int, height: int, color: tuple[int, int, int, int] = (10, 20, 30, 255)) -> Framebuffer:
    pixel = bytes(color)
    return Framebuffer(
        width=width,
        height=height,
        pixel_format="RGBA",
        pixels=pixel * (width * height),
        source="test",
    )


def test_encode_and_integer_scale() -> None:
    frame = _rgba_frame(8, 8)
    png, width, height = encode_framebuffer_png(frame, scale=3)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert width == 24
    assert height == 24
    from PIL import Image
    import io

    image = Image.open(io.BytesIO(png))
    assert image.size == (24, 24)
    assert image.getpixel((0, 0))[:3] == (10, 20, 30)


def test_reject_bad_scale() -> None:
    with pytest.raises(VisionError):
        encode_framebuffer_png(_rgba_frame(2, 2), scale=5)


def test_parse_stamps_visual_and_ignores_actions() -> None:
    raw = json.dumps(
        {
            "scene_type": "OVERWORLD",
            "description": "A bedroom interior.",
            "visible_text": ["START"],
            "entities": [{"name": "player", "kind": "character"}],
            "menu_visible": False,
            "dialogue_visible": False,
            "battle_visible": False,
            "confidence": 0.7,
            "notable_changes": "",
            "press_button": "a",
            "source": "RAM",
        }
    )
    obs = parse_observation(raw, model="qwen3-vl:8b", scale=3, image_width=480, image_height=432)
    assert obs.source == "VISUAL"
    assert obs.scene_type == SceneType.OVERWORLD
    assert obs.visible_text == ("START",)
    assert obs.entities[0].name == "player"
    assert obs.model == "qwen3-vl:8b"
    assert "press_button" in obs.notes
    assert obs.menu_visible is False


def test_parse_unknown_scene_and_malformed() -> None:
    raw = json.dumps(
        {
            "scene_type": "CUTSCENE",
            "description": "unclear",
            "menu_visible": False,
            "dialogue_visible": False,
            "battle_visible": False,
            "confidence": 0.2,
        }
    )
    obs = parse_observation(raw, model="x", scale=2, image_width=1, image_height=1)
    assert obs.scene_type == SceneType.UNKNOWN
    high = json.loads(raw)
    high["confidence"] = 1.4
    clamped = parse_observation(json.dumps(high), model="x", scale=2, image_width=1, image_height=1)
    assert clamped.confidence == 1.0
    assert "confidence_clamped_from=1.4" in clamped.notes
    low = json.loads(raw)
    low["confidence"] = -0.4
    clamped_low = parse_observation(json.dumps(low), model="x", scale=2, image_width=1, image_height=1)
    assert clamped_low.confidence == 0.0
    assert "confidence_clamped_from=-0.4" in clamped_low.notes
    nan_raw = json.dumps(low).replace("-0.4", "NaN")
    with pytest.raises(VisionParseError):
        parse_observation(nan_raw, model="x", scale=2, image_width=1, image_height=1)
    inf_raw = json.dumps(low).replace("-0.4", "Infinity")
    with pytest.raises(VisionParseError):
        parse_observation(inf_raw, model="x", scale=2, image_width=1, image_height=1)
    ninf_raw = json.dumps(low).replace("-0.4", "-Infinity")
    with pytest.raises(VisionParseError):
        parse_observation(ninf_raw, model="x", scale=2, image_width=1, image_height=1)
    as_string = json.loads(raw)
    as_string["confidence"] = "0.8"
    with pytest.raises(VisionParseError):
        parse_observation(json.dumps(as_string), model="x", scale=2, image_width=1, image_height=1)
    with pytest.raises(VisionParseError):
        parse_observation("not-json", model="x", scale=1, image_width=1, image_height=1)
    with pytest.raises(VisionParseError):
        parse_observation("{}", model="x", scale=1, image_width=1, image_height=1)


def test_frame_change_suppresses_identical() -> None:
    a = _rgba_frame(4, 4, (1, 2, 3, 255))
    b = _rgba_frame(4, 4, (1, 2, 3, 255))
    c = _rgba_frame(4, 4, (9, 9, 9, 255))
    gate = FrameChangeDetector(threshold=0.01)
    assert gate.should_observe(a) is True
    assert gate.should_observe(b) is False
    assert gate.should_observe(c) is True
    assert changed_pixel_ratio(a.pixels, b.pixels, width=4, height=4) == 0.0
    assert changed_pixel_ratio(a.pixels, c.pixels, width=4, height=4) == 1.0


def test_local_endpoint_enforced() -> None:
    assert assert_local_endpoint("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    with pytest.raises(LocalOnlyEndpointError):
        assert_local_endpoint("http://example.com:11434")
    with pytest.raises(LocalOnlyEndpointError):
        OllamaVisionProvider(endpoint="https://api.openai.com")


def test_discovery_requires_vision_capability() -> None:
    tags = {"models": [{"name": "qwen3-vl:8b"}, {"name": "plain:latest"}]}
    show_ok = {"capabilities": ["completion", "vision", "thinking"], "details": {"family": "qwen3vl"}}
    info = require_vision_model(
        "qwen3-vl:8b",
        get_json=lambda path: tags,
        post_json=lambda path, body: show_ok,
    )
    assert is_memnara_vision_model(info) is True
    with pytest.raises(ModelUnavailableError):
        require_vision_model(
            "missing",
            get_json=lambda path: tags,
            post_json=lambda path, body: show_ok,
        )
    with pytest.raises(ModelUnavailableError):
        require_vision_model(
            "plain:latest",
            get_json=lambda path: tags,
            post_json=lambda path, body: {"capabilities": ["completion"]},
        )


def test_provider_observe_mocked() -> None:
    frame = _rgba_frame(2, 2)
    content = json.dumps(
        {
            "scene_type": "MENU",
            "description": "A menu is visible.",
            "visible_text": ["POKeDEX"],
            "entities": [],
            "menu_visible": True,
            "dialogue_visible": False,
            "battle_visible": False,
            "confidence": 0.8,
            "notable_changes": "",
        }
    )
    provider = OllamaVisionProvider(
        http_get=lambda path: {"models": [{"name": "qwen3-vl:8b"}]},
        http_post=lambda path, body: (
            {"capabilities": ["vision"]}
            if path == "/api/show"
            else {"message": {"content": content}, "eval_count": 12}
        ),
    )
    obs = provider.observe(frame)
    assert obs.source == "VISUAL"
    assert obs.scene_type == SceneType.MENU
    assert obs.menu_visible is True
    assert obs.eval_count == 12
    assert obs.scale == 3
    assert obs.image_width == 6
    assert obs.latency_ms is not None


def test_provider_uses_thinking_when_content_empty() -> None:
    frame = _rgba_frame(2, 2)
    content = json.dumps(
        {
            "scene_type": "BOOT_OR_TITLE",
            "description": "Boot logo on a title screen.",
            "menu_visible": False,
            "dialogue_visible": False,
            "battle_visible": False,
            "confidence": 0.9,
        }
    )
    provider = OllamaVisionProvider(
        http_get=lambda path: {"models": [{"name": "qwen3-vl:8b"}]},
        http_post=lambda path, body: (
            {"capabilities": ["vision"]}
            if path == "/api/show"
            else {"message": {"content": "", "thinking": content}, "eval_count": 40}
        ),
    )
    obs = provider.observe(frame)
    assert obs.scene_type.value == "BOOT_OR_TITLE"
    assert "thinking" in obs.notes


def _provider_with_chat(http_post_chat):
    def http_post(path, body):
        if path == "/api/show":
            return {"capabilities": ["vision"]}
        return http_post_chat(path, body)

    return OllamaVisionProvider(
        http_get=lambda path: {"models": [{"name": "qwen3-vl:8b"}]},
        http_post=http_post,
    )


def test_provider_chat_timeout() -> None:
    def http_post_chat(path, body):
        raise TimeoutError("chat timed out")

    provider = _provider_with_chat(http_post_chat)
    with pytest.raises(VisionTimeoutError):
        provider.observe(_rgba_frame(2, 2))


def test_provider_chat_unavailable() -> None:
    def http_post_chat(path, body):
        raise OSError("connection refused")

    provider = _provider_with_chat(http_post_chat)
    with pytest.raises(OllamaUnavailableError):
        provider.observe(_rgba_frame(2, 2))


def test_provider_empty_content_and_thinking() -> None:
    provider = _provider_with_chat(
        lambda path, body: {"message": {"content": "", "thinking": ""}}
    )
    with pytest.raises(VisionParseError):
        provider.observe(_rgba_frame(2, 2))
    provider_missing = _provider_with_chat(lambda path, body: {"message": {}})
    with pytest.raises(VisionParseError):
        provider_missing.observe(_rgba_frame(2, 2))


def test_provider_malformed_structured_content() -> None:
    provider = _provider_with_chat(lambda path, body: {"message": {"content": "not-json"}})
    with pytest.raises(VisionParseError):
        provider.observe(_rgba_frame(2, 2))
    provider_empty_object = _provider_with_chat(
        lambda path, body: {"message": {"content": "{}"}}
    )
    with pytest.raises(VisionParseError):
        provider_empty_object.observe(_rgba_frame(2, 2))
    provider_bad_thinking = _provider_with_chat(
        lambda path, body: {"message": {"content": "", "thinking": "not-json"}}
    )
    with pytest.raises(VisionParseError):
        provider_bad_thinking.observe(_rgba_frame(2, 2))


def test_parse_show_flags() -> None:
    info = parse_show("qwen3-vl:8b", {"capabilities": ["completion", "vision", "thinking"]})
    assert info.vision_capable is True
    assert info.thinking is True
