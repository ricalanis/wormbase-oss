"""WormBase voice agent.

Bridges ElevenLabs Conversational AI to the WormBase ledger and the
Kimi-via-Ollama brain. Phone calls and browser voice sessions land as
ledger entries indistinguishable from Slack chat (per the design doc at
``docs/superpowers/specs/2026-04-26-voice-agent-design.md``).

Public surface (kept deliberately small):

* :class:`VoiceAgent` — facade over ledger + Kimi for one-call
  programmatic use (mostly for tests and embedding scenarios).
* :class:`VoiceAgentConfig` — static config knob bundle.
* :class:`AudioRef` — content-addressed audio reference (filesystem
  path + sha256 + duration). Mirrors §6 of the design doc.
* :class:`VoiceTurn` / :class:`VoiceTurnReply` — request/response data
  classes for one inbound utterance.
* :class:`VoiceProvider` — Protocol so we can swap ElevenLabs out (Phase 2).

The HTTP surface (the ElevenLabs webhook handlers) lives in
:mod:`wormbase_voice_agent.app` so unit-testing :class:`VoiceAgent` doesn't
require FastAPI to be imported.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from wormbase_voice_agent.audit import (
    emit_chat_received,
    emit_chat_sent,
    emit_chat_session_closed,
    emit_chat_session_started,
)
from wormbase_voice_agent.elevenlabs import (
    KimiOllamaClient,
    build_voice_prompt,
    fetch_recent_conversation_context,
)

__all__ = [
    "AudioRef",
    "VoiceAgent",
    "VoiceAgentConfig",
    "VoiceProvider",
    "VoiceTurn",
    "VoiceTurnReply",
]


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudioRef:
    """Reference to an audio blob in object storage.

    Mirrors the ``AudioRef`` proposed for ``ChatReceivedPayload`` /
    ``ChatSentPayload`` in §6 of the design doc. For the demo build,
    ``storage_url`` is a filesystem path under ``/tmp/voice-audio``;
    production swaps it for an S3 URL.
    """

    storage_url: str
    sha256: str
    duration_ms: int
    transcript_method: Literal["elevenlabs-stt", "whisper-large-v3"]
    speaker: Literal["caller", "agent"]


@dataclass(frozen=True)
class VoiceTurn:
    """One inbound utterance from the voice provider's webhook."""

    session_id: str
    company_id: UUID
    transcript: str
    audio_ref: AudioRef | None
    # ElevenLabs sends an OpenAI-shaped messages array; carry it through
    # opaquely.
    messages: list[dict[str, Any]]
    caller_id: str | None = None


@dataclass(frozen=True)
class VoiceTurnReply:
    """One outbound reply for the voice provider to TTS."""

    text: str
    audio_ref: AudioRef | None
    ledger_chat_received_id: str
    ledger_chat_sent_id: str


@dataclass(frozen=True)
class VoiceAgentConfig:
    """Static config; the CLI / docker-compose env populates this."""

    company_id: UUID
    voice_provider: Literal["elevenlabs", "openai-realtime", "stub"] = "elevenlabs"
    audio_bucket: str = "/tmp/voice-audio"
    elevenlabs_agent_id: str | None = None
    elevenlabs_api_key: str | None = None
    inference_route: str = "ollama/kimi-k2.6:cloud"
    fallback_route: str = "ollama/gpt-oss:120b"


# ---------------------------------------------------------------------------
# Provider Protocol — kept thin (one method per session boundary).
# ---------------------------------------------------------------------------


class VoiceProvider(Protocol):
    """Hosted-voice abstraction. ElevenLabs is the default impl."""

    async def session_started(self, session_id: str) -> None: ...

    async def session_ended(
        self, session_id: str, *, recording_url: str, transcript_url: str
    ) -> None: ...


# ---------------------------------------------------------------------------
# Programmatic facade — used by tests and any embedding scenario.
# ---------------------------------------------------------------------------


