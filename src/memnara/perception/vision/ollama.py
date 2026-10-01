"""Ollama HTTP vision provider. Loopback only. No gameplay actions."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any
from urllib.parse import urljoin, urlparse

from memnara.emulators.base import Framebuffer
from memnara.perception.vision.base import VisionProvider
from memnara.perception.vision.discovery import require_vision_model
from memnara.perception.vision.exceptions import (
    LocalOnlyEndpointError,
    ModelUnavailableError,
    OllamaUnavailableError,
    VisionParseError,
    VisionTimeoutError,
)
from memnara.perception.vision.images import DEFAULT_SCALE, encode_framebuffer_png
from memnara.perception.vision.models import VisualObservation
from memnara.perception.vision.parse import parse_observation
from memnara.perception.vision.prompts import OBSERVATION_FORMAT, SYSTEM_PROMPT, USER_PROMPT

import base64

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_TIMEOUT_S = 120.0
DEFAULT_MODEL = "qwen3-vl:8b"
# Longer than Ollama's 5-minute default so a hands-on pause does not reload the model.
DEFAULT_KEEP_ALIVE = "30m"


def assert_local_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"}:
        raise LocalOnlyEndpointError(f"unsupported Ollama URL scheme: {endpoint}")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise LocalOnlyEndpointError(
            f"Ollama endpoint must be loopback (127.0.0.1/localhost); got {host or endpoint!r}"
        )
    if parsed.port is None:
        return endpoint.rstrip("/")
    return endpoint.rstrip("/")


class OllamaVisionProvider(VisionProvider):
    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        scale: int = DEFAULT_SCALE,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        think: bool = False,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
        http_get=None,
        http_post=None,
    ) -> None:
        self.endpoint = assert_local_endpoint(endpoint)
        self.model = model
        self.scale = scale
        self.timeout_s = timeout_s
        self.think = think
        self.keep_alive = keep_alive
        self._http_get = http_get or self._get_json
        self._http_post = http_post or self._post_json
        self._model_checked = False

    def observe(self, frame: Framebuffer) -> VisualObservation:
        self.ensure_model()
        png, width, height = encode_framebuffer_png(frame, scale=self.scale)
        image_b64 = base64.b64encode(png).decode("ascii")
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "format": OBSERVATION_FORMAT,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": USER_PROMPT,
                    "images": [image_b64],
                },
            ],
        }
        started = time.perf_counter()
        try:
            response = self._http_post("/api/chat", payload)
        except TimeoutError as exc:
            raise VisionTimeoutError(f"Ollama chat timed out after {self.timeout_s}s") from exc
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if exc.code == 404:
                raise ModelUnavailableError(f"Ollama returned 404 for model {self.model}: {body}") from exc
            raise OllamaUnavailableError(f"Ollama chat HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, OSError, socket.timeout) as exc:
            raise OllamaUnavailableError(f"Ollama chat failed: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        message = (response.get("message") or {}) if isinstance(response, dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        thinking = message.get("thinking") if isinstance(message, dict) else None
        text = content if isinstance(content, str) and content.strip() else ""
        used_thinking = False
        if not text and isinstance(thinking, str) and thinking.strip():
            text = thinking
            used_thinking = True
        if not text:
            raise VisionParseError("Ollama chat response missing message.content")
        eval_count = response.get("eval_count") if isinstance(response, dict) else None
        eval_int = int(eval_count) if isinstance(eval_count, int) else None
        observation = parse_observation(
            text,
            model=self.model,
            scale=self.scale,
            image_width=width,
            image_height=height,
            latency_ms=latency_ms,
            eval_count=eval_int,
        )
        if used_thinking:
            extra = "json_in_message.thinking (content empty; think=false still used thinking field)"
            notes = f"{observation.notes}; {extra}" if observation.notes else extra
            return replace(observation, notes=notes)
        return observation

    def ensure_model(self) -> None:
        if self._model_checked:
            return
        require_vision_model(self.model, get_json=self._http_get, post_json=self._http_post)
        self._model_checked = True

    def _get_json(self, path: str) -> dict[str, Any]:
        return self._request("GET", path, None)

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, body)

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        url = urljoin(self.endpoint + "/", path.lstrip("/"))
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as handle:
                raw = handle.read().decode("utf-8")
        except TimeoutError as exc:
            raise TimeoutError(str(exc)) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, socket.timeout) or "timed out" in str(exc).lower():
                raise TimeoutError(str(exc)) from exc
            raise
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise VisionParseError(f"Ollama returned non-JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise VisionParseError("Ollama JSON must be an object")
        return parsed
