"""P10 — chat_received → process_map data product → /system-map projection.

The end-to-end conversation→gold flow:

    1. Three threaded chat_received entries with the same
       (asker, askee, topic) triplet land in the ledger (within window).
    2. ``RecurringQuestionProcessMapperReactivity`` fires on the third,
       proposing a ``data_product_proposed`` of ``kind="process_map"``.
    3. The dashboard's process_map projection (mirrored here as a fold)
       reads the entry and surfaces it as a row.
    4. An admin "confirms" by emitting ``data_product_generated`` on
       the same data_product_id (same path the dashboard uses).
    5. Re-reading the projection shows the row in ``status="generated"``.

This test is container-free — it uses ``InMemoryLedger`` and dispatches
through the real ``ReactivityRegistry``. The Playwright dashboard test
in ``apps/dashboard/tests/components/system-map/`` covers the
component-level rendering.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_reactivities import ReactivityRegistry
from wormbase_reactivities.process_mapper import (
    RecurringQuestionProcessMapperReactivity,
    _reset_history,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


BOB = UUID("aaaaaaaa-0000-0000-0000-0000000000b0")
CAROL = UUID("bbbbbbbb-0000-0000-0000-0000000000c0")
COMPANY_ID = UUID("00000000-0000-0000-0000-00000000a002")


def _chat_entry(
    seq: int,
    *,
    ts_epoch: float,
    thread_ts_epoch: float | None = None,
) -> dict:
    """Synthesize a chat_received execute envelope for a Bob→Carol churn ask."""
    thread_ts = thread_ts_epoch if thread_ts_epoch is not None else ts_epoch - 60
    return {
        "kind": "execute",
        "seq": seq,
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "channel_id": "C-revenue",
                "message_id": f"M-{seq}",
                "ts": str(ts_epoch),
                "thread_ts": str(thread_ts),
                "sender_person": str(BOB),
                "thread_parent_person": str(CAROL),
                "topic": "churn_rate",
                "text": "hey carol — what's the churn rate this week?",
            },
        },
    }


def _project_process_maps(rows: list[dict]) -> list[dict]:
    """Mirror of the dashboard's ``getProcessMaps`` projection.

    Folds emit_data_product_* rows; returns proposed/generated process_map
    artifacts ordered most-recent-first by proposed_at. Kept inline so
    this test stays a single dependency-light file (no dashboard-test
    runtime needed for L5 coverage).
    """
    products: dict[str, dict] = {}
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        dp_id = args.get("data_product_id")
        if not dp_id:
            continue
        if tool == "emit_data_product_proposed":
            if args.get("kind") != "process_map":
                continue
            products[dp_id] = {
                "data_product_id": dp_id,
                "name": args.get("name"),
                "kind": args.get("kind"),
                "status": "proposed",
                "parameters": args.get("parameters", {}),
                "proposed_at": row.get("ts"),
            }
        elif tool == "emit_data_product_generated":
            if dp_id in products:
                products[dp_id]["status"] = "generated"
        elif tool == "emit_data_product_archived":
            if dp_id in products:
                products[dp_id]["status"] = "archived"
    return list(products.values())


@pytest.fixture(autouse=True)
def _isolate_history():
    """Ensure module-level history store is reset around the e2e flow."""
    _reset_history(COMPANY_ID)
    yield
    _reset_history(COMPANY_ID)


async def test_process_map_e2e_proposal_then_admin_confirms() -> None:
    ledger = InMemoryLedger()

    # T0 — register the reactivity through the production path.
    reg = ReactivityRegistry(
        ledger=ledger,
        company_id=COMPANY_ID,
        now=lambda: datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
    )
    reg.register(RecurringQuestionProcessMapperReactivity(threshold=3))

    # T1 — three threaded chats from Bob to Carol about churn over a 12-day
    # window, landing inside the trailing 14-day recurrence horizon.
    bob_carol_chats = [
        _chat_entry(1, ts_epoch=1777334000.0),  # ~2026-04-28
        _chat_entry(2, ts_epoch=1777334100.0),
        _chat_entry(3, ts_epoch=1777334200.0),
    ]
    for entry in bob_carol_chats:
        await reg.dispatch(entry)

    rows = await ledger.fetch(COMPANY_ID)
    proposed = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_data_product_proposed"
    ]
    # Exactly one process_map proposal should have landed.
    assert len(proposed) == 1, (
        f"expected exactly one process_map proposal, got {len(proposed)}"
    )
    args = proposed[0]["payload"]["args"]
    assert args["kind"] == "process_map"
    pm_id = args["data_product_id"]
    pm_payload = args["parameters"]
    # Payload conforms to the spec'd shape.
    assert "nodes" in pm_payload
    assert "edges" in pm_payload
    assert pm_payload["window_end"] >= pm_payload["window_start"]
    assert any(
        e["from"] == str(BOB)
        and e["to"] == str(CAROL)
        and e["topic"] == "churn_rate"
        and e["frequency"] == 3
        for e in pm_payload["edges"]
    )

    # T2 — projection sees it as proposed.
    projected = _project_process_maps(rows)
    assert len(projected) == 1
    assert projected[0]["status"] == "proposed"
    assert projected[0]["data_product_id"] == pm_id

    # T3 — admin confirms via the dashboard path. Emit
    # data_product_generated for the same dp_id (same code path the
    # dashboard /api/data-products POST will exercise).
    from wormbase_core.data_product_actions import generate_data_product
    await generate_data_product(
        ledger,
        COMPANY_ID,
        data_product_id=UUID(pm_id),
        contents_uri=f"ledger://process-map/{pm_id}",
        content_hash="deadbeefcafe",
        kind="process_map",
        source_hashes=["chat-bob-carol-churn-window"],
        duration_ms=42,
        generated_by="dashboard-admin",
    )

    rows2 = await ledger.fetch(COMPANY_ID)
    projected2 = _project_process_maps(rows2)
    assert len(projected2) == 1
    assert projected2[0]["status"] == "generated"
    assert projected2[0]["data_product_id"] == pm_id


async def test_process_map_e2e_below_threshold_does_not_propose() -> None:
    """Two observations isn't enough — no process_map should land."""
    ledger = InMemoryLedger()
    reg = ReactivityRegistry(
        ledger=ledger,
        company_id=COMPANY_ID,
        now=lambda: datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
    )
    reg.register(RecurringQuestionProcessMapperReactivity(threshold=3))

    for i in range(1, 3):  # only 2 chats
        await reg.dispatch(_chat_entry(i, ts_epoch=1777334000.0 + i))

    rows = await ledger.fetch(COMPANY_ID)
    proposed = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_data_product_proposed"
    ]
    assert proposed == []
