"""Optional in-character LLM riff.

When a beat declares ``improv: true``, the engine asks the LLM to rewrite
the seed line in the persona's voice instead of posting it verbatim. We
hit Ollama Cloud (``kimi-k2.6:cloud``) directly using the same pattern as
``wormbase_core.classifier``; if no API key is configured, we degrade to
the literal seed text — the demo still runs, it just sounds scripted.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from wormbase_sim_harness.personas import Persona

log = logging.getLogger(__name__)

_DEFAULT_OLLAMA_BASE = "https://ollama.com"
_DEFAULT_OLLAMA_MODEL = "kimi-k2.6:cloud"

_PROMPT = (
    "You are {display_name}, role: {role}. Voice: {voice}.\n"
    "The user said this seed: {seed}\n"
    "Reply in 1-2 sentences max, in character. No quotes, no name prefix."
)


class ImprovEngine:
    """Generates persona-flavored variants of seed lines.

    Falls back to the literal seed text on any error (missing key,
    network, malformed JSON) — improv is decoration, not a hard
    requirement of the demo loop.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = _DEFAULT_OLLAMA_MODEL,
        client: httpx.AsyncClient | None = None,
        enabled: bool = True,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("OLLAMA_API_KEY")
        self._base = (base_url or os.environ.get(
            "OLLAMA_API_BASE", _DEFAULT_OLLAMA_BASE
        )).rstrip("/")
        self._model = model
        self._client = client
        self._enabled = enabled and bool(self._api_key)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def generate(self, persona: Persona, seed: str) -> str:
        """Return an in-character riff or the seed itself on failure."""
        if not self._enabled:
            return seed

        prompt = _PROMPT.format(
            display_name=persona.display_name,
            role=persona.role,
            voice=persona.voice_hint or "natural, conversational",
            seed=seed,
        )
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "Reply with prose only, no JSON, no quotes."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "stream": False,
        }
        client = self._client or httpx.AsyncClient(timeout=20.0)
        own_client = self._client is None
        try:
            r = await client.post(f"{self._base}/api/chat", headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            log.info("improv fallback (network/json): %s", exc)
            return seed
        finally:
            if own_client:
                await client.aclose()

        msg = data.get("message") if isinstance(data, dict) else None
        text = (msg or {}).get("content") if isinstance(msg, dict) else None
        if isinstance(text, str) and text.strip():
            return text.strip()
        return seed


__all__ = ["ImprovEngine"]
