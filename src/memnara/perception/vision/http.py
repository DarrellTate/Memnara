"""Loopback JSON HTTP with connection reuse. No cloud hosts. No new packages."""

from __future__ import annotations

import http.client
import json
import socket
import urllib.error
from email.message import Message
from typing import Any
from urllib.parse import urlparse

from memnara.perception.vision.exceptions import LocalOnlyEndpointError, VisionParseError

ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class LocalJsonSession:
    """One keep-alive HTTP connection to a loopback Ollama endpoint.

    Callers that inject `http_post` in tests never need this. A live process
    should close the session on shutdown.
    """

    def __init__(self, *, host: str, port: int, timeout_s: float, scheme: str = "http") -> None:
        host_key = (host or "").lower()
        if host_key not in ALLOWED_HOSTS:
            raise LocalOnlyEndpointError(
                f"Ollama endpoint must be loopback (127.0.0.1/localhost); got {host or 'empty'!r}"
            )
        if scheme not in {"http", "https"}:
            raise LocalOnlyEndpointError(f"unsupported Ollama URL scheme: {scheme}")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self.scheme = scheme
        self._conn: http.client.HTTPConnection | None = None
        self._closed = False
        self.requests = 0
        self.reconnects = 0

    @classmethod
    def from_endpoint(cls, endpoint: str, *, timeout_s: float) -> LocalJsonSession:
        parsed = urlparse(endpoint)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return cls(host=host, port=port, timeout_s=timeout_s, scheme=parsed.scheme or "http")

    def get_json(self, path: str) -> dict[str, Any]:
        return self.request("GET", path, None)

    def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", path, body)

    def request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        if self._closed:
            raise OSError("LocalJsonSession is closed")
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json", "Connection": "keep-alive"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            raw = self._send(method, path, payload, headers)
        except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError, http.client.CannotSendRequest):
            self._reset()
            self.reconnects += 1
            raw = self._send(method, path, payload, headers)
        self.requests += 1
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise VisionParseError(f"Ollama returned non-JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise VisionParseError("Ollama JSON must be an object")
        return parsed

    def close(self) -> None:
        self._closed = True
        self._reset()

    @property
    def closed(self) -> bool:
        return self._closed

    def _send(self, method: str, path: str, payload: bytes | None, headers: dict[str, str]) -> str:
        conn = self._connection()
        try:
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read().decode("utf-8")
        except socket.timeout as exc:
            self._reset()
            raise TimeoutError(str(exc)) from exc
        except TimeoutError:
            self._reset()
            raise
        except OSError:
            self._reset()
            raise
        if response.status >= 400:
            error = http.client.HTTPException(f"HTTP {response.status}")
            error.status = response.status  # type: ignore[attr-defined]
            error.body = raw  # type: ignore[attr-defined]
            raise _httperror(response.status, raw)
        return raw

    def _connection(self) -> http.client.HTTPConnection:
        if self._conn is None:
            if self.scheme == "https":
                self._conn = http.client.HTTPSConnection(
                    self.host, self.port, timeout=self.timeout_s
                )
            else:
                self._conn = http.client.HTTPConnection(
                    self.host, self.port, timeout=self.timeout_s
                )
        return self._conn

    def _reset(self) -> None:
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


class _Body:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body


def _httperror(code: int, body: str):
    return urllib.error.HTTPError(
        url="",
        code=code,
        msg=f"HTTP {code}",
        hdrs=Message(),
        fp=_Body(body),
    )
