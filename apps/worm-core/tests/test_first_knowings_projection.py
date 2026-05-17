"""Tests for the first_knowings projection (Demo-day P12).

Asserts:
  * Empty row stream returns an empty list (honest empty-state).
  * ``phenomenon_gap_detected`` execute rows surface as un-confirmed
    first-knowings with the correct kind / referenced_in_seq.
  * Confirmed phenomena disappear (``emit_phenomenon_gap_resolved``
    with matching novelty_key).
  * Raw ``person_proposed`` / ``reactivity_proposed`` proposed_by a worm
    identity surface; admin-proposed rows do not.
  * Confirmed person/reactivity rows disappear.
  * Filter chips: kinds + scope + recency narrow the result correctly.
  * Chatter context window returns ±3 chat_received rows around the
    triggering seq, in ascending seq order.
  * Replay determinism — identical row stream → identical projection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from wormbase_core.projections.first_knowings import (
    PHENOMENON_KINDS,
    compute_first_knowings,
)


TENANT = "00000000-0000-0000-0000-000000000001"
NOW = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)


def _row(
    seq: int,
    kind: str,
    payload: dict[str, Any],
    *,
    ts: datetime | None = None,
) -> dict[str, Any]:
    return {
        "seq": seq,
        "kind": kind,
        "payload": payload,
        "ts": ts or (NOW + timedelta(seconds=seq)),
    }


def _execute(
    seq: int, tool: str, args: dict[str, Any], *, ts: datetime | None = None,
) -> dict[str, Any]:
    return _row(seq, "execute", {"tool": tool, "args": args}, ts=ts)


def _propose(
    seq: int,
    target_kind: str,
    ref_id: str,
    proposed_by: str,
    *,
    ts: datetime | None = None,
) -> dict[str, Any]:
    return _row(
        seq,
        "propose",
        {
            "target_kind": target_kind,
            "ref_id": ref_id,
            "reason": "test propose",
            "proposed_by": proposed_by,
        },
        ts=ts,
    )


def _chat(seq: int, channel_id: str, text: str) -> dict[str, Any]:
    return _execute(
        seq,
        "channel_adapter.emit_chat_received",
        {
            "channel_id": channel_id,
            "sender_person": "p-1",
            "text": text,
        },
    )


# ---------------------------------------------------------------------------
# Empty / honest baselines
# ---------------------------------------------------------------------------


def test_first_knowings_empty_ledger_returns_empty_result() -> None:
    result = compute_first_knowings([], now=NOW)
    assert result.rows == []
    assert result.chatter_context == {}


def test_phenomenon_kinds_canonical_order_is_stable() -> None:
    assert PHENOMENON_KINDS == (
        "kpi_gap",
        "domain_gap",
        "process_gap",
        "reactivity_gap",
        "person_gap",
    )


# ---------------------------------------------------------------------------
# Phenomenon-gap surfacing
# ---------------------------------------------------------------------------


def test_phenomenon_gap_detected_surfaces_as_kpi_gap_first_knowing() -> None:
    rows = [
        _chat(1, "C1", "we should track Q3 Rev"),
        _execute(2, "emit_phenomenon_gap_detected", {
            "gap_kind": "kpi",
            "referenced_in_seq": 1,
            "suggested_proposal": {"label": "Q3 Revenue"},
            "confidence": 0.84,
            "novelty_key": "kpi:q3_rev",
        }),
    ]
    result = compute_first_knowings(rows, now=NOW)
    assert len(result.rows) == 1
    r = result.rows[0]
    assert r.kind == "kpi_gap"
    assert r.referenced_in_seq == 1
    assert r.confidence == 0.84
    assert r.novelty_key == "kpi:q3_rev"
    assert "Q3 Revenue" in r.summary


def test_phenomenon_gap_kinds_map_to_first_knowing_kinds() -> None:
    rows = [
        _execute(1, "emit_phenomenon_gap_detected", {
            "gap_kind": "kpi", "referenced_in_seq": 0,
            "suggested_proposal": {"label": "X"},
            "confidence": 0.5, "novelty_key": "k:x",
        }),
        _execute(2, "emit_phenomenon_gap_detected", {
            "gap_kind": "domain", "referenced_in_seq": 0,
            "suggested_proposal": {"name": "finance"},
            "confidence": 0.6, "novelty_key": "d:finance",
        }),
        _execute(3, "emit_phenomenon_gap_detected", {
            "gap_kind": "process", "referenced_in_seq": 0,
            "suggested_proposal": {"label": "weekly review"},
            "confidence": 0.7, "novelty_key": "p:wk",
        }),
        _execute(4, "emit_phenomenon_gap_detected", {
            "gap_kind": "reactivity", "referenced_in_seq": 0,
            "suggested_proposal": {"name": "friday-quality-review"},
            "confidence": 0.8, "novelty_key": "r:fqr",
        }),
    ]
    result = compute_first_knowings(rows, now=NOW)
    kinds = {r.kind for r in result.rows}
    assert kinds == {"kpi_gap", "domain_gap", "process_gap", "reactivity_gap"}


def test_phenomenon_gap_resolved_removes_first_knowing() -> None:
    rows = [
        _execute(1, "emit_phenomenon_gap_detected", {
            "gap_kind": "kpi", "referenced_in_seq": 0,
            "suggested_proposal": {"label": "X"},
            "confidence": 0.5, "novelty_key": "k:x",
        }),
        _execute(2, "emit_phenomenon_gap_resolved", {"novelty_key": "k:x"}),
    ]
    result = compute_first_knowings(rows, now=NOW)
    assert result.rows == []


# ---------------------------------------------------------------------------
# Person / Reactivity proposes
# ---------------------------------------------------------------------------


def test_person_proposed_by_worm_surfaces_as_person_gap() -> None:
    rows = [
        _propose(1, "person_proposed", "p-bob-uuid", proposed_by="worm"),
        _execute(2, "emit_person_proposed", {
            "person_id": "p-bob-uuid",
            "name": "Bob",
            "platform": "slack",
        }),
    ]
    result = compute_first_knowings(rows, now=NOW)
    assert len(result.rows) == 1
    r = result.rows[0]
    assert r.kind == "person_gap"
    assert r.ref_id == "p-bob-uuid"
    assert "Bob" in r.summary
    assert r.scope == "mine"


def test_person_proposed_by_admin_does_not_surface() -> None:
    rows = [
        _propose(1, "person_proposed", "p-bob-uuid", proposed_by="admin"),
        _execute(2, "emit_person_proposed", {"person_id": "p-bob-uuid", "name": "Bob"}),
    ]
    result = compute_first_knowings(rows, now=NOW)
    assert result.rows == []


def test_person_proposed_by_uuid_string_does_not_surface() -> None:
    """A 36-char UUID-shaped proposed_by signals a real Person actor."""
    rows = [
        _propose(
            1,
            "person_proposed",
            "p-bob-uuid",
            proposed_by="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ),
        _execute(2, "emit_person_proposed", {"person_id": "p-bob-uuid"}),
    ]
    result = compute_first_knowings(rows, now=NOW)
    assert result.rows == []


def test_confirmed_person_disappears_from_first_knowings() -> None:
    rows = [
        _propose(1, "person_proposed", "p-bob-uuid", proposed_by="worm"),
        _execute(2, "emit_person_proposed", {"person_id": "p-bob-uuid", "name": "Bob"}),
        _propose(3, "person_confirmed", "p-bob-uuid", proposed_by="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
        _execute(4, "emit_person_confirmed", {"person_id": "p-bob-uuid"}),
    ]
    result = compute_first_knowings(rows, now=NOW)
    assert result.rows == []


def test_reactivity_proposed_by_worm_surfaces_as_reactivity_gap() -> None:
    rows = [
        _propose(1, "reactivity_proposed", "r-fri-uuid", proposed_by="worm"),
        _execute(2, "emit_reactivity_proposed", {
            "reactivity_id": "r-fri-uuid",
            "name": "friday-revenue-close",
            "predicate": "every Friday",
        }),
    ]
    result = compute_first_knowings(rows, now=NOW)
    assert len(result.rows) == 1
    r = result.rows[0]
    assert r.kind == "reactivity_gap"
    assert "friday-revenue-close" in r.summary


def test_confirmed_reactivity_disappears_from_first_knowings() -> None:
    rows = [
        _propose(1, "reactivity_proposed", "r-1", proposed_by="worm"),
        _execute(2, "emit_reactivity_proposed", {"reactivity_id": "r-1"}),
        _execute(3, "emit_reactivity_confirmed", {"reactivity_id": "r-1"}),
    ]
    result = compute_first_knowings(rows, now=NOW)
    assert result.rows == []


# ---------------------------------------------------------------------------
# Filter chips
# ---------------------------------------------------------------------------


def _build_mixed_arc() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.append(_chat(1, "C1", "Q3 rev"))
    rows.append(_execute(2, "emit_phenomenon_gap_detected", {
        "gap_kind": "kpi", "referenced_in_seq": 1,
        "suggested_proposal": {"label": "Q3 Rev"},
        "confidence": 0.7, "novelty_key": "kpi:q3",
    }))
    rows.append(_propose(3, "person_proposed", "p-alice", proposed_by="worm"))
    rows.append(_execute(4, "emit_person_proposed", {"person_id": "p-alice"}))
    rows.append(_propose(5, "reactivity_proposed", "r-1", proposed_by="worm"))
    rows.append(_execute(6, "emit_reactivity_proposed", {"reactivity_id": "r-1"}))
    return rows


def test_filter_by_kinds_narrows_result() -> None:
    rows = _build_mixed_arc()
    result = compute_first_knowings(rows, kinds=("kpi_gap",), now=NOW)
    assert len(result.rows) == 1
    assert result.rows[0].kind == "kpi_gap"


def test_filter_by_scope_mine_returns_only_person_scope() -> None:
    rows = _build_mixed_arc()
    result = compute_first_knowings(rows, scope="mine", now=NOW)
    # Only the person_gap row falls into mine-scope (auto-inferred).
    kinds = {r.kind for r in result.rows}
    assert kinds == {"person_gap"}


def test_filter_by_scope_company_returns_company_scope_only() -> None:
    rows = _build_mixed_arc()
    result = compute_first_knowings(rows, scope="company", now=NOW)
    kinds = {r.kind for r in result.rows}
    # phenomenon_gap_detected and reactivity_proposed default to company.
    assert kinds == {"kpi_gap", "reactivity_gap"}


def test_filter_by_recency_drops_old_rows() -> None:
    # An old row 8 days back, plus a fresh one.
    old_ts = NOW - timedelta(days=8)
    fresh_ts = NOW - timedelta(minutes=10)
    rows = [
        _execute(1, "emit_phenomenon_gap_detected", {
            "gap_kind": "kpi", "referenced_in_seq": 0,
            "suggested_proposal": {"label": "old"},
            "confidence": 0.5, "novelty_key": "kpi:old",
        }, ts=old_ts),
        _execute(2, "emit_phenomenon_gap_detected", {
            "gap_kind": "kpi", "referenced_in_seq": 0,
            "suggested_proposal": {"label": "fresh"},
            "confidence": 0.5, "novelty_key": "kpi:fresh",
        }, ts=fresh_ts),
    ]
    result_24h = compute_first_knowings(rows, recency="24h", now=NOW)
    assert len(result_24h.rows) == 1
    assert result_24h.rows[0].novelty_key == "kpi:fresh"

    result_7d = compute_first_knowings(rows, recency="7d", now=NOW)
    assert len(result_7d.rows) == 1  # 8d still drops

    result_all = compute_first_knowings(rows, recency="all", now=NOW)
    assert len(result_all.rows) == 2


# ---------------------------------------------------------------------------
# Chatter context
# ---------------------------------------------------------------------------


def test_chatter_context_returns_three_above_three_below_anchor() -> None:
    rows: list[dict[str, Any]] = []
    # 8 chat rows with seqs 1..8, all in C1.
    for s in range(1, 9):
        rows.append(_chat(s, "C1", f"msg {s}"))
    # Phenomenon gap anchored at seq=4.
    rows.append(_execute(9, "emit_phenomenon_gap_detected", {
        "gap_kind": "kpi", "referenced_in_seq": 4,
        "suggested_proposal": {"label": "X"},
        "confidence": 0.5, "novelty_key": "kpi:x",
    }))
    result = compute_first_knowings(rows, now=NOW + timedelta(seconds=10))
    assert len(result.rows) == 1
    ctx = result.chatter_context.get(4)
    assert ctx is not None
    # ±3 around seq=4 → seqs 1..7 (anchor at index 3, lo=0, hi=7).
    seqs = [c["seq"] for c in ctx]
    assert seqs == [1, 2, 3, 4, 5, 6, 7]


def test_chatter_context_handles_missing_anchor_gracefully() -> None:
    rows: list[dict[str, Any]] = [
        _execute(2, "emit_phenomenon_gap_detected", {
            "gap_kind": "kpi", "referenced_in_seq": 999,
            "suggested_proposal": {"label": "X"},
            "confidence": 0.5, "novelty_key": "kpi:x",
        }),
    ]
    result = compute_first_knowings(rows, now=NOW + timedelta(seconds=5))
    assert len(result.rows) == 1
    # No chat rows to anchor against → empty list keyed at the anchor seq.
    assert result.chatter_context.get(999) == []


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_first_knowings_is_replay_deterministic() -> None:
    rows = _build_mixed_arc()
    a = compute_first_knowings(rows, now=NOW + timedelta(seconds=10))
    b = compute_first_knowings(list(rows), now=NOW + timedelta(seconds=10))
    assert [r.to_dict() for r in a.rows] == [r.to_dict() for r in b.rows]
    assert a.chatter_context == b.chatter_context


def test_first_knowings_sorts_newest_seq_first() -> None:
    rows = _build_mixed_arc()
    result = compute_first_knowings(rows, now=NOW + timedelta(seconds=10))
    seqs = [r.first_detected_seq for r in result.rows]
    assert seqs == sorted(seqs, reverse=True)
