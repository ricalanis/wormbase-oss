"""P13 — "Ask the worm" pipeline integration test.

End-to-end: a KPI-shaped transcript flows through the voice-agent's
``/v1/ask`` endpoint, which routes the question through worm-core's
real MCP server (Streamable HTTP), resolves the KPI, and returns a
citation pointing at the actual ``emit_kpi_node`` ledger row. The
dashboard floater would then render that as a clickable
``/trace?seq=N`` link.

The pipeline is:

  STT-stub (typed transcript) → /v1/ask → MCP query_kpis →
  MCP query_ledger → Kimi-stub → ledger writes (chat_received +
  chat_sent) → response envelope with KPI citation.

Test substitutes a stubbed STT (we feed a literal transcript, the
same shape Whisper would emit) and a stubbed Kimi (FakeKimi from the
voice-agent test conftest) so no external API keys are required.
The MCP server is the real :func:`build_mcp_server` from worm-core,
running on a dynamically-allocated port over Streamable HTTP.

Acceptance:

- ``citation_kind == "kpi_node"`` when the question matches a seeded
  KPI.
- ``ledger_seq`` is the seq of the most recent ``emit_kpi_node``
  execute row whose args.id matched the resolved KPI — verified by
  walking the ledger directly.
- ``hash_receipt`` is deterministic across two runs of the same
  inputs (C2).
- A non-KPI transcript falls back to the chat_sent citation cleanly.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import time
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from wormbase_ledger import InMemoryLedger
from wormbase_voice_agent.app import VoiceAppState, create_app
from wormbase_voice_agent.audio_store import AudioStore
from wormbase_voice_agent.mcp_client import StreamableHTTPMCPRouter

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ---------------------------------------------------------------------------
# Plumbing — copied from tests/integration/test_mcp_full_feature_surface.py
# so this test stays self-contained.
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@contextlib.asynccontextmanager
async def _running_mcp_server(ledger: Any, port: int, api_token: str) -> Any:
    from wormbase_core.mcp_server import build_mcp_server

    server = build_mcp_server(
        ledger=ledger, api_token=api_token, host="127.0.0.1", port=port,
    )
    task = asyncio.create_task(server.run_streamable_http_async())

    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline:
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.close()
            await w.wait_closed()
            break
        except OSError:
            await asyncio.sleep(0.05)
    else:
        task.cancel()
        raise TimeoutError(f"MCP server did not bind on :{port} within 5s")

    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class StubKimi:
    """Deterministic fake Kimi that records calls.

    The voice-agent forwards the system+user prompt straight through;
    we capture it so the test can assert that the KPI metadata block
    landed in the prompt — proving the MCP hit influenced the answer.
    """

    def __init__(self, *, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        self.calls.append(messages)
        return self.reply


# ---------------------------------------------------------------------------
# Ledger seeding
# ---------------------------------------------------------------------------


async def _seed_kpi(ledger: InMemoryLedger, company_id: UUID, *,
                    kpi_id: str, name: str) -> None:
    """Write one emit_kpi_node entry; use the seq for citation checks."""
    args = {
        "id": kpi_id,
        "name": name,
        "label": name,
        "formula": "sum(invoices.net_amount) - sum(refunds)",
        "unit": "USD",
        "domain_id": None,
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "kpi_node",
            "ref_id": kpi_id,
            "reason": "P13 integration seed",
            "proposed_by": "test",
        },
        execute_fn=lambda a=args: {
            "tool": "emit_kpi_node", "args": a, "result_ref": kpi_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "seeded", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _kpi_node_seq(
    ledger: InMemoryLedger, company_id: UUID, kpi_id: str,
) -> int | None:
    rows = await ledger.fetch(company_id)
    target = str(kpi_id)
    best: int | None = None
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        if payload.get("tool") != "emit_kpi_node":
            continue
        if str(payload.get("args", {}).get("id") or "") != target:
            continue
        seq = row.get("seq")
        if isinstance(seq, int) and (best is None or seq > best):
            best = seq
    return best


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_app(
    *,
    ledger: Any,
    kimi: StubKimi,
    company_id: UUID,
    mcp_url: str,
    api_token: str,
) -> TestClient:
    state = VoiceAppState(
        ledger=ledger,
        kimi=kimi,  # type: ignore[arg-type]
        audio_store=AudioStore("/tmp/voice-audio-p13"),
        tenant_slug="baseworm",
        company_id=company_id,
        mcp_router=StreamableHTTPMCPRouter(
            url=mcp_url, api_token=api_token, request_timeout_s=5.0,
        ),
    )
    app = create_app(state=state)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_kpi_question_routes_through_mcp_and_cites_kpi_node_seq() -> None:
    """Acceptance: KPI-shaped question → MCP hit → citation_kind=kpi_node."""
    api_token = "p13-test-token"
    ledger = InMemoryLedger()
    # Match the company_id derivation the voice-agent uses for the
    # tenant slug "baseworm" so the MCP server and the voice-agent
    # write to (and read from) the same ledger company partition.
    from wormbase_core.service import tenant_to_uuid
    company_id = tenant_to_uuid("baseworm")

    kpi_id = str(uuid4())
    await _seed_kpi(
        ledger, company_id, kpi_id=kpi_id, name="Q3 Net Revenue",
    )
    expected_seq = await _kpi_node_seq(ledger, company_id, kpi_id)
    assert expected_seq is not None, "fixture failed: no kpi_node seq"

    port = _free_port()
    async with _running_mcp_server(ledger, port, api_token):
        kimi = StubKimi(
            reply="Q3 Net Revenue — see the most recent ledger entry.",
        )
        client = _make_app(
            ledger=ledger,
            kimi=kimi,
            company_id=company_id,
            mcp_url=f"http://127.0.0.1:{port}/mcp",
            api_token=api_token,
        )

        r = await client.post(
            "/v1/ask",
            json={
                "transcript": "What's the current value of Q3 net revenue?",
                "tenant_id": "baseworm",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()

        # Citation points at the seeded emit_kpi_node — not the
        # chat_sent row the answer wrote.
        assert body["citation_kind"] == "kpi_node", body
        assert body["ledger_seq"] == expected_seq, body
        assert body["kpi"]["id"] == kpi_id
        assert body["kpi"]["name"] == "Q3 Net Revenue"

        # The KPI metadata landed in Kimi's prompt — proves the MCP hit
        # actually influenced the answer rather than being decorative.
        assert kimi.calls, "Kimi was never called"
        joined_system = "\n".join(
            m["content"] for m in kimi.calls[0]
            if m.get("role") == "system" and isinstance(m.get("content"), str)
        )
        assert "Q3 Net Revenue" in joined_system
        assert kpi_id in joined_system

        # Hash receipt determinism — same transcript+answer+model → same digest.
        r2 = await client.post(
            "/v1/ask",
            json={
                "transcript": "What's the current value of Q3 net revenue?",
                "tenant_id": "baseworm",
            },
        )
        assert r2.status_code == 200
        assert r2.json()["hash_receipt"] == body["hash_receipt"]


async def test_non_kpi_question_falls_back_to_chat_sent_citation() -> None:
    """Greeting-shaped transcripts skip MCP and cite the chat_sent row."""
    api_token = "p13-test-token-2"
    ledger = InMemoryLedger()
    from wormbase_core.service import tenant_to_uuid
    company_id = tenant_to_uuid("baseworm")

    port = _free_port()
    async with _running_mcp_server(ledger, port, api_token):
        kimi = StubKimi(reply="Hello there.")
        client = _make_app(
            ledger=ledger,
            kimi=kimi,
            company_id=company_id,
            mcp_url=f"http://127.0.0.1:{port}/mcp",
            api_token=api_token,
        )

        r = await client.post(
            "/v1/ask",
            json={"transcript": "hi worm", "tenant_id": "baseworm"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Non-KPI transcript: no MCP routing, citation falls back to
        # chat_sent. The seq still points at a real ledger row (the
        # chat_sent execute we just wrote) so /trace?seq=N still works.
        assert body["citation_kind"] == "chat_sent"
        assert body["ledger_seq"] is not None and body["ledger_seq"] > 0
        assert body.get("kpi") is None


async def test_kpi_question_with_unknown_kpi_falls_back_cleanly() -> None:
    """A KPI-shaped question with no ledger match degrades to chat_sent."""
    api_token = "p13-test-token-3"
    ledger = InMemoryLedger()
    from wormbase_core.service import tenant_to_uuid
    company_id = tenant_to_uuid("baseworm")

    # Seed a Q3-shaped KPI so query_kpis has something to return, but
    # ask about churn — the fuzzy match should fail and the surface
    # falls back to chat_sent without erroring.
    await _seed_kpi(
        ledger, company_id, kpi_id=str(uuid4()), name="Q3 Net Revenue",
    )

    port = _free_port()
    async with _running_mcp_server(ledger, port, api_token):
        kimi = StubKimi(reply="I don't have that one yet.")
        client = _make_app(
            ledger=ledger,
            kimi=kimi,
            company_id=company_id,
            mcp_url=f"http://127.0.0.1:{port}/mcp",
            api_token=api_token,
        )
        r = await client.post(
            "/v1/ask",
            json={"transcript": "what is our churn rate this month?", "tenant_id": "baseworm"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["citation_kind"] == "chat_sent"
        assert body.get("kpi") is None
