"""Chaos: voice-agent /v1/ask doesn't respond within 30s.

Failure mode
------------
The voice-agent's Kimi/Ollama HTTP call (``KimiOllamaClient.chat``)
blocks past the configured timeout — emulated by a fake client that
raises ``httpx.ReadTimeout``. This is the production failure shape
when the inference endpoint is overloaded or the VLAN is wedged.

Invariants the system MUST preserve
-----------------------------------
1. ``POST /v1/ask`` returns a 503 ``service unavailable`` response
   with a body that names the inference router as the root cause.
   The dashboard's voice floater renders the red banner from this.
2. NO half-state writes leak into the ledger: there is NO matching
   ``emit_chat_sent`` for the ``emit_chat_received`` that landed at
   the start of the call. The /trace view shows the inbound message
   without a fake outbound — honest UX.
3. The ``emit_chat_received`` PEVR cycle is fully complete (4 entries),
   not a half-cycle. The Kimi failure happens AFTER the chat_received
   entries land, not in the middle of writing them.
4. Voice-agent budget / session-state counters (``turn_counts``) do
   NOT increment for a turn that didn't produce an answer.

Failure-injection point
-----------------------
We inject a ``FakeKimi`` whose ``chat`` raises ``httpx.ReadTimeout``,
mirroring a production timeout. The voice-agent's /v1/ask handler
catches the exception (line 408-416 in app.py) and raises 503.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from wormbase_voice_agent.app import VoiceAppState, create_app
from wormbase_voice_agent.audio_store import AudioStore


WORMBASE_TENANT_NAMESPACE_HEX = "6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f"


class _TimingOutKimi:
    """Stand-in for ``KimiOllamaClient`` whose ``chat`` always times out.

    We raise ``httpx.ReadTimeout`` — the canonical "the server didn't
    respond in time" signal in async-httpx. The /v1/ask handler maps
    this to a 503 (line 408-416 of app.py).
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def chat(
        self,
        messages: Any,
        *,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        self.calls.append(messages)
        raise httpx.ReadTimeout(
            "voice-agent: /api/chat read timeout (30s)",
            request=httpx.Request("POST", "https://kimi.example/api/chat"),
        )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_ledger() -> Any:
    from wormbase_ledger import InMemoryLedger

    return InMemoryLedger()


@pytest.fixture
def baseworm_company_id() -> Any:
    from uuid import UUID, uuid5

    namespace = UUID(WORMBASE_TENANT_NAMESPACE_HEX)
    return uuid5(namespace, "baseworm")


def _make_app(
    *,
    ledger: Any,
    kimi: _TimingOutKimi,
    company_id: Any,
    audio_store: AudioStore | None = None,
) -> TestClient:
    state = VoiceAppState(
        ledger=ledger,
        kimi=kimi,  # type: ignore[arg-type]
        audio_store=audio_store or AudioStore("/tmp/voice-audio-chaos"),
        tenant_slug="baseworm",
        company_id=company_id,
    )
    app = create_app(state=state)
    return TestClient(app)


async def test_v1_ask_kimi_timeout_surfaces_503_no_half_state(
    in_memory_ledger: Any, baseworm_company_id: Any,
) -> None:
    """Kimi 30s timeout → 503; ledger has chat_received but no chat_sent."""
    kimi = _TimingOutKimi()
    client = _make_app(
        ledger=in_memory_ledger,
        kimi=kimi,
        company_id=baseworm_company_id,
    )

    rows_before = await in_memory_ledger.fetch(baseworm_company_id)

    resp = client.post(
        "/v1/ask",
        json={
            "transcript": "What was Q3 net revenue?",
            "person_id": "00000000-0000-0000-0000-000000000abc",
            "tenant_id": "baseworm",
        },
    )

    # Invariant 1: 503 service unavailable.
    assert resp.status_code == 503, resp.text
    body = resp.json()
    detail = body.get("detail", "")
    assert "inference router unavailable" in detail or "Kimi" in detail or "kimi" in detail.lower(), (
        f"503 body must name the inference router as the failure root; "
        f"got: {detail!r}"
    )

    # The Kimi call WAS attempted (we did reach the wire) — the failure
    # is honest, not a pre-call short-circuit.
    assert len(kimi.calls) == 1

    # Invariant 3: chat_received PEVR cycle landed (4 entries).
    rows_after = await in_memory_ledger.fetch(baseworm_company_id)
    delta = len(rows_after) - len(rows_before)
    chat_received_executes = [
        r for r in rows_after[len(rows_before):]
        if r["kind"] == "execute"
        and r["payload"].get("tool") in (
            "emit_chat_received",
            "channel_adapter.emit_chat_received",
            "voice_agent.emit_chat_received",
        )
    ]
    assert len(chat_received_executes) == 1, (
        "the inbound transcript must land its full chat_received PEVR "
        "cycle before the Kimi call is attempted"
    )
    # PEVR cycle = 4 entries; nothing more.
    assert delta == 4, (
        f"exactly one PEVR cycle (4 rows) must land for the inbound "
        f"transcript; got delta={delta}"
    )

    # Invariant 2: NO chat_sent landed. The /trace view will show the
    # inbound without a fake outbound — honest "we received but never
    # answered" state.
    chat_sent_executes = [
        r for r in rows_after[len(rows_before):]
        if r["kind"] == "execute"
        and r["payload"].get("tool") in (
            "emit_chat_sent",
            "channel_adapter.emit_chat_sent",
            "voice_agent.emit_chat_sent",
        )
    ]
    assert chat_sent_executes == [], (
        "no chat_sent entry must land when Kimi timed out — the "
        "dashboard renders an honest 'service unavailable' state from "
        "the missing receipt"
    )

    # Invariant 4: voice-agent's session-state turn count is NOT
    # incremented for a failed turn. The /v1/ask handler doesn't touch
    # turn_counts (only the ElevenLabs webhook does), so this is a
    # belt-and-braces check that the chaos didn't inadvertently spike
    # the bookkeeping.
    state = client.app.state.voice
    # turn_counts is only populated by the ElevenLabs webhook; for /v1/ask
    # it stays empty. Assert the bookkeeping didn't drift.
    assert state.turn_counts == {} or all(
        v == 0 for v in state.turn_counts.values()
    ), (
        "voice-agent turn counters must NOT increment on a failed /v1/ask"
    )
