"""L5 integration: 7-beat demo arc on the real wire, no flow-bypass.

Two layers, mirroring the C1 + C2 + C5 pattern:

1. **In-process pipeline drive** — runs every beat against the real
   reactivity pipeline + dispatcher chain (the same code paths the
   live channel-adapter would invoke). Asserts every expected
   wire-driven tool lands. This protects against regressions of the
   C1 + C2 fixes and the source-building flow chain.

2. **Live-wire smoke** — gated on ``WORMBASE_INTEGRATION_LIVE_SLACK=1``
   with a running compose stack + real Slack tokens; reproduces the
   demo end-to-end via files_upload_v2 + chat.postMessage and asserts
   the same expected_tools land. This is the gate the demo runs
   through.

PRD §10 — beats 3 (file drop) + 4 (Stripe mention) + 5 (cascade)
together synthesize ledger entries identical to those produced by the
real wire on a `files_upload_v2` + `chat.postMessage` pair.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest


pytestmark = pytest.mark.asyncio


_WIRE_DRIVEN_TOOLS = {
    "channel_adapter.emit_chat_received",
    "channel_adapter.emit_file_received",
    "emit_source_proposed",
    "emit_source_bronzed",
    "emit_source_silvered",
    "emit_source_golded",
    "emit_proactive_offer",
}


async def _write_chat_received(ledger, company_id, *, channel: str, message_id: str, text: str) -> dict:
    """Replicate channel-adapter's chat_received emit (PEVR cycle)."""
    args = {
        "channel_id": channel,
        "message_id": message_id,
        "sender_person": str(uuid4()),
        "text": text,
        "classification": "internal",
    }
    payload = {"tool": "channel_adapter.emit_chat_received", "args": args}
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(uuid4()),
            "reason": "test demo arc",
            "proposed_by": "test_demo_arc_live_wire",
        },
        execute_fn=lambda: {**payload, "result_ref": message_id},
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
        quadrant="active_probabilistic",
    )
    return payload


async def _write_file_received(
    ledger, company_id, *,
    channel: str, message_id: str, file_id: str,
    file_name: str, file_url: str, caption: str,
) -> dict:
    """Replicate channel-adapter's file_received emit (PEVR cycle)."""
    args = {
        "channel_id": channel,
        "message_id": message_id,
        "sender_person": str(uuid4()),
        "slack_file_id": file_id,
        "file_name": file_name,
        "mimetype": "text/csv",
        "file_size": 4096,
        "url_private": file_url,
        "classification": "internal",
        "caption_text": caption,
    }
    payload = {"tool": "channel_adapter.emit_file_received", "args": args}
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "file_received",
            "ref_id": str(uuid4()),
            "reason": "test demo arc",
            "proposed_by": "test_demo_arc_live_wire",
        },
        execute_fn=lambda: {**payload, "result_ref": file_id},
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
        quadrant="active_probabilistic",
    )
    return payload


async def test_demo_arc_in_process_pipeline(
    worm_core_integration, integration_ledger, integration_company_id,
) -> None:
    """End-to-end: chat + file rows + downstream flows fire every wire tool.

    Replicates the production sequence end-to-end against an in-memory
    ledger:

      1. Channel-adapter writes channel_adapter.emit_chat_received +
         channel_adapter.emit_file_received (the wire entries).
      2. Worm-core synthesizes events from those rows and runs them
         through pipeline.process → flow_dispatcher.
      3. Drop-and-profile + cascade chain produces emit_source_proposed
         + emit_source_bronzed/silvered/golded.
      4. Mentioned-in-conversation + relevance gate produces
         emit_proactive_offer.

    Asserts every expected wire-driven ledger entry lands. If C1
    (file_received emission), C2 (proactive offer dispatch), or any
    flow regresses, this test fails on the corresponding entry.
    """
    from pathlib import Path

    from wormbase_core.medallion import MedallionCascade
    from wormbase_core.service import (
        _synthesize_event,
        make_flow_dispatcher_with_proactivity,
    )

    worm = worm_core_integration
    ledger = integration_ledger
    company_id = integration_company_id

    cascade = MedallionCascade(ledger)
    dispatcher = make_flow_dispatcher_with_proactivity(
        worm.drop_and_profile,
        worm.credential_in_dm,
        worm.mentioned_in_conversation,
        company_id,
        cascade,
    )

    # The cascade reads from the URI; point at the real fixture so gold
    # can derive a non-empty aggregate. Live-wire mode fetches over HTTPS
    # via Slack's url_private; the cascade's bronze step handles either.
    csv_path = (
        Path(__file__).resolve().parents[2]
        / "apps/sim-harness/fixtures/sales-q3.csv"
    )
    assert csv_path.is_file(), f"fixture missing: {csv_path}"
    file_uri = f"file://{csv_path}"

    # --- Beat 3: file drop ------------------------------------------
    file_payload = await _write_file_received(
        ledger, company_id,
        channel="C0DEMO", message_id="100.000001", file_id="F-SALES-Q3",
        file_name="sales-q3.csv", file_url=file_uri, caption="sales-q3.csv",
    )
    file_event = _synthesize_event(
        "channel_adapter.emit_file_received", file_payload, company_id,
    )
    assert file_event is not None
    file_decision = await worm.pipeline.process(file_event)
    if file_decision is not None and getattr(file_decision, "should_react", False):
        await dispatcher(file_event, file_decision)

    # --- Beat 4: Stripe mention -------------------------------------
    chat_payload = await _write_chat_received(
        ledger, company_id,
        channel="C0DEMO",
        message_id="200.000001",
        text=(
            "we should also pull our Stripe data so the gross-net rec is clean"
        ),
    )
    chat_event = _synthesize_event(
        "channel_adapter.emit_chat_received", chat_payload, company_id,
    )
    assert chat_event is not None
    chat_decision = await worm.pipeline.process(chat_event)
    if chat_decision is not None and getattr(chat_decision, "should_react", False):
        await dispatcher(chat_event, chat_decision)

    # --- Assert: every expected wire-driven tool landed --------------
    rows = await ledger.fetch(company_id)
    seen = {
        r["payload"].get("tool")
        for r in rows
        if r["kind"] == "execute"
    }
    missing = _WIRE_DRIVEN_TOOLS - seen
    assert not missing, (
        f"missing wire-driven tools: {missing}. "
        f"saw: {sorted(seen)}"
    )


