"""ElevenLabs Conversational AI custom-LLM webhook handler.

ElevenLabs lets you point its hosted voice agent at *your* LLM via a
custom-LLM webhook. The webhook contract is intentionally OpenAI
chat-completions-shaped: ``POST`` a body of ``{model, messages,
temperature, ...}``; respond with an OpenAI-shaped completion object
(``{id, object, model, choices: [{message: {role, content}}], ...}``).

This module owns:

1. The Pydantic models for inbound/outbound payloads. The schemas are
   permissive — ElevenLabs has historically added fields (call_sid,
   conversation_id, etc.) without bumping a contract version. We accept
   anything by setting ``extra="allow"``; we depend on ``messages`` and
   nothing else.

2. ``KimiOllamaClient`` — a thin async HTTP wrapper over the Ollama
   Cloud chat endpoint. Reuses the same env vars as the existing
   :class:`wormbase_core.classifier.OllamaCloudClassifier` (``OLLAMA_API_KEY``
   / ``OLLAMA_API_BASE``) so we don't fragment configuration. Falls back
   to ``gpt-oss:120b`` if Kimi is unreachable (per design-doc §8 risk #2).

3. ``build_voice_prompt`` — pulls the last N ``chat_received`` ledger
   entries for the tenant and prepends them as conversation context, so
   a phone caller asking "what was Q3 revenue?" gets an answer grounded
   in the same conversation lake the Slack worm sees.

This module is **provider-agnostic** about ElevenLabs in one direction
only: it parses their webhook and renders an OpenAI-shaped response.
We don't import the ElevenLabs Python SDK; the contract is HTTP, and a
small shape-tolerant Pydantic wrapper is more reliable than chasing
SDK versions.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults — mirror wormbase_core.classifier so the same OLLAMA_API_KEY env
# var configures both surfaces.
# ---------------------------------------------------------------------------

DEFAULT_OLLAMA_BASE = "https://ollama.com"
DEFAULT_KIMI_MODEL = "kimi-k2.6:cloud"
DEFAULT_FALLBACK_MODEL = "gpt-oss:120b"

# Voice answers must be short and TTS-friendly. The system prompt
# explicitly tells Kimi to write numbers as words for ElevenLabs to read
# aloud cleanly (per design-doc risk-register lower-priority note).
VOICE_SYSTEM_PROMPT = """You are WormBase, an institutional-AI data analyst speaking on a voice call.

Rules for spoken answers:
- Be concise. Two to three sentences max.
- Render numbers and currency as words ElevenLabs can speak: "four point two
  million dollars", not "$4.2M".
- Cite provenance the user can verify: source filename, ingest time, and a
  ledger reference if you have one.
- If you do not have the data, say so plainly. Do not guess.
- The caller is on the phone. Do not output Markdown, code blocks, or URLs.
"""


# ---------------------------------------------------------------------------
# Inbound webhook payloads — accept anything ElevenLabs sends.
# ---------------------------------------------------------------------------


class WebhookMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: str | list[dict[str, Any]] | None = None

    def text(self) -> str:
        """Extract a plain text string regardless of content shape."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            parts: list[str] = []
            for piece in self.content:
                if isinstance(piece, dict):
                    txt = piece.get("text") or piece.get("content")
                    if isinstance(txt, str):
                        parts.append(txt)
            return "\n".join(parts)
        return ""


class LLMWebhookRequest(BaseModel):
    """ElevenLabs custom-LLM webhook body.

    Schemas drift; we accept any extra fields ElevenLabs adds. The fields
    we actually depend on are documented inline.
    """

    model_config = ConfigDict(extra="allow")

    # ElevenLabs sends an OpenAI-style messages array (system, then
    # alternating user/assistant). The user's transcribed utterance is
    # the LAST user message.
    messages: list[WebhookMessage] = Field(default_factory=list)

    # Optional model hint (we ignore it; we always route to Kimi).
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool | None = None

    # Session identifiers. ElevenLabs' field names have varied; we accept
    # any of them and pick the first present.
    conversation_id: str | None = None
    session_id: str | None = None
    agent_id: str | None = None

    # Caller metadata — phone number, "from", "caller_id"; whichever they
    # send. Used as the ``sender_person`` mapping seed.
    user_id: str | None = None
    caller_id: str | None = None

    def latest_user_text(self) -> str:
        for msg in reversed(self.messages):
            if msg.role == "user":
                return msg.text()
        return ""

    def session_key(self) -> str:
        return (
            self.conversation_id
            or self.session_id
            or self.agent_id
            or "unknown-session"
        )

    def caller_key(self) -> str | None:
        return self.user_id or self.caller_id


class SessionWebhookRequest(BaseModel):
    """Body of ``/webhook/elevenlabs/session-start`` and ``/session-end``.

    ElevenLabs sends a small JSON envelope with the conversation id and
    an event type. We accept anything; we only need the session id.
    """

    model_config = ConfigDict(extra="allow")

    conversation_id: str | None = None
    session_id: str | None = None
    agent_id: str | None = None
    user_id: str | None = None
    caller_id: str | None = None
    event_type: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    transcript_url: str | None = None
    recording_url: str | None = None
    turn_count: int | None = None

    def session_key(self) -> str:
        return (
            self.conversation_id
            or self.session_id
            or self.agent_id
            or "unknown-session"
        )

    def caller_key(self) -> str | None:
        return self.user_id or self.caller_id


