"""Ledger writes for voice turns.

Every voice exchange must produce ledger entries indistinguishable in shape
from a Slack chat exchange (per design-doc §6). We reuse the existing
``ChatReceivedPayload`` / ``ChatSentPayload`` schemas from
:mod:`wormbase_ledger` but augment the *execute* payload's top-level dict
with two extra keys:

* ``modality`` — the literal string ``"voice"`` so JSONB queries like
  ``payload->>'modality' = 'voice'`` find every voice utterance.
* ``audio_ref`` — the filesystem path (or ``None``) where the audio blob
  lives, set by :mod:`audio_store`.

These keys ride alongside the canonical ``tool``, ``args``, ``result_ref``
fields on the execute entry. The hash chain treats them like any other
content — every byte is hash-chainable.

We additionally emit two **session-scoped** entries — ``chat_session_started``
and ``chat_session_closed``. The ledger has no dedicated payload type for
either, so we piggyback on the canonical ``propose → execute → verify →
resolve`` write primitive with ``target_kind = "chat_session_started"`` /
``"chat_session_closed"`` on the propose row. Downstream replay tools can
filter on ``execute.payload.tool == "voice_agent.session_started"``
without any schema migration.

Channel-id convention: ``voice:elevenlabs:<session_id>`` (matches design
doc §6).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import ChatReceivedPayload, ChatSentPayload
from wormbase_ledger.write_primitive import WriteResult

# Stable namespace for caller -> sender_person UUID mapping.
# The ChatReceivedPayload requires ``sender_person`` as a UUID; we don't
# know who the phone caller is yet, so we hash whatever caller identifier
# the provider gives us (phone number, agent-side caller id, "anonymous").
VOICE_CALLER_NAMESPACE = uuid5(
    UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f"),  # WORMBASE_TENANT_NAMESPACE
    "voice-caller-namespace",
)


def caller_to_person_uuid(caller_id: str | None) -> UUID:
    """Deterministic mapping caller-id -> sender_person UUID."""
    if not caller_id:
        return uuid5(VOICE_CALLER_NAMESPACE, "__anonymous_caller__")
    return uuid5(VOICE_CALLER_NAMESPACE, caller_id)


def voice_channel_id(session_id: str) -> str:
    """Canonical channel id for a voice session (design-doc §6)."""
    return f"voice:elevenlabs:{session_id}"


# ---------------------------------------------------------------------------
# Module-level audit helpers (function form so callers can pass any
# Ledger-shaped object; the FastAPI app wires the real Postgres Ledger,
# tests pass an InMemoryLedger).
# ---------------------------------------------------------------------------


async def emit_chat_received(
    ledger: Ledger | InMemoryLedger | Any,
    *,
    company_id: UUID,
    session_id: str,
    message_id: str,
    text: str,
    caller_id: str | None,
    audio_ref: str | None,
    classification: str = "internal",
    timestamp: datetime | None = None,
) -> WriteResult:
    """Persist one inbound voice utterance via the canonical PEVR cycle.

    The ``modality="voice"`` and ``audio_ref`` tags ride at the execute
    payload's top level so JSONB queries can find every voice exchange
    without a schema migration. Returns the resulting ``WriteResult`` so
    callers can correlate with the outbound write that follows.
    """
    ts = timestamp or datetime.now(UTC)
    ref_id = uuid4()
    payload = ChatReceivedPayload(
        channel_id=voice_channel_id(session_id),
        message_id=message_id,
        sender_person=caller_to_person_uuid(caller_id),
        text=text,
        classification=classification,  # type: ignore[arg-type]
    )
    args = payload.model_dump(mode="json")

    return await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(ref_id),
            "reason": f"voice inbound from {caller_id or 'anonymous'}",
            "proposed_by": "voice-agent",
        },
        execute_fn=lambda: {
            "tool": "voice_agent.emit_chat_received",
            "args": args,
            "result_ref": message_id,
            "modality": "voice",
            "audio_ref": audio_ref,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "payload_valid", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "voice inbound persisted",
        },
        timestamp=ts,
        quadrant="active_probabilistic",
    )


async def emit_chat_sent(
    ledger: Ledger | InMemoryLedger | Any,
    *,
    company_id: UUID,
    session_id: str,
    message_id: str,
    text: str,
    in_reply_to: str | None,
    audio_ref: str | None,
    attribution: dict[str, Any] | None = None,
    speech_act: str = "answer",
    timestamp: datetime | None = None,
) -> WriteResult:
    """Persist one outbound voice reply via the canonical PEVR cycle."""
    ts = timestamp or datetime.now(UTC)
    ref_id = uuid4()
    payload = ChatSentPayload(
        channel_id=voice_channel_id(session_id),
        message_id=message_id,
        text=text,
        in_reply_to=in_reply_to,
        attribution={
            "source": "voice-agent",
            "session_id": session_id,
            **(attribution or {}),
        },
        speech_act=speech_act,  # type: ignore[arg-type]
    )
    args = payload.model_dump(mode="json")

    return await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_sent",
            "ref_id": str(ref_id),
            "reason": "voice agent reply",
            "proposed_by": "voice-agent",
        },
        execute_fn=lambda: {
            "tool": "voice_agent.emit_chat_sent",
            "args": args,
            "result_ref": message_id,
            "modality": "voice",
            "audio_ref": audio_ref,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "payload_valid", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "voice reply persisted",
        },
        timestamp=ts,
        quadrant="active_probabilistic",
    )


async def emit_chat_session_started(
    ledger: Ledger | InMemoryLedger | Any,
    *,
    company_id: UUID,
    session_id: str,
    caller_id: str | None,
    timestamp: datetime | None = None,
) -> WriteResult:
    """Open a voice session in the ledger.

    There's no first-class ``ChatSessionStartedPayload`` in the ledger
    (yet); we ride on the propose/execute/verify/resolve primitive with
    ``target_kind = "chat_session_started"``. Replay tools filter on
    ``execute.payload.tool == "voice_agent.session_started"``.
    """
    ts = timestamp or datetime.now(UTC)
    ref_id = uuid4()
    return await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_session_started",
            "ref_id": str(ref_id),
            "reason": f"voice session started for {caller_id or 'anonymous'}",
            "proposed_by": "voice-agent",
        },
        execute_fn=lambda: {
            "tool": "voice_agent.session_started",
            "args": {
                "channel_id": voice_channel_id(session_id),
                "session_id": session_id,
                "caller_id": caller_id,
                "started_at": ts.isoformat(),
            },
            "result_ref": session_id,
            "modality": "voice",
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "session_id_present", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "voice session opened",
        },
        timestamp=ts,
        quadrant="active_probabilistic",
    )


async def emit_chat_session_closed(
    ledger: Ledger | InMemoryLedger | Any,
    *,
    company_id: UUID,
    session_id: str,
    started_at: datetime | None,
    ended_at: datetime | None,
    turn_count: int,
    full_recording_url: str | None = None,
    full_recording_sha256: str | None = None,
    transcript_url: str | None = None,
    timestamp: datetime | None = None,
) -> WriteResult:
    """Close a voice session — emit the equivalent of
    ``chat_session_closed`` from design-doc §6.
    """
    ts = timestamp or datetime.now(UTC)
    started_iso = (started_at or ts).isoformat()
    ended_iso = (ended_at or ts).isoformat()
    ref_id = uuid4()
    return await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_session_closed",
            "ref_id": str(ref_id),
            "reason": "voice session ended",
            "proposed_by": "voice-agent",
        },
        execute_fn=lambda: {
            "tool": "voice_agent.session_closed",
            "args": {
                "channel_id": voice_channel_id(session_id),
                "session_id": session_id,
                "started_at": started_iso,
                "ended_at": ended_iso,
                "full_recording_url": full_recording_url,
                "full_recording_sha256": full_recording_sha256,
                "transcript_url": transcript_url,
                "turn_count": turn_count,
            },
            "result_ref": session_id,
            "modality": "voice",
            "audio_ref": full_recording_url,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "session_id_present", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "voice session closed",
        },
        timestamp=ts,
        quadrant="active_probabilistic",
    )


__all__ = [
    "VOICE_CALLER_NAMESPACE",
    "caller_to_person_uuid",
    "emit_chat_received",
    "emit_chat_sent",
    "emit_chat_session_closed",
    "emit_chat_session_started",
    "voice_channel_id",
]
