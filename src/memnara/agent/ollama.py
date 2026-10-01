"""Loopback-only Ollama reasoning. Structured action JSON; no chain-of-thought storage."""

from __future__ import annotations

import socket
import urllib.error
from typing import Any

from memnara.agent.actions import ActionProposal
from memnara.agent.exceptions import ReasoningError, ReasoningTimeoutError
from memnara.agent.reasoning import (
    ReasoningProvider,
    build_user_prompt,
    proposal_format_for,
    system_prompt_for,
)
from memnara.agent.thinking import clip_text, prompt_size_report
from memnara.agent.validator import ActionValidator
from memnara.perception.context import PerceptionContext
from memnara.perception.vision.exceptions import ModelUnavailableError, OllamaUnavailableError
from memnara.perception.vision.http import LocalJsonSession
from memnara.perception.vision.ollama import (
    DEFAULT_ENDPOINT,
    DEFAULT_KEEP_ALIVE,
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
        keep_alive: str = DEFAULT_KEEP_ALIVE,
        num_predict: int | None = None,
        compact_prompt: bool = False,
        reason_limit: int | None = None,
        session: LocalJsonSession | None = None,
        http_post=None,
    ) -> None:
        self.endpoint = assert_local_endpoint(endpoint)
        self.model = model
        self.timeout_s = timeout_s
        self.think = think
        self.keep_alive = keep_alive
        self.num_predict = num_predict
        self.compact_prompt = compact_prompt
        self.reason_limit = reason_limit
        self.system_prompt = system_prompt_for(compact=compact_prompt)
        self._session = session
        self._owns_session = session is None and http_post is None
        self._http_post = http_post or (session.post_json if session is not None else self._post_json)
        self.last_prompt_chars = 0
        self.last_prompt_sizes: dict[str, int] = {}
        self.last_eval_count: int | None = None

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
            "keep_alive": self.keep_alive,
            "format": proposal_format_for(reason_limit=self.reason_limit),
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user},
            ],
        }
        if self.num_predict is not None:
            payload["options"] = {"num_predict": int(self.num_predict)}
        self.last_prompt_sizes = prompt_size_report(self.system_prompt, user)
        self.last_prompt_chars = self.last_prompt_sizes["total_chars"]
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
        eval_count = response.get("eval_count") if isinstance(response, dict) else None
        self.last_eval_count = int(eval_count) if isinstance(eval_count, int) else None
        proposal = validator.parse_and_validate(text)
        if self.reason_limit is not None:
            clipped = clip_text(proposal.reason, self.reason_limit)
            if clipped != proposal.reason:
                proposal = ActionProposal(
                    action=proposal.action,
                    parameters=proposal.parameters,
                    reason=clipped,
                    confidence=proposal.confidence,
                    metadata=dict(proposal.metadata),
                )
        if used_thinking:
            return ActionProposal(
                action=proposal.action,
                parameters=proposal.parameters,
                reason=proposal.reason,
                confidence=proposal.confidence,
                metadata={"json_in_message.thinking": True},
            )
        return proposal

    def close(self) -> None:
        if self._owns_session and self._session is not None:
            self._session.close()
            self._session = None

    def _lazy_session(self) -> LocalJsonSession:
        if self._session is None:
            self._session = LocalJsonSession.from_endpoint(self.endpoint, timeout_s=self.timeout_s)
            self._owns_session = True
        return self._session

    def _post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._lazy_session().post_json(path, body)
