"""Tests for the demo-day knowledge-ramp gauge projection (P2).

Covers the contract spelled out in
``docs/superpowers/specs/2026-04-29-demo-day-prd.md`` §7 P2:

  * Three named axes (ontology / conversational / relational).
  * Each axis is an integer count over the ledger.
  * Each axis carries a per-minute sparkline of the last 60 minutes
    capped at 100 contributing entries.
  * Empty axes return ``count=0`` plus a zero-vector sparkline (the
    dashboard renders ``0`` honestly; no fixture fallback).
  * Two replays with identical row streams produce byte-identical
    gauge values (replay-determinism, PRD §7 footnote 8).

The tests are pure-function tests over a hand-built ledger row stream
— no DB, no fixtures, no I/O. Determinism and empty-state are the
only invariants that matter; the dashboard wiring is exercised by the
TS-side tests under ``apps/dashboard/tests/components/``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from wormbase_core.projections.knowledge_ramp import (
    GAUGE_AXES,
    SPARKLINE_BUCKETS,
    SPARKLINE_MAX_ENTRIES,
    KnowledgeRampGauges,
    TRACE_FILTER_KIND,
    compute_knowledge_ramp_gauges,
)


COMPANY_ID = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)


def _execute_row(
    seq: int,
    *,
    tool: str,
    args: dict[str, Any] | None = None,
    ts: datetime | None = None,
    company_id: UUID = COMPANY_ID,
) -> dict[str, Any]:
    """Build a minimal ledger row in the canonical PEVR ``execute`` shape."""
    return {
        "seq": seq,
        "company_id": company_id,
        "ts": ts if ts is not None else NOW,
        "kind": "execute",
        "payload": {"tool": tool, "args": args or {}},
    }


def _kind_row(
    seq: int,
    *,
    kind: str,
    payload: dict[str, Any] | None = None,
    ts: datetime | None = None,
    company_id: UUID = COMPANY_ID,
) -> dict[str, Any]:
    """Build a minimal ledger row with a direct ``kind=<...>`` shape."""
    return {
        "seq": seq,
        "company_id": company_id,
        "ts": ts if ts is not None else NOW,
        "kind": kind,
        "payload": payload or {},
    }


# ---------------------------------------------------------------------------
# Empty-state contract
# ---------------------------------------------------------------------------


def test_empty_ledger_returns_zero_per_axis() -> None:
    out = compute_knowledge_ramp_gauges([], company_id=COMPANY_ID, now=NOW)
    assert isinstance(out, KnowledgeRampGauges)
    assert out.company_id == str(COMPANY_ID)
    assert len(out.gauges) == 3
    for axis in GAUGE_AXES:
        g = out.by_axis(axis)
        assert g.count == 0
        assert g.last_seq == 0
        assert g.last_ts is None
        assert g.sparkline == [0] * SPARKLINE_BUCKETS
        # Trace filter is always non-empty so the dashboard's deep-link
        # never sends the user to an unfiltered /trace by accident.
        assert g.trace_filter == TRACE_FILTER_KIND[axis]


def test_empty_axis_renders_zero_alongside_populated_axis() -> None:
    """One axis populated, two axes empty — empties stay honestly zero."""
    rows = [
        _execute_row(1, tool="emit_chat_received", args={"channel_id": "C1"}),
        _execute_row(2, tool="channel_adapter.emit_chat_received", args={}),
    ]
    out = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    assert out.by_axis("conversational").count == 2
    assert out.by_axis("ontology").count == 0
    assert out.by_axis("relational").count == 0
    assert out.by_axis("ontology").sparkline == [0] * SPARKLINE_BUCKETS
    assert out.by_axis("relational").sparkline == [0] * SPARKLINE_BUCKETS


# ---------------------------------------------------------------------------
# Per-axis counting
# ---------------------------------------------------------------------------


def test_ontology_counts_concept_proposed_and_confirmed() -> None:
    rows = [
        _execute_row(1, tool="emit_concept_proposed", args={"concept_id": str(uuid4())}),
        _execute_row(2, tool="emit_concept_confirmed", args={"concept_id": str(uuid4())}),
        _kind_row(3, kind="concept_proposed", payload={"concept_id": str(uuid4())}),
        # Should NOT count toward ontology — it's a chat row.
        _execute_row(4, tool="emit_chat_received"),
    ]
    out = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    assert out.by_axis("ontology").count == 3


def test_conversational_counts_lurker_and_channel_adapter_paths() -> None:
    """Both write paths (lurker ``emit_chat_received`` and the channel-adapter
    ``channel_adapter.emit_chat_received``) fold into the same gauge."""
    rows = [
        _execute_row(1, tool="emit_chat_received", args={"channel_id": "C1"}),
        _execute_row(2, tool="channel_adapter.emit_chat_received", args={}),
        # Direct kind shape used by the in-memory ledger in some test paths.
        _kind_row(3, kind="chat_received"),
        # Sender-side messages must not double-count the gauge.
        _execute_row(4, tool="emit_chat_sent"),
    ]
    out = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    assert out.by_axis("conversational").count == 3


def test_relational_counts_kpi_growth_entries() -> None:
    rows = [
        _execute_row(1, tool="emit_kpi_proposed", args={"name": "ARR"}),
        _execute_row(2, tool="emit_kpi_node", args={"id": "n1"}),
        # Aspirational PRD names — should also count when they appear.
        _execute_row(3, tool="emit_kpi_node_added", args={"id": "n2"}),
        _execute_row(4, tool="emit_kpi_edge_added", args={"from": "n1", "to": "n2"}),
        # Unrelated tool must not contribute.
        _execute_row(5, tool="emit_chat_received"),
    ]
    out = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    assert out.by_axis("relational").count == 4


# ---------------------------------------------------------------------------
# Sparkline shape + windowing
# ---------------------------------------------------------------------------


def test_sparkline_is_60_buckets_per_axis() -> None:
    out = compute_knowledge_ramp_gauges([], company_id=COMPANY_ID, now=NOW)
    for axis in GAUGE_AXES:
        assert len(out.by_axis(axis).sparkline) == 60


def test_sparkline_buckets_one_per_minute_in_last_hour() -> None:
    """Two chat events 5 and 25 minutes ago land in distinct buckets."""
    rows = [
        _execute_row(
            1,
            tool="emit_chat_received",
            ts=NOW - timedelta(minutes=25),
        ),
        _execute_row(
            2,
            tool="emit_chat_received",
            ts=NOW - timedelta(minutes=5),
        ),
    ]
    out = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    sl = out.by_axis("conversational").sparkline
    # Newest bucket is index 59 → 5min ago lands at index 54.
    # 25min ago lands at index 34. Both should be 1.
    assert sl[54] == 1
    assert sl[34] == 1
    assert sum(sl) == 2


def test_sparkline_drops_entries_older_than_window() -> None:
    """Entries older than 60 minutes still count toward ``count`` but
    don't contribute to the sparkline (PRD §7: sparkline is the last 60min)."""
    rows = [
        _execute_row(
            1,
            tool="emit_chat_received",
            ts=NOW - timedelta(hours=2),
        ),
        _execute_row(
            2,
            tool="emit_chat_received",
            ts=NOW - timedelta(minutes=30),
        ),
    ]
    out = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    g = out.by_axis("conversational")
    # Cumulative count includes both, sparkline only the in-window one.
    assert g.count == 2
    assert sum(g.sparkline) == 1


