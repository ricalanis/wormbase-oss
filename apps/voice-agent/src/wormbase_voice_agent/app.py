"""FastAPI service exposing the ElevenLabs custom-LLM webhook surface.

Endpoints
---------

``POST /webhook/elevenlabs``
    Per-turn custom-LLM hook. Receives the OpenAI-shaped messages array
    from ElevenLabs, writes a ``chat_received`` ledger entry, routes the
    prompt through Kimi (Ollama), writes a ``chat_sent`` entry, and
    returns the OpenAI-shaped completion ElevenLabs needs to render TTS.

``POST /webhook/elevenlabs/session-start``
    Fires when a call begins. Pre-warms Kimi context (a tiny ping so the
    first turn doesn't pay cold-start latency) and writes a session
    opener entry. The pre-warm runs in the background; the response
    returns ``{"ok": true}`` immediately.

``POST /webhook/elevenlabs/session-end``
    Fires when the call ends. Writes a ``chat_session_closed`` entry
    pointing at any post-call recording / transcript URLs ElevenLabs
    sends along.

``POST /v1/ask``
    Dashboard-facing "Ask the worm" entrypoint (W3.A12 of the
    production-hardening plan). Accepts ``{transcript, person_id,
    tenant_id}``, runs the same Kimi pipeline the ElevenLabs webhook
    runs (chat_received → fetch context → Kimi → chat_sent), and
    returns ``{answer, hash_receipt, ledger_seq}``. The ``hash_receipt``
    is deterministic — sha256 of the canonical
    ``{transcript, answer, model}`` triple — so the same question over
    the same data yields the same receipt. ``ledger_seq`` points at the
    seq of the ``chat_sent`` execute entry for trace linkage.

``GET /healthz``
    Compose-style liveness check. Returns ``{"ok": true}``.

The HTTP layer is intentionally thin. All ledger and LLM logic lives in
:mod:`audit` and :mod:`elevenlabs`; this module wires them.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from wormbase_voice_agent.audio_store import AudioStore
from wormbase_voice_agent.audit import (
    emit_chat_received,
    emit_chat_sent,
    emit_chat_session_closed,
    emit_chat_session_started,
)
from wormbase_voice_agent.elevenlabs import (
    DEFAULT_KIMI_MODEL,
    KimiOllamaClient,
    LLMWebhookRequest,
    SessionWebhookRequest,
    build_voice_prompt,
    fetch_recent_conversation_context,
    openai_chat_response,
)
from wormbase_voice_agent.mcp_client import (
    KPIHit,
    MCPRouter,
    build_default_router,
    looks_like_kpi_question,
)
from wormbase_core import silent_mode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tenant resolution — mirror channel-adapter to keep company-id consistent.
# ---------------------------------------------------------------------------

_WORMBASE_TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")


def _tenant_to_company_uuid(slug: str) -> UUID:
    if not slug:
        raise ValueError("tenant slug must be non-empty")
    return uuid5(_WORMBASE_TENANT_NAMESPACE, slug.strip().lower())


# ---------------------------------------------------------------------------
# App-state factory — one ledger + Kimi + audio store per process.
# ---------------------------------------------------------------------------


class VoiceAppState:
    """Per-process service dependencies.

    Held on ``app.state.voice``; tests overwrite it with in-memory fakes.
    """

    def __init__(
        self,
        *,
        ledger: Any,
        kimi: KimiOllamaClient,
        audio_store: AudioStore,
        tenant_slug: str,
        company_id: UUID | None = None,
        mcp_router: MCPRouter | None = None,
    ) -> None:
        self.ledger = ledger
        self.kimi = kimi
        self.audio_store = audio_store
        self.tenant_slug = tenant_slug
        self.company_id = company_id or _tenant_to_company_uuid(tenant_slug)
        # P13 — KPI lookup via worm-core's MCP server. Optional: the
        # /v1/ask endpoint degrades to chat-only when ``mcp_router`` is
        # None (no API key in env, MCP server unreachable, etc.).
        self.mcp_router = mcp_router
        # Bookkeeping for /session-end: how many turns ran for each session.
        self.turn_counts: dict[str, int] = {}
        self.session_started_at: dict[str, datetime] = {}


def _build_default_state() -> VoiceAppState:
    """Build production-shaped state from environment variables.

    Imported here (not at module load) so that pure unit tests of the
    helper modules don't need ``WORMBASE_LEDGER_DSN`` to be set.
    """
    from wormbase_ledger import Ledger  # local import: keeps tests cheap

    dsn = os.environ.get("WORMBASE_LEDGER_DSN")
    if not dsn:
        raise RuntimeError(
            "WORMBASE_LEDGER_DSN must be set to run the voice-agent service"
        )
    tenant_slug = os.environ.get("WORMBASE_TENANT_ID", "baseworm")
    return VoiceAppState(
        ledger=Ledger(dsn),
        kimi=KimiOllamaClient(),
        audio_store=AudioStore(),
        tenant_slug=tenant_slug,
        mcp_router=build_default_router(),
    )


# ---------------------------------------------------------------------------
# FastAPI app factory
# ---------------------------------------------------------------------------


def create_app(state: VoiceAppState | None = None) -> FastAPI:
    """Build the FastAPI app.

    Pass ``state`` to inject test fakes; omit it for the real DSN-backed
    service. The lifespan hook lazily builds default state if none was
    provided so ``uvicorn wormbase_voice_agent.app:app`` works.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        if not hasattr(app.state, "voice") or app.state.voice is None:
            app.state.voice = _build_default_state()
        try:
            yield
        finally:
            ledger = getattr(app.state.voice, "ledger", None)
            dispose = getattr(ledger, "dispose", None)
            if callable(dispose):
                try:
                    await dispose()
                except Exception:  # noqa: BLE001
                    logger.exception("voice-agent: ledger.dispose failed")

    app = FastAPI(title="wormbase-voice-agent", lifespan=lifespan)
    if state is not None:
        app.state.voice = state

    # ------------------------------------------------------------------
    # /healthz
    # ------------------------------------------------------------------

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "service": "wormbase-voice-agent"}

    # ------------------------------------------------------------------
    # /webhook/elevenlabs — per-turn custom-LLM hook
    # ------------------------------------------------------------------

    @app.post("/webhook/elevenlabs")
    async def elevenlabs_llm(req: LLMWebhookRequest) -> JSONResponse:
        s: VoiceAppState = app.state.voice
        user_text = req.latest_user_text()
        if not user_text:
            raise HTTPException(
                status_code=400, detail="webhook body has no user message"
            )
        session_id = req.session_key()
        caller_id = req.caller_key()

        # 1) Persist the inbound utterance. Audio bytes are not part of
        #    the per-turn webhook (ElevenLabs renders them upstream); the
        #    audio_ref placeholder will be filled by /session-end if the
        #    provider sends a recording_url. For per-turn audio (when we
        #    add streaming pre-emission), pass a real path here.
        in_message_id = f"el-in-{uuid.uuid4().hex[:12]}"
        try:
            received = await emit_chat_received(
                s.ledger,
                company_id=s.company_id,
                session_id=session_id,
                message_id=in_message_id,
                text=user_text,
                caller_id=caller_id,
                audio_ref=None,
            )
        except Exception:  # noqa: BLE001
            logger.exception("voice-agent: emit_chat_received failed")
            raise HTTPException(
                status_code=500, detail="ledger write failed for chat_received"
            ) from None

        # 2) Build prompt with recent conversation lake context.
        history = await fetch_recent_conversation_context(
            s.ledger, s.company_id, limit=20,
        )
        prompt = build_voice_prompt(user_text, history=history)

        # 3) Call Kimi (with fallback to gpt-oss).
        try:
            reply_text = await s.kimi.chat(prompt)
        except Exception:  # noqa: BLE001
            logger.exception("voice-agent: kimi call failed")
            reply_text = (
                "I'm having trouble reaching my reasoning model right now. "
                "Please try again in a moment."
            )

        # Silent mode: replace the outbound emit + response with a reply_suppressed
        # entry. Bookkeeping (turn_counts) still runs — the turn happened.
        if silent_mode.is_silent_mode_enabled():
            await silent_mode.record_suppressed(
                s.ledger,
                company_id=s.company_id,
                surface="voice",
                tool="elevenlabs_llm",
                args={
                    "session_id": session_id,
                    "caller_id": caller_id,
                    "user_text": user_text,
                    "reply_text": reply_text,
                },
                presence_reason="voice_utterance",
            )
            s.turn_counts[session_id] = s.turn_counts.get(session_id, 0) + 1
            return JSONResponse(
                openai_chat_response(text="", model=DEFAULT_KIMI_MODEL)
            )

        # 4) Persist the outbound reply.
        out_message_id = f"el-out-{uuid.uuid4().hex[:12]}"
        try:
            await emit_chat_sent(
                s.ledger,
                company_id=s.company_id,
                session_id=session_id,
                message_id=out_message_id,
                text=reply_text,
                in_reply_to=in_message_id,
                audio_ref=None,
                attribution={
                    "model": DEFAULT_KIMI_MODEL,
                    "received_chat_ids": [str(uid) for uid in received.entry_ids],
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("voice-agent: emit_chat_sent failed")
            # Still return the reply to ElevenLabs — the user already
            # heard a delay; better to ship an answer than to 500.

        # 5) Bookkeeping.
        s.turn_counts[session_id] = s.turn_counts.get(session_id, 0) + 1

        # 6) Return OpenAI-shaped completion.
        return JSONResponse(
            openai_chat_response(text=reply_text, model=DEFAULT_KIMI_MODEL)
        )

    # ------------------------------------------------------------------
    # /webhook/elevenlabs/session-start
    # ------------------------------------------------------------------

    @app.post("/webhook/elevenlabs/session-start")
    async def session_start(req: SessionWebhookRequest) -> dict[str, Any]:
        s: VoiceAppState = app.state.voice
        session_id = req.session_key()
        caller_id = req.caller_key()

        s.session_started_at[session_id] = datetime.now(UTC)
        s.turn_counts[session_id] = 0

        # Best-effort ledger write.
        try:
            await emit_chat_session_started(
                s.ledger,
                company_id=s.company_id,
                session_id=session_id,
                caller_id=caller_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("voice-agent: emit_chat_session_started failed")

        # Fire-and-forget Kimi pre-warm so the first turn isn't cold.
        async def _prewarm() -> None:
            try:
                await s.kimi.chat(
                    [
                        {"role": "system", "content": "respond with only the word READY"},
                        {"role": "user", "content": "ping"},
                    ],
                )
            except Exception:  # noqa: BLE001
                logger.warning("voice-agent: kimi pre-warm failed (non-fatal)")

        asyncio.create_task(_prewarm())
        return {"ok": True, "session_id": session_id}

    # ------------------------------------------------------------------
    # /webhook/elevenlabs/session-end
    # ------------------------------------------------------------------

    @app.post("/webhook/elevenlabs/session-end")
    async def session_end(req: SessionWebhookRequest) -> dict[str, Any]:
        s: VoiceAppState = app.state.voice
        session_id = req.session_key()
        started_at = s.session_started_at.pop(session_id, None)
        ended_at = datetime.now(UTC)
        turn_count = s.turn_counts.pop(session_id, 0)

        try:
            await emit_chat_session_closed(
                s.ledger,
                company_id=s.company_id,
                session_id=session_id,
                started_at=started_at,
                ended_at=ended_at,
                turn_count=turn_count,
                full_recording_url=req.recording_url,
                transcript_url=req.transcript_url,
            )
        except Exception:  # noqa: BLE001
            logger.exception("voice-agent: emit_chat_session_closed failed")

        return {"ok": True, "session_id": session_id, "turns": turn_count}

    # ------------------------------------------------------------------
    # /v1/ask — dashboard "Ask the worm" entrypoint (W3.A12)
    # ------------------------------------------------------------------

    @app.post("/v1/ask")
    async def ask_the_worm(req: AskRequest) -> JSONResponse:
        """Run a single dashboard-initiated question through the voice
        agent's inference pipeline and return ``{answer, hash_receipt,
        ledger_seq}``.

        The pipeline mirrors the ElevenLabs per-turn handler so a question
        asked from the dashboard floater lands in the same conversation
        lake as a question asked over the phone — both produce
        ``chat_received`` / ``chat_sent`` rows tagged ``modality="voice"``.

        ``hash_receipt`` is deterministic: sha256 over the canonical JSON
        of ``{transcript, answer, model}``. Same question against the
        same data → same receipt — hash-stable, the way the design doc
        promises (C2 of the on-thesis rubric). ``ledger_seq`` is the seq
        of the ``chat_sent`` execute entry, suitable for ``/trace?seq=N``
        deep links.
        """
        s: VoiceAppState = app.state.voice
        transcript = (req.transcript or "").strip()
        if not transcript:
            raise HTTPException(
                status_code=400,
                detail="transcript is required and must be non-empty",
            )

        # Resolve the company id. The dashboard sends the tenant slug
        # (e.g. "baseworm") as ``tenant_id``; fall back to the configured
        # tenant when omitted so the surface is forgiving for the demo.
        tenant_slug = (req.tenant_id or s.tenant_slug or "").strip().lower()
        try:
            company_id = (
                _tenant_to_company_uuid(tenant_slug)
                if tenant_slug
                else s.company_id
            )
        except ValueError:
            raise HTTPException(
                status_code=400, detail="tenant_id is invalid"
            ) from None

        # Synthesize a stable session id per (tenant, person) pair so the
        # dashboard floater's history threads across reloads. The id is
        # deterministic — fine for ledger linkage and consistent with the
        # voice-channel id convention.
        person_token = (req.person_id or "anonymous").strip() or "anonymous"
        session_id = f"dashboard-{tenant_slug or 'default'}-{person_token}"

        in_message_id = f"dash-in-{uuid.uuid4().hex[:12]}"
        try:
            received = await emit_chat_received(
                s.ledger,
                company_id=company_id,
                session_id=session_id,
                message_id=in_message_id,
                text=transcript,
                caller_id=person_token,
                audio_ref=None,
            )
        except Exception:  # noqa: BLE001
            logger.exception("voice-agent: emit_chat_received failed (/v1/ask)")
            raise HTTPException(
                status_code=503,
                detail="ledger write failed for chat_received",
            ) from None

        # P13 — KPI questions take a side-trip through worm-core's MCP
        # server before we hit Kimi. The MCP call returns the canonical
        # KPI metadata + the ledger seq of the most recent computation;
        # we inject the metadata into Kimi's system prompt so the worm
        # answers with grounded numbers and we cite the MCP-resolved
        # seq instead of the chat_sent seq for /trace?seq=N.
        kpi_hit: KPIHit | None = None
        if s.mcp_router is not None and looks_like_kpi_question(transcript):
            try:
                kpi_hit = await s.mcp_router.lookup_kpi(
                    company_id=tenant_slug or s.tenant_slug,
                    transcript=transcript,
                )
            except Exception:  # noqa: BLE001
                # The router itself catches and logs; this is a paranoid
                # backstop so a misbehaving fake doesn't 503 the surface.
                logger.warning(
                    "voice-agent: MCP router raised for KPI lookup",
                    exc_info=True,
                )
                kpi_hit = None

        history = await fetch_recent_conversation_context(
            s.ledger, company_id, limit=20,
        )
        extra_system = _kpi_hit_system_block(kpi_hit) if kpi_hit else None
        prompt = build_voice_prompt(
            transcript, history=history, extra_system=extra_system,
        )

        try:
            answer_text = await s.kimi.chat(prompt)
        except Exception:  # noqa: BLE001
            logger.exception("voice-agent: kimi call failed (/v1/ask)")
            raise HTTPException(
                status_code=503,
                detail=(
                    "inference router unavailable — voice-agent could not "
                    "reach the Kimi/Ollama brain"
                ),
            ) from None

        out_message_id = f"dash-out-{uuid.uuid4().hex[:12]}"
        try:
            sent = await emit_chat_sent(
                s.ledger,
                company_id=company_id,
                session_id=session_id,
                message_id=out_message_id,
                text=answer_text,
                in_reply_to=in_message_id,
                audio_ref=None,
                attribution={
                    "model": DEFAULT_KIMI_MODEL,
                    "surface": "dashboard.voice_floater",
                    "received_chat_ids": [
                        str(uid) for uid in received.entry_ids
                    ],
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("voice-agent: emit_chat_sent failed (/v1/ask)")
            raise HTTPException(
                status_code=503,
                detail="ledger write failed for chat_sent",
            ) from None

        # Resolve the seq for the citation link.
        #
        # When MCP returned a KPI hit with a real computation seq, cite
        # THAT — the dashboard's /trace?seq=N link should land on the
        # KPI's most recent emit_kpi_node entry, not the chat-sent row.
        # When MCP didn't fire (non-KPI question, MCP unreachable), the
        # citation falls back to the chat_sent execute row so every
        # answer still resolves to a real ledger entry.
        if kpi_hit and kpi_hit.ledger_seq is not None:
            ledger_seq: int | None = kpi_hit.ledger_seq
            citation_kind = "kpi_node"
        else:
            ledger_seq = await _resolve_execute_seq(
                s.ledger, company_id, sent.entry_ids[1],
            )
            citation_kind = "chat_sent"

        # Deterministic receipt — sha256 over canonical JSON of the inputs
        # and outputs that define the answer. Independent of the ledger
        # entry hash (which mixes in entry_id + ts and is therefore not
        # stable across replays).
        hash_receipt = compute_hash_receipt(
            transcript=transcript,
            answer=answer_text,
            model=DEFAULT_KIMI_MODEL,
        )

        envelope: dict[str, Any] = {
            "answer": answer_text,
            "hash_receipt": hash_receipt,
            "ledger_seq": ledger_seq,
            "model": DEFAULT_KIMI_MODEL,
            "session_id": session_id,
            "citation_kind": citation_kind,
        }
        if kpi_hit is not None:
            envelope["kpi"] = {
                "id": kpi_hit.kpi_id,
                "name": kpi_hit.name,
                "formula": kpi_hit.formula,
                "unit": kpi_hit.unit,
                "domain_id": kpi_hit.domain_id,
                "owner_position": kpi_hit.owner_position,
                "status": kpi_hit.status,
            }
        return JSONResponse(envelope)

    return app


async def _resolve_execute_seq(
    ledger: Any, company_id: UUID, execute_entry_id: UUID,
) -> int | None:
    """Return the ``seq`` of the ledger row whose ``entry_id`` matches.

    Returns ``None`` if the row can't be found (defensive — ledger
    backends always return what we just wrote, but we don't 500 on a
    cold projection lookup).
    """
    try:
        rows = await ledger.fetch(company_id)
    except Exception:  # noqa: BLE001
        logger.warning("voice-agent: ledger.fetch failed during /v1/ask seq lookup")
        return None
    target = str(execute_entry_id)
    for row in rows:
        if str(row.get("entry_id")) == target:
            seq = row.get("seq")
            if isinstance(seq, int):
                return seq
    return None


def _kpi_hit_system_block(hit: KPIHit) -> str:
    """Render a KPIHit as an extra system-prompt block.

    Kimi gets the canonical KPI metadata so its answer is grounded in
    what the ledger actually says — name, formula, unit, owner. The
    citation seq is NOT injected here (we don't trust Kimi to repeat
    it verbatim); the seq is appended by the response envelope and
    rendered by the dashboard floater as a clickable link.
    """
    lines: list[str] = [
        "Context: the user's question is a KPI lookup. The most recent "
        "ledger entry resolved by the MCP read tool query_kpis is:",
        f"- Name: {hit.name}",
        f"- KPI id: {hit.kpi_id}",
    ]
    if hit.formula:
        lines.append(f"- Formula: {hit.formula}")
    if hit.unit:
        lines.append(f"- Unit: {hit.unit}")
    if hit.owner_position:
        lines.append(f"- Owner position: {hit.owner_position}")
    if hit.status:
        lines.append(f"- Status: {hit.status}")
    if hit.ledger_seq is not None:
        lines.append(f"- Most recent computation: ledger row {hit.ledger_seq}")
    lines.append(
        "Answer concisely with the KPI name and any deterministic value "
        "the ledger provides. Do not invent numbers.",
    )
    return "\n".join(lines)


def compute_hash_receipt(
    *, transcript: str, answer: str, model: str,
) -> str:
    """sha256 hex of canonical JSON over the answer-defining triple.

    Deterministic by construction: same ``transcript`` + same ``answer``
    + same ``model`` → same digest. Independent of the ledger's chained
    hash (which depends on uuid4 entry_ids and timestamps).
    """
    payload = json.dumps(
        {"transcript": transcript, "answer": answer, "model": model},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class AskRequest(BaseModel):
    """``POST /v1/ask`` body — dashboard floater asks the worm a question."""

    model_config = ConfigDict(extra="allow")

    transcript: str = Field(..., description="The user's question text.")
    person_id: str | None = Field(
        default=None,
        description=(
            "Dashboard-resolved Person id (UUID string) or any stable "
            "actor token. Used as the caller key for ledger attribution."
        ),
    )
    tenant_id: str | None = Field(
        default=None,
        description=(
            "Tenant slug (e.g. 'baseworm'). When omitted, falls back to "
            "the voice-agent's configured WORMBASE_TENANT_ID."
        ),
    )


# Default ASGI app for `uvicorn wormbase_voice_agent.app:app`.
app = create_app()


__all__ = [
    "AskRequest",
    "VoiceAppState",
    "app",
    "compute_hash_receipt",
    "create_app",
]
