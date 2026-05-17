"""Position registry tests — moved from apps/worm-core/tests/test_positions.py.

Identical to the original; only the import path changed:
  - `from wormbase_core.positions import ...`
  + `from wormbase_identity_tracker.positions import ...`

Step 5 — position registry tests.

The seed registry must:
  * carry ≥ 6 canonical positions (CFO, CMO, data engineer, marketing lead,
    ops manager, customer success, founder, admin, product manager).
  * give every position a non-empty metric set + question patterns +
    improvement candidates.
  * pin a deterministic headline metric per position.
"""

from __future__ import annotations

import pytest

from wormbase_identity_tracker.positions import (
    ImprovementCandidate,
    Metric,
    Position,
    all_positions,
    get_position,
    headline_metric_for_position,
    position_candidates,
    position_metrics,
    position_patterns,
)


REQUIRED_POSITIONS = {
    "cfo",
    "cmo",
    "data_engineer",
    "marketing_lead",
    "ops_manager",
    "customer_success",
    "founder",
    "admin",
    "product_manager",
}


def test_registry_has_seed_positions() -> None:
    ids = {p.position_id for p in all_positions()}
    assert REQUIRED_POSITIONS.issubset(ids)
    assert len(all_positions()) >= 6


def test_each_position_has_metrics_patterns_candidates() -> None:
    for p in all_positions():
        assert isinstance(p, Position)
        assert p.metrics, f"position {p.position_id} has no metrics"
        assert p.patterns, f"position {p.position_id} has no patterns"
        assert p.candidates, f"position {p.position_id} has no candidates"
        for m in p.metrics:
            assert isinstance(m, Metric)
            assert 0.0 <= m.weight <= 1.0
            assert m.metric_id
        for c in p.candidates:
            assert isinstance(c, ImprovementCandidate)
            assert c.summary
            # Candidate's headline metric must exist on the position.
            assert any(
                m.metric_id == c.headline_metric_id for m in p.metrics
            ), (
                f"candidate {c.candidate_id} references missing metric "
                f"{c.headline_metric_id} on {p.position_id}"
            )


def test_position_accessors_match_registry() -> None:
    cfo = get_position("cfo")
    assert cfo is not None
    metrics = position_metrics("cfo")
    assert any(m.metric_id == "revenue" for m in metrics)
    patterns = position_patterns("cfo")
    assert any("what's our" in p for p in patterns)
    candidates = position_candidates("cfo")
    assert candidates, "cfo should have candidates"
    # All candidates' headline metrics live in the cfo metric set.
    cfo_metric_ids = {m.metric_id for m in metrics}
    for c in candidates:
        assert c.headline_metric_id in cfo_metric_ids


def test_unknown_position_returns_none_and_empty_lists() -> None:
    assert get_position("zzznotreal") is None
    assert position_metrics("zzznotreal") == []
    assert position_patterns("zzznotreal") == []
    assert position_candidates("zzznotreal") == []
    assert headline_metric_for_position("zzznotreal") is None


@pytest.mark.parametrize("position_id", sorted(REQUIRED_POSITIONS))
def test_headline_metric_is_deterministic(position_id: str) -> None:
    a = headline_metric_for_position(position_id)
    b = headline_metric_for_position(position_id)
    assert a is not None and b is not None
    assert a.metric_id == b.metric_id


def test_data_engineer_headline_is_pipeline_latency() -> None:
    m = headline_metric_for_position("data_engineer")
    assert m is not None
    assert m.metric_id == "pipeline_p95_latency_ms"


def test_cfo_headline_is_revenue() -> None:
    m = headline_metric_for_position("cfo")
    assert m is not None
    assert m.metric_id == "revenue"
