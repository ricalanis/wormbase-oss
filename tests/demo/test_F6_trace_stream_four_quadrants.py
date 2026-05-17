"""F6 demo gate: the trace stream produces entries from all 4 quadrants.

Drives a representative slice of the demo (warmup + 1 mention + 1 file
drop + 1 PII text) and asserts every one of the 4 quadrant labels
appears at least once in the resulting ledger.

Quadrant enum (from `wormbase_ledger.entries.QUADRANT_VALUES`):
  - passive_deterministic
  - passive_probabilistic
  - active_deterministic
  - active_probabilistic
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from wormbase_channel_adapter.parser import ChatSentEvent
from wormbase_channel_adapter.writer import LedgerWriter
from wormbase_core.lurker import SlackLurker
from wormbase_core.reactivity import InfraEvent
from wormbase_core.service import build_worm_core
from wormbase_governance import PIIGate
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import QUADRANT_VALUES


@pytest.mark.asyncio
async def test_F6_trace_stream_four_quadrants() -> None:
    company_id = uuid4()
    ledger = InMemoryLedger()
    worm = await build_worm_core(
        ledger, company_id,
        domain_pack="saas",
        enable_lurker=False, enable_cloud_classifier=False,
    )

    # 1) channel mention via reactivity pipeline (active_deterministic +
    #    passive_deterministic via warmup gates)
    await worm.pipeline.process(
        {
            "type": "channel_message",
            "ts": datetime(2026, 4, 30, 12, tzinfo=UTC).timestamp(),
            "channel_id": "C-act1",
            "user_id": "U-stakeholder",
            "text": "@worm what do we measure for churn?",
            "message_id": "m-mention-1",
            "company_id": str(company_id),
        }
    )

    # 2) file drop -> drop_and_profile (active_deterministic + PEVR)
    file_event = InfraEvent(
        source="file_drop",
        payload={
            "filename": "subs.csv",
            "mimetype": "text/csv",
            "bytes_url": "https://files/x",
        },
        ts=datetime(2026, 4, 30, 12, 1, tzinfo=UTC),
        company_id=company_id,
        message_id="m-file-1",
        channel_id="C-act2",
        text="subs.csv",
    )
    await worm.drop_and_profile.on_file_drop(file_event)

    # 3) PII gate fire (passive_deterministic)
    pii_gate = PIIGate(ledger, company_id)
    await pii_gate.check(
        "leak ssn 123-45-6789", context={"source": "demo-act-3"}
    )

    # 4) Lurker chat_received write — passive_probabilistic.
    lurker = SlackLurker(
        ledger=ledger, company_id=company_id, pipeline=worm.pipeline,
        app_token="xapp-fake", bot_token="xoxb-fake",
    )
    await lurker._handle_event(  # noqa: SLF001
        {
            "channel": "C-lurker", "user": "U-watcher",
            "ts": "1745619400.0001", "client_msg_id": "m-lurk-1",
            "text": "non-mention observation", "type": "message",
        },
        body={}, kind="channel_message",
    )

    # 5) Channel-adapter writer for an outbound — active_probabilistic.
    writer = LedgerWriter(ledger, company_id)
    await writer.emit(ChatSentEvent(
        kind="chat_sent",
        session_id="s-demo-f6",
        event_id="e-demo-f6",
        ts=datetime(2026, 4, 30, 12, 2, tzinfo=UTC),
        text="here's what I found",
        in_reply_to="m-mention-1",
    ))

    # Now scrape all quadrant labels in the ledger.
    rows = await ledger.fetch(company_id)
    seen_quadrants = {r["quadrant"] for r in rows}

    # All 4 quadrants must be present. We do NOT lower the bar here —
    # the demo gate is "all 4 visible in the trace stream", and any
    # missing one means our four-quadrant story is incomplete.
    missing = set(QUADRANT_VALUES) - seen_quadrants
    assert not missing, (
        f"F6 GATE FAILED: missing quadrants in trace stream: "
        f"{sorted(missing)}. Saw: {sorted(seen_quadrants)}."
    )
