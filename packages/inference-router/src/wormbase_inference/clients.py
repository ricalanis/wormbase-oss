"""Blocks C + D — concrete inference backends.

Two backends, one Protocol (:class:`InferenceClient`):

* :class:`KimiClient` — Ollama-Cloud-routed Kimi K2.6. Used for
  high-stakes reasoning, affirm, voice turns. Auth: ``OLLAMA_API_KEY``.
* :class:`GemmaClient` — own-VLAN Ollama hosting ``gemma4:e4b``. Used
  for classify / summarize / commodity inference. Auth: optional
  ``OLLAMA_OWN_API_KEY``.

Both speak the Ollama ``/api/chat`` shape — an OpenAI-compatible chat
endpoint that returns ``{message: {role, content}}``. Differences are
only the base URL, default model, and (for Kimi) the cloud bearer token.

Both clients raise :class:`InferenceError` on any failure (network,
non-2xx, malformed body, missing content). The router catches
``InferenceError`` to drive its own fallback policy; consumer code
should not catch it directly.

Note on the "Kimi base URL" referenced in the orchestrator's plan
-----------------------------------------------------------------

The orchestrator's plan said ``https://api.moonshot.ai/v1``. Production
in this repo (voice-agent's :class:`KimiOllamaClient`,
chat-presence's :class:`OllamaCloudClassifier`) speaks Ollama Cloud at
``https://ollama.com``. The router follows production. Swapping to
Moonshot's native API later is a one-flag change inside
:class:`KimiClient` (different base URL, same OpenAI-shaped body).
The exposed env vars are deliberately ``OLLAMA_*`` to match what
already lives in ``.env`` and ``.env.example``.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults — pulled from existing production code.
# ---------------------------------------------------------------------------

DEFAULT_OLLAMA_BASE: str = "https://ollama.com"
DEFAULT_KIMI_MODEL: str = "kimi-k2.6:cloud"

# Default own-inference base. Defaults to localhost so a developer
# running ``ollama serve`` locally Just Works; in production this is
# overridden to the VLAN endpoint via env.
DEFAULT_OLLAMA_OWN_BASE: str = "http://localhost:11434"
DEFAULT_GEMMA_MODEL: str = "gemma4:e4b"


class InferenceError(RuntimeError):
    """Wrap any backend failure so the router can drive fallback."""


@runtime_checkable
class InferenceClient(Protocol):
    """The single Protocol both Kimi and Gemma satisfy.

    Implementations are async + cheap to construct (no I/O at __init__).
    """

    name: str  # "kimi" | "gemma"
    model: str

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Run one chat completion; return the assistant's text reply.

        Raises :class:`InferenceError` on any failure.
        """
        ...

    async def aclose(self) -> None:
        """Release any owned httpx client."""
        ...


# ---------------------------------------------------------------------------
# Helper — shared body POST against an Ollama-shaped endpoint.
# ---------------------------------------------------------------------------


async def _post_chat(
    *,
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
) -> str:
    """POST one chat-completion; return the assistant content string.

    Raises :class:`InferenceError` on any failure.
    """
    try:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as exc:
        raise InferenceError(f"http error: {exc}") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise InferenceError(f"malformed response body: {exc}") from exc

    if not isinstance(data, dict):
        raise InferenceError("response was not a JSON object")
    msg = data.get("message")
    if not isinstance(msg, dict):
        raise InferenceError("response missing 'message' object")
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise InferenceError("response content was empty")
    return content.strip()


# ---------------------------------------------------------------------------
# KimiClient — remote inference (Ollama Cloud).
# ---------------------------------------------------------------------------


@dataclass
class KimiClient:
    """Async Kimi client routed through Ollama Cloud.

    Configurable via constructor kwargs OR env:

    * ``OLLAMA_API_KEY`` — bearer token (required for cloud).
    * ``OLLAMA_API_BASE`` — default ``https://ollama.com``.

    A custom ``client`` can be injected for tests. When omitted, a
    fresh :class:`httpx.AsyncClient` is created on first call and
    closed by :meth:`aclose`.
    """

    api_key: str | None = None
    base_url: str = DEFAULT_OLLAMA_BASE
    model: str = DEFAULT_KIMI_MODEL
    timeout_s: float = 30.0
    client: httpx.AsyncClient | None = None
    name: str = field(default="kimi", init=False)
    _own_client: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("OLLAMA_API_KEY")
        env_base = os.environ.get("OLLAMA_API_BASE")
        if env_base:
            self.base_url = env_base
        self.base_url = self.base_url.rstrip("/")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        if not self.api_key:
            raise InferenceError(
                "kimi: OLLAMA_API_KEY is not configured; remote inference unavailable"
            )
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout_s)
            self._own_client = True

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        return await _post_chat(
            client=self.client,
            url=f"{self.base_url}/api/chat",
            headers=headers,
            body=body,
        )

    async def aclose(self) -> None:
        if self._own_client and self.client is not None:
            await self.client.aclose()
            self.client = None
            self._own_client = False


# ---------------------------------------------------------------------------
# GemmaClient — own inference (private VLAN Ollama).
# ---------------------------------------------------------------------------


@dataclass
class GemmaClient:
    """Async Gemma client targeting an Ollama-compatible VLAN endpoint.

    Configurable via constructor kwargs OR env:

    * ``OLLAMA_OWN_BASE_URL`` — base URL of the VLAN endpoint
      (default ``http://localhost:11434``).
    * ``OLLAMA_OWN_API_KEY`` — bearer token if the endpoint requires it
      (most local Ollama installs do not). Optional.

    The default model is ``gemma4:e4b`` per the project CLAUDE.md
    "Remote vs own inference" section.
    """

    api_key: str | None = None
    base_url: str = DEFAULT_OLLAMA_OWN_BASE
    model: str = DEFAULT_GEMMA_MODEL
    timeout_s: float = 30.0
    client: httpx.AsyncClient | None = None
    name: str = field(default="gemma", init=False)
    _own_client: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("OLLAMA_OWN_API_KEY")
        env_base = os.environ.get("OLLAMA_OWN_BASE_URL")
        if env_base:
            self.base_url = env_base
        self.base_url = self.base_url.rstrip("/")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout_s)
            self._own_client = True

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return await _post_chat(
            client=self.client,
            url=f"{self.base_url}/api/chat",
            headers=headers,
            body=body,
        )

    async def aclose(self) -> None:
        if self._own_client and self.client is not None:
            await self.client.aclose()
            self.client = None
            self._own_client = False


# ---------------------------------------------------------------------------
# Time helper — exported for the router so latency_ms is consistent
# across paths.
# ---------------------------------------------------------------------------


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


__all__ = [
    "DEFAULT_GEMMA_MODEL",
    "DEFAULT_KIMI_MODEL",
    "DEFAULT_OLLAMA_BASE",
    "DEFAULT_OLLAMA_OWN_BASE",
    "GemmaClient",
    "InferenceClient",
    "InferenceError",
    "KimiClient",
    "monotonic_ms",
]