class VoiceAgent:
    """Bridges a voice provider to the WormBase ledger.

    Tests construct one with an ``InMemoryLedger`` and a fake Kimi client,
    then call :meth:`handle_turn` to verify ledger semantics. The
    HTTP-facing FastAPI app in :mod:`wormbase_voice_agent.app` builds an
    equivalent flow on top of dependency-injected state.
    """

    def __init__(
        self,
        config: VoiceAgentConfig,
        *,
        ledger: Any,
        kimi: KimiOllamaClient | None = None,
        provider: VoiceProvider | None = None,
        # Legacy kwarg from the stub interface — accept it but ignore it.
        # Voice-agent currently goes direct to Ollama; an inference router
        # plugs in here when packages/inference-router lands.
        inference_router: Any | None = None,
    ) -> None:
        self._config = config
        self._ledger = ledger
        self._kimi = kimi or KimiOllamaClient()
        self._provider = provider
        self._inference_router = inference_router

    @property
    def config(self) -> VoiceAgentConfig:
        return self._config

    async def handle_turn(self, turn: VoiceTurn) -> VoiceTurnReply:
        """Process one inbound utterance end-to-end.

        Steps:

        1. Write ``chat_received`` (with ``modality="voice"`` and the
           caller's ``audio_ref``).
        2. Fetch recent conversation lake context, prepend to the
           prompt.
        3. Call Kimi (with ``gpt-oss:120b`` fallback).
        4. Write ``chat_sent`` with the reply.
        5. Return :class:`VoiceTurnReply` carrying both ledger ids.
        """
        message_id_in = f"vt-in-{uuid4().hex[:12]}"
        in_audio_path = (
            turn.audio_ref.storage_url if turn.audio_ref is not None else None
        )

        received = await emit_chat_received(
            self._ledger,
            company_id=turn.company_id,
            session_id=turn.session_id,
            message_id=message_id_in,
            text=turn.transcript,
            caller_id=turn.caller_id,
            audio_ref=in_audio_path,
            timestamp=datetime.now(UTC),
        )

        history = await fetch_recent_conversation_context(
            self._ledger, turn.company_id,
        )
        prompt = build_voice_prompt(turn.transcript, history=history)
        reply_text = await self._kimi.chat(prompt)

        message_id_out = f"vt-out-{uuid4().hex[:12]}"
        sent = await emit_chat_sent(
            self._ledger,
            company_id=turn.company_id,
            session_id=turn.session_id,
            message_id=message_id_out,
            text=reply_text,
            in_reply_to=message_id_in,
            audio_ref=None,
            timestamp=datetime.now(UTC),
        )

        return VoiceTurnReply(
            text=reply_text,
            audio_ref=None,
            ledger_chat_received_id=str(received.entry_ids[1]),  # execute id
            ledger_chat_sent_id=str(sent.entry_ids[1]),
        )

    async def session_started(self, session_id: str, company_id: UUID) -> None:
        """Open a voice session in the ledger."""
        await emit_chat_session_started(
            self._ledger,
            company_id=company_id,
            session_id=session_id,
            caller_id=None,
        )
        if self._provider is not None:
            await self._provider.session_started(session_id)

    async def session_ended(
        self,
        session_id: str,
        company_id: UUID,
        *,
        recording_url: str | None = None,
        recording_sha256: str | None = None,
        transcript_url: str | None = None,
        turn_count: int = 0,
    ) -> None:
        """Close a voice session — emit ``chat_session_closed``."""
        await emit_chat_session_closed(
            self._ledger,
            company_id=company_id,
            session_id=session_id,
            started_at=None,
            ended_at=None,
            turn_count=turn_count,
            full_recording_url=recording_url,
            full_recording_sha256=recording_sha256,
            transcript_url=transcript_url,
        )
        if self._provider is not None and recording_url and transcript_url:
            await self._provider.session_ended(
                session_id,
                recording_url=recording_url,
                transcript_url=transcript_url,
            )