def test_sparkline_capped_at_100_entries() -> None:
    """When >100 entries fall in the window, only the most-recent 100 contribute."""
    # 120 chat rows, all in the last 60 minutes (one every 30 seconds).
    rows = [
        _execute_row(
            i,
            tool="emit_chat_received",
            ts=NOW - timedelta(seconds=30 * (120 - i)),
        )
        for i in range(1, 121)
    ]
    out = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    g = out.by_axis("conversational")
    assert g.count == 120
    # PRD: cap at SPARKLINE_MAX_ENTRIES = 100 contributing entries.
    assert sum(g.sparkline) == SPARKLINE_MAX_ENTRIES


# ---------------------------------------------------------------------------
# last_seq / last_ts deep-link metadata
# ---------------------------------------------------------------------------


def test_last_seq_points_at_most_recent_contributing_row() -> None:
    rows = [
        _execute_row(1, tool="emit_chat_received", ts=NOW - timedelta(minutes=10)),
        _execute_row(2, tool="emit_concept_proposed", ts=NOW - timedelta(minutes=8)),
        _execute_row(3, tool="emit_chat_received", ts=NOW - timedelta(minutes=5)),
        _execute_row(4, tool="emit_kpi_proposed", ts=NOW - timedelta(minutes=2)),
    ]
    out = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    assert out.by_axis("conversational").last_seq == 3
    assert out.by_axis("ontology").last_seq == 2
    assert out.by_axis("relational").last_seq == 4
    # Empty axes when there's nothing for a kind — still gracefully zero.
    rows2 = [_execute_row(1, tool="emit_chat_received")]
    out2 = compute_knowledge_ramp_gauges(rows2, company_id=COMPANY_ID, now=NOW)
    assert out2.by_axis("relational").last_seq == 0
    assert out2.by_axis("relational").last_ts is None