# ---------------------------------------------------------------------------
# Outbound response — OpenAI chat-completion shape.
# ---------------------------------------------------------------------------


def openai_chat_response(
    *,
    text: str,
    model: str,
    completion_id: str | None = None,
) -> dict[str, Any]:
    """Render an OpenAI chat-completion response body.

    ElevenLabs reads ``choices[0].message.content`` and ignores the rest,
    but we fill the standard fields so a stricter validator (e.g. their
    SDK) doesn't complain.
    """
    return {
        "id": completion_id or f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }


# ---------------------------------------------------------------------------
# Kimi client (via Ollama Cloud)
# ---------------------------------------------------------------------------


@dataclass
class KimiOllamaClient:
    """Thin async HTTP client targeting Ollama Cloud.

    Configurable via constructor kwargs OR the existing env vars used by
    ``wormbase_core.classifier.OllamaCloudClassifier`` so a single
    ``OLLAMA_API_KEY`` configures both surfaces:

    - ``OLLAMA_API_KEY``  — bearer token (required for cloud routes).
    - ``OLLAMA_API_BASE`` — default ``https://ollama.com``.
    """

    api_key: str | None = None
    base_url: str = DEFAULT_OLLAMA_BASE
    model: str = DEFAULT_KIMI_MODEL
    fallback_model: str = DEFAULT_FALLBACK_MODEL
    timeout_s: float = 20.0
    client: httpx.AsyncClient | None = None

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
        model: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Run one chat completion; return the assistant's text reply.

        Tries the primary ``model``; on failure (timeout, 5xx, malformed
        body) retries once on ``fallback_model``. Both attempts emit
        structured logs so demo-day operators can see which path served
        the answer.
        """
        primary = model or self.model
        try:
            return await self._call(messages, primary, temperature)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "voice-agent: kimi primary failed (%s); falling back to %s",
                exc,
                self.fallback_model,
            )
            return await self._call(messages, self.fallback_model, temperature)

    async def _call(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
    ) -> str:
        if not self.api_key:
            # No key configured: return a deterministic placeholder so the
            # webhook doesn't 500 in dev. Demo-day must set the key.
            logger.warning(
                "voice-agent: OLLAMA_API_KEY not set — returning stub reply"
            )
            return (
                "I am offline at the moment. The Ollama API key is not "
                "configured on the voice agent."
            )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        client = self.client or httpx.AsyncClient(timeout=self.timeout_s)
        own_client = self.client is None
        try:
            r = await client.post(
                f"{self.base_url}/api/chat", headers=headers, json=body,
            )
            r.raise_for_status()
            data = r.json()
        finally:
            if own_client:
                await client.aclose()

        content = (
            data.get("message", {}).get("content")
            if isinstance(data, dict) else None
        )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("ollama returned empty content")
        return content.strip()


# ---------------------------------------------------------------------------
# Conversation-context builder
# ---------------------------------------------------------------------------


async def fetch_recent_conversation_context(
    ledger: Any,
    company_id: Any,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Pull the last ``limit`` ``chat_received`` execute rows for the tenant.

    Returns a list of ``{role: "user"|"assistant", content: str}`` dicts
    suitable for prepending to the LLM messages array. Quietly returns
    ``[]`` if the ledger fetch fails — a missing context is preferable to
    a 500 mid-call.
    """
    try:
        rows = await ledger.fetch(company_id)
    except Exception as exc:  # noqa: BLE001 — best-effort context
        logger.warning("voice-agent: ledger fetch failed for context: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        tool = payload.get("tool", "")
        args = payload.get("args") or {}
        text = args.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        if tool.endswith("emit_chat_received"):
            out.append({"role": "user", "content": text})
        elif tool.endswith("emit_chat_sent"):
            out.append({"role": "assistant", "content": text})
    return out[-limit:]


def build_voice_prompt(
    user_text: str,
    *,
    history: list[dict[str, Any]] | None = None,
    extra_system: str | None = None,
) -> list[dict[str, Any]]:
    """Compose the full Kimi messages array for one voice turn."""
    system = VOICE_SYSTEM_PROMPT
    if extra_system:
        system = f"{system}\n\n{extra_system.strip()}"
    msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
    if history:
        msgs.extend(history)
    msgs.append({"role": "user", "content": user_text})
    return msgs


__all__ = [
    "DEFAULT_FALLBACK_MODEL",
    "DEFAULT_KIMI_MODEL",
    "DEFAULT_OLLAMA_BASE",
    "KimiOllamaClient",
    "LLMWebhookRequest",
    "SessionWebhookRequest",
    "VOICE_SYSTEM_PROMPT",
    "WebhookMessage",
    "build_voice_prompt",
    "fetch_recent_conversation_context",
    "openai_chat_response",
]
