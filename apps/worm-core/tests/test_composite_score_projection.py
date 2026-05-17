"""Tests for the composite_score projection (Demo-day P1).

Asserts:
  * Replay determinism — identical row stream → identical scalar.
  * Components fold over the four expected signals (gate precision,
    propose→keep, ramp delta, reactivity confirm).
  * Loss-style display value descends as positive signal accumulates.
  * Series accessor returns ≥9 points across an install arc.
  * Top-contributor reactivity surfaces by fire count with deterministic
    tie-break on lex-sorted reactivity_id.
  * Empty ledger returns a neutral score without raising.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from wormbase_core.projections.composite_score import (
    DEFAULT_WEIGHTS,
    composite_score,
    composite_score_series,
)


TENANT = "00000000-0000-0000-0000-000000000001"
NOW = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)


def _row(seq: int, kind: str, payload: dict[str, Any], *, ts: datetime | None = None) -> dict[str, Any]:
    """Build a synthetic ledger row in the shape ``fetch`` returns."""
    return {
        "seq": seq,
        "kind": kind,
        "payload": payload,
        "ts": ts or (NOW + timedelta(seconds=seq)),
    }


def _execute(seq: int, tool: str, args: dict[str, Any], *, ts: datetime | None = None) -> dict[str, Any]:
    return _row(seq, "execute", {"tool": tool, "args": args}, ts=ts)


def _build_arc() -> list[dict[str, Any]]:
    """Synthetic 9-step install arc — gradual positive signal accumulation."""
    rows: list[dict[str, Any]] = []
    seq = 1

    # Step 1: chat_received (ramp delta tick).
    rows.append(_row(seq, "chat_received", {"channel_id": "C1"})); seq += 1
    # Step 2: memory_written (ramp delta tick on ontology).
    rows.append(_execute(seq, "emit_memory_written", {"memory_id": "m1"})); seq += 1
    # Step 3: kpi_proposed (ramp delta tick on relational).
    rows.append(_execute(seq, "emit_kpi_proposed", {"kpi_id": "k1"})); seq += 1
    # Step 4: reactivity_proposed.
    rows.append(_execute(seq, "emit_reactivity_proposed", {"reactivity_id": "r1"})); seq += 1
    # Step 5: reactivity_confirmed (confirm rate ↑).
    rows.append(_execute(seq, "emit_reactivity_confirmed", {"reactivity_id": "r1"})); seq += 1
    # Step 6: experiment_proposed.
    rows.append(_execute(
        seq, "emit_experiment_proposed",
        {"experiment_id": "e1", "audience": "person:00000000-0000-0000-0000-000000000abc"},
    )); seq += 1
    # Step 7: gate_fired allowed (subject_ref=e1).
    rows.append(_row(seq, "gate_fired", {
        "gate": "interjection", "outcome": "allowed", "subject_ref": "e1",
    })); seq += 1
    # Step 8: experiment_resolved keep (gate precision ↑, propose→keep ↑).
    rows.append(_execute(
        seq, "emit_experiment_resolved",
        {"experiment_id": "e1", "outcome": "keep"},
    )); seq += 1
    # Step 9: reactivity_fired (top-contributor signal).
    rows.append(_execute(
        seq, "emit_reactivity_fired", {"reactivity_id": "r1", "source_seq": 4},
    )); seq += 1
    return rows


def test_composite_score_is_replay_deterministic() -> None:
    rows = _build_arc()
    a = composite_score(TENANT, rows)
    b = composite_score(TENANT, list(rows))  # fresh list, same seqs
    assert a == b
    assert a.score == b.score


def test_composite_score_descends_as_loss_across_arc() -> None:
    """Loss = 1 - score should *decrease* as positive signal accumulates."""
    rows = _build_arc()
    series = composite_score_series(TENANT, rows, points=9)
    assert len(series.points) >= 9
    losses = [1.0 - p.score for p in series.points]
    # First loss must exceed last loss — the curve descends across the arc.
    assert losses[0] > losses[-1], (
        f"loss did not descend: first={losses[0]:.4f} last={losses[-1]:.4f} "
        f"all={[round(x, 4) for x in losses]}"
    )


def test_composite_score_components_match_expected() -> None:
    rows = _build_arc()
    cs = composite_score(TENANT, rows)
    # Propose-keep: 1 keep / (1 keep + 0 discard) = 1.0
    assert cs.components["propose_keep_ratio"] == 1.0
    # Reactivity confirm: 1/1 = 1.0
    assert cs.components["reactivity_confirm_rate"] == 1.0
    # Gate precision: 1 upheld / (1 upheld + 0 rejected) = 1.0
    assert cs.components["gate_precision"] == 1.0
    # Ramp delta: 3 increments / 30 cap = 0.1
    assert cs.components["ramp_delta"] == 0.1
    # Equal-weight composite: (1 + 1 + 1 + 0.1) / 4 = 0.775
    assert abs(cs.score - 0.775) < 1e-9


def test_composite_score_default_weights_sum_to_one() -> None:
    cs = composite_score(TENANT, _build_arc())
    assert abs(sum(cs.weights.values()) - 1.0) < 1e-9
    for k in DEFAULT_WEIGHTS:
        assert k in cs.weights


def test_composite_score_empty_ledger_is_neutral() -> None:
    cs = composite_score(TENANT, [])
    # No rows → all components fall back to neutrals (0.5 / 0.5 / 0.0 / 0.5)
    # but composite_score short-circuits on empty in_scope and returns 0.5.
    assert cs.score == 0.5
    assert cs.ledger_height == 0


def test_composite_score_top_contributor_is_max_fire_count() -> None:
    rows = _build_arc()
    # Add another reactivity that fires twice — should win over r1 (1 fire).
    rows.append(_execute(
        100, "emit_reactivity_fired", {"reactivity_id": "r2", "source_seq": 9},
    ))
    rows.append(_execute(
        101, "emit_reactivity_fired", {"reactivity_id": "r2", "source_seq": 9},
    ))
    series = composite_score_series(TENANT, rows, points=9)
    # The latest point sees both r1 (1 fire) and r2 (2 fires) in window.
    assert series.points[-1].top_contributor_reactivity_id == "r2"


def test_composite_score_weights_override_via_ledger_entry() -> None:
    rows = _build_arc()
    # Admin emit override: weight 1.0 to ramp_delta, 0 elsewhere.
    rows.append(_execute(
        50, "emit_composite_score_weights",
        {
            "gate_precision": 0.0,
            "propose_keep_ratio": 0.0,
            "ramp_delta": 1.0,
            "reactivity_confirm_rate": 0.0,
        },
    ))
    cs = composite_score(TENANT, rows)
    # Score collapses to ramp_delta (0.1) since it is the only weighted term.
    assert abs(cs.score - 0.1) < 1e-9
    assert cs.weights["ramp_delta"] == 1.0


def test_composite_score_series_uniform_stride_replay_stable() -> None:
    rows = _build_arc()
    s1 = composite_score_series(TENANT, rows, points=9)
    s2 = composite_score_series(TENANT, list(rows), points=9)
    assert [p.ledger_height for p in s1.points] == [p.ledger_height for p in s2.points]
    assert [p.score for p in s1.points] == [p.score for p in s2.points]
    assert all(p1 == p2 for p1, p2 in zip(s1.points, s2.points))
