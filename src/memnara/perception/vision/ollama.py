"""Ollama HTTP vision provider. Loopback only. No gameplay actions."""

from __future__ import annotations

import copy
import socket
import time
import urllib.error
from dataclasses import replace
from typing import Any
from urllib.parse import urlparse

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
from memnara.perception.vision.http import LocalJsonSession
from memnara.perception.vision.images import DEFAULT_SCALE, encode_framebuffer_png
from memnara.perception.vision.models import VisualObservation
from memnara.perception.vision.parse import parse_observation
from memnara.perception.vision.prompts import (
    COMPACT_USER_PROMPT,
    OBSERVATION_FORMAT,
    SYSTEM_PROMPT,
    USER_PROMPT,
)

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
        num_predict: int | None = None,
        description_limit: int | None = None,
        compact_prompt: bool = False,
        session: LocalJsonSession | None = None,
        http_get=None,
        http_post=None,
    ) -> None:
        self.endpoint = assert_local_endpoint(endpoint)
        self.model = model
        self.scale = scale
        self.timeout_s = timeout_s
        self.think = think
        self.keep_alive = keep_alive
        self.num_predict = num_predict
        self.description_limit = description_limit
        self.compact_prompt = compact_prompt
        self._session = session
        self._owns_session = session is None and http_get is None and http_post is None
        self._http_get = http_get or (session.get_json if session is not None else self._get_json)
        self._http_post = http_post or (session.post_json if session is not None else self._post_json)
        self._model_checked = False
        self.last_prompt_chars = 0
        self.last_eval_count: int | None = None

    def observe(self, frame: Framebuffer) -> VisualObservation:
        self.ensure_model()
        png, width, height = encode_framebuffer_png(frame, scale=self.scale)
        image_b64 = base64.b64encode(png).decode("ascii")
        user_prompt = COMPACT_USER_PROMPT if self.compact_prompt else USER_PROMPT
        observation_format = copy.deepcopy(OBSERVATION_FORMAT)
        if self.description_limit is not None:
            observation_format["properties"]["description"]["maxLength"] = int(self.description_limit)
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "format": observation_format,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": [image_b64],
                },
            ],
        }
        if self.num_predict is not None:
            payload["options"] = {"num_predict": int(self.num_predict)}
        self.last_prompt_chars = len(SYSTEM_PROMPT) + len(user_prompt)
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
        self.last_eval_count = eval_int
        if self.description_limit is not None:
            clipped = _clip_text(observation.description, self.description_limit)
            if clipped != observation.description:
                observation = replace(observation, description=clipped)
        if used_thinking:
            extra = "json_in_message.thinking (content empty; think=false still used thinking field)"
            notes = f"{observation.notes}; {extra}" if observation.notes else extra
            return replace(observation, notes=notes)
        return observation

    def close(self) -> None:
        if self._owns_session and self._session is not None:
            self._session.close()
            self._session = None

    def ensure_model(self) -> None:
        if self._model_checked:
            return
        require_vision_model(self.model, get_json=self._http_get, post_json=self._http_post)
        self._model_checked = True

    def _lazy_session(self) -> LocalJsonSession:
        if self._session is None:
            self._session = LocalJsonSession.from_endpoint(self.endpoint, timeout_s=self.timeout_s)
            self._owns_session = True
        return self._session

    def _get_json(self, path: str) -> dict[str, Any]:
        return self._lazy_session().get_json(path)

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._lazy_session().post_json(path, body)


def _clip_text(text: str, limit: int) -> str:
    stripped = (text or "").strip()
    if limit < 1 or len(stripped) <= limit:
        return stripped
    clipped = stripped[:limit].rstrip()
    if " " in clipped[ max(0, limit // 2) :]:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped or stripped[:limit]