def test_trace_filter_kind_present_per_axis() -> None:
    out = compute_knowledge_ramp_gauges([], company_id=COMPANY_ID, now=NOW)
    for axis in GAUGE_AXES:
        assert out.by_axis(axis).trace_filter == TRACE_FILTER_KIND[axis]
        assert out.by_axis(axis).trace_filter  # non-empty


# ---------------------------------------------------------------------------
# Determinism (PRD §7 footnote 8: "Anything new must replay byte-identically")
# ---------------------------------------------------------------------------


def test_compute_is_deterministic_across_two_replays() -> None:
    """Same row stream → byte-identical gauges (sparkline + counts + seq)."""
    rows = [
        _execute_row(1, tool="emit_chat_received", ts=NOW - timedelta(minutes=10)),
        _execute_row(2, tool="emit_concept_proposed", ts=NOW - timedelta(minutes=8)),
        _execute_row(3, tool="emit_kpi_node", ts=NOW - timedelta(minutes=5)),
        _execute_row(4, tool="emit_chat_received", ts=NOW - timedelta(minutes=2)),
    ]
    a = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    b = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    assert a.to_dict() == b.to_dict()


def test_compute_is_order_invariant() -> None:
    """Same rows in different order → same gauges (last_seq is by seq, not order)."""
    rows = [
        _execute_row(1, tool="emit_chat_received", ts=NOW - timedelta(minutes=10)),
        _execute_row(2, tool="emit_chat_received", ts=NOW - timedelta(minutes=8)),
        _execute_row(3, tool="emit_chat_received", ts=NOW - timedelta(minutes=5)),
    ]
    a = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    b = compute_knowledge_ramp_gauges(
        list(reversed(rows)), company_id=COMPANY_ID, now=NOW
    )
    assert a.to_dict() == b.to_dict()
    assert a.by_axis("conversational").last_seq == 3


# ---------------------------------------------------------------------------
# Future-dated / clock-skew safety
# ---------------------------------------------------------------------------


def test_future_dated_row_lands_in_newest_bucket() -> None:
    """Clock skew: a row dated slightly in the future still contributes."""
    rows = [
        _execute_row(
            1,
            tool="emit_chat_received",
            ts=NOW + timedelta(seconds=30),
        ),
    ]
    out = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    sl = out.by_axis("conversational").sparkline
    assert sum(sl) == 1
    assert sl[-1] == 1


def test_to_dict_round_trip_is_jsonable() -> None:
    """KnowledgeRampGauges.to_dict() returns plain JSON-safe values."""
    import json

    rows = [
        _execute_row(1, tool="emit_chat_received", ts=NOW - timedelta(minutes=2)),
    ]
    out = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    s = json.dumps(out.to_dict())
    parsed = json.loads(s)
    assert parsed["company_id"] == str(COMPANY_ID)
    assert len(parsed["gauges"]) == 3
    assert parsed["window_seconds"] == 3600


# ---------------------------------------------------------------------------
# Integration with the in-memory ledger (smoke; ensures shape compatibility)
# ---------------------------------------------------------------------------


async def test_compute_against_inmemory_ledger_rows() -> None:
    """Smoke-check against ``InMemoryLedger.fetch`` row shape — the dashboard
    will hand the same shape to the projection in production."""
    from wormbase_ledger import InMemoryLedger

    ledger = InMemoryLedger()
    await ledger.write(
        company_id=COMPANY_ID,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(uuid4()),
            "reason": "test",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_chat_received",
            "args": {"channel_id": "C1", "message_id": "m1"},
            "result_ref": "m1",
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
        timestamp=NOW - timedelta(minutes=2),
        quadrant="active_probabilistic",
    )
    rows = await ledger.fetch(COMPANY_ID)
    out = compute_knowledge_ramp_gauges(rows, company_id=COMPANY_ID, now=NOW)
    assert out.by_axis("conversational").count == 1
    # The in-memory ledger writes 4 PEVR rows; only the execute row counts.
    assert sum(g.count for g in out.gauges) == 1
