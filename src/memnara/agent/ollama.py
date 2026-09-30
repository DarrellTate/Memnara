"""Loopback-only Ollama reasoning. Structured action JSON; no chain-of-thought storage."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin

from memnara.agent.actions import ActionProposal
from memnara.agent.exceptions import ReasoningError, ReasoningTimeoutError
from memnara.agent.reasoning import PROPOSAL_FORMAT, SYSTEM_PROMPT, ReasoningProvider, build_user_prompt
from memnara.agent.validator import ActionValidator
from memnara.perception.context import PerceptionContext
from memnara.perception.vision.exceptions import ModelUnavailableError, OllamaUnavailableError
from memnara.perception.vision.ollama import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    assert_local_endpoint,
)


class OllamaReasoningProvider(ReasoningProvider):
    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 120.0,
        think: bool = False,
        http_post=None,
    ) -> None:
        self.endpoint = assert_local_endpoint(endpoint)
        self.model = model
        self.timeout_s = timeout_s
        self.think = think
        self._http_post = http_post or self._post_json

    def propose(
        self,
        *,
        context: PerceptionContext,
        goal: str,
        stuck_state: str,
        discouraged: tuple[str, ...],
        history_lines: tuple[str, ...],
        validator: ActionValidator,
    ) -> ActionProposal:
        if not isinstance(context, PerceptionContext):
            raise ReasoningError("reasoning requires PerceptionContext")
        user = build_user_prompt(
            context=context,
            goal=goal,
            allowed=validator.registry.allowed,
            stuck_state=stuck_state,
            discouraged=discouraged,
            history_lines=history_lines,
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "think": self.think,
            "format": PROPOSAL_FORMAT,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = self._http_post("/api/chat", payload)
        except TimeoutError as exc:
            raise ReasoningTimeoutError(f"Ollama reasoning timed out after {self.timeout_s}s") from exc
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if exc.code == 404:
                raise ModelUnavailableError(f"Ollama returned 404 for model {self.model}: {body}") from exc
            raise OllamaUnavailableError(f"Ollama reasoning HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, OSError, socket.timeout) as exc:
            raise OllamaUnavailableError(f"Ollama reasoning failed: {exc}") from exc
        message = (response.get("message") or {}) if isinstance(response, dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        thinking = message.get("thinking") if isinstance(message, dict) else None
        text = content if isinstance(content, str) and content.strip() else ""
        used_thinking = False
        if not text and isinstance(thinking, str) and thinking.strip():
            text = thinking
            used_thinking = True
        if not text:
            raise ReasoningError("Ollama reasoning response missing message.content")
        proposal = validator.parse_and_validate(text)
        if used_thinking:
            return ActionProposal(
                action=proposal.action,
                parameters=proposal.parameters,
                reason=proposal.reason,
                confidence=proposal.confidence,
                metadata={"json_in_message.thinking": True},
            )
        return proposal

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = urljoin(self.endpoint + "/", path.lstrip("/"))
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
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
            raise ReasoningError(f"Ollama returned non-JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ReasoningError("Ollama JSON must be an object")
        return parsed