# ---------------------------------------------------------------------------
# Live-wire layer: real Slack + docker-compose. Gated behind an env flag.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("WORMBASE_INTEGRATION_LIVE_SLACK") != "1",
    reason=(
        "live Slack integration off by default. "
        "Set WORMBASE_INTEGRATION_LIVE_SLACK=1 with a running compose "
        "stack and SLACK_BOT_TOKEN_BASEWORM in env to enable."
    ),
)
async def test_demo_arc_produces_all_expected_entries() -> None:
    """End-to-end on the real wire. See module docstring."""
    from pathlib import Path

    from slack_sdk.web.async_client import AsyncWebClient

    from wormbase_channel_adapter.tenant import tenant_to_company_uuid
    from wormbase_ledger import Ledger

    bot_token = os.environ.get("SLACK_BOT_TOKEN_BASEWORM")
    if not bot_token:
        pytest.skip("SLACK_BOT_TOKEN_BASEWORM not set")

    channel_id = os.environ.get("WORMBASE_INTEGRATION_TEST_CHANNEL", "C0B06MCSLQ1")
    dsn = os.environ.get(
        "WORMBASE_LEDGER_DSN",
        "postgresql+asyncpg://wormbase:wormbase@localhost:5432/wormbase",
    )
    company_id = tenant_to_company_uuid("baseworm")

    csv_path = Path(__file__).resolve().parents[2] / "apps/sim-harness/fixtures/sales-q3.csv"
    if not csv_path.is_file():
        pytest.skip(f"fixture missing: {csv_path}")

    client = AsyncWebClient(token=bot_token)
    ledger = Ledger(dsn)
    started = datetime.now(UTC)

    try:
        # Beat 3: file drop
        upload_resp = await client.files_upload_v2(
            channel=channel_id,
            file=str(csv_path),
            title="sales-q3.csv",
        )
        upload_data = getattr(upload_resp, "data", upload_resp)  # type: ignore[assignment]
        assert upload_data.get("ok") is True, f"upload failed: {upload_data!r}"

        # Beat 4: Stripe mention
        chat_resp = await client.chat_postMessage(
            channel=channel_id,
            text=(
                "we should also pull our Stripe data so the gross-net rec is clean"
            ),
        )
        chat_data = getattr(chat_resp, "data", chat_resp)
        assert chat_data.get("ok") is True, f"postMessage failed: {chat_data!r}"

        # Wait up to 60s for the worm to finish processing.
        deadline = time.monotonic() + 60.0
        seen: set[str] = set()
        while time.monotonic() < deadline:
            rows = await ledger.fetch(company_id, until_ts=None)
            seen = {
                r["payload"].get("tool")
                for r in rows
                if r["kind"] == "execute" and r["ts"] >= started
            }
            if _WIRE_DRIVEN_TOOLS.issubset(seen):
                break
            time.sleep(2.0)

        missing = _WIRE_DRIVEN_TOOLS - seen
        assert not missing, (
            f"missing wire-driven tools after live demo: {missing}. "
            f"saw: {sorted(seen)}"
        )
    finally:
        await ledger.dispose()
