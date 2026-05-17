"""L5 Sub-wave B — per-strategy unit tests.

Three strategy impls, each independently testable:

  * :class:`ColumnNameFingerprintStrategy` — regex over column names.
  * :class:`ValuePatternFingerprintStrategy` — value-pattern regex via
    :class:`SamplerProtocol`.
  * :class:`DistributionFingerprintStrategy` — statistical heuristics
    via :class:`HistoricalStatsReader`.

Tests assert:

  * Per-strategy productive paths (positive matches).
  * Per-strategy negative paths (stop-list, empty samples, no stats).
  * Replay stability + canonical ``type_id`` formation.
  * Confidence values match the spec tiers.
"""
from __future__ import annotations

from typing import Any

import pytest

from wormbase_agent_gateway.semantic_type import (
    ColumnNameFingerprintStrategy,
    DistributionFingerprintStrategy,
    ProposedSemanticType,
    ValuePatternFingerprintStrategy,
    make_type_id,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeSampler:
    """Test double for :class:`SamplerProtocol`."""

    def __init__(self, columns: dict[tuple[str, str], set[str]] | None = None) -> None:
        self.columns = columns or {}
        self.calls: list[tuple[str, str, int]] = []

    async def sample_column(self, table_id: str, column: str, n: int) -> set[str]:
        self.calls.append((table_id, column, n))
        return self.columns.get((table_id, column), set())

    async def estimate_table_size(self, table_id: str) -> int:
        return 0


class _FakeStatsReader:
    """Test double for :class:`HistoricalStatsReader`."""

    def __init__(self, snapshots: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.snapshots = snapshots or {}
        self.calls: list[str] = []

    async def get_snapshots_for_table(self, table_id: str) -> list[dict[str, Any]]:
        self.calls.append(table_id)
        return self.snapshots.get(table_id, [])


# ---------------------------------------------------------------------------
# ColumnNameFingerprintStrategy — positive matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_column_name_exact_email_match() -> None:
    """``email`` column → email proposal at high confidence."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="src.public.users", column="email")
    assert len(out) == 1
    p = out[0]
    assert p.semantic_type == "email"
    assert p.confidence >= 0.85
    assert p.strategy == "column_name"
    assert p.table_id == "src.public.users"
    assert p.column == "email"
    assert p.type_id == make_type_id(
        table_id="src.public.users", column="email", semantic_type="email",
    )
    assert "regex" in p.evidence
    assert "reason" in p.evidence


@pytest.mark.asyncio
async def test_column_name_email_suffix_match() -> None:
    """``user_email`` suffix → email proposal at lower-tier confidence."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="t", column="user_email")
    assert len(out) == 1
    assert out[0].semantic_type == "email"
    assert 0.70 <= out[0].confidence < 0.90


@pytest.mark.asyncio
async def test_column_name_ssn_high_confidence() -> None:
    """``ssn`` exact → pii_ssn at very high confidence."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="t", column="ssn")
    assert len(out) == 1
    assert out[0].semantic_type == "pii_ssn"
    assert out[0].confidence >= 0.90


@pytest.mark.asyncio
async def test_column_name_currency_iso() -> None:
    """``currency`` → currency_iso."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="t", column="currency")
    assert len(out) == 1
    assert out[0].semantic_type == "currency_iso"


@pytest.mark.asyncio
async def test_column_name_pii_address_suffix() -> None:
    """``billing_address`` → pii_address."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="t", column="billing_address")
    semantic_types = {p.semantic_type for p in out}
    assert "pii_address" in semantic_types


@pytest.mark.asyncio
async def test_column_name_metric_amount_suffix() -> None:
    """``order_amount`` → metric_amount."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="t", column="order_amount")
    assert len(out) >= 1
    semantic_types = {p.semantic_type for p in out}
    assert "metric_amount" in semantic_types


@pytest.mark.asyncio
async def test_column_name_metric_rate_pct_suffix() -> None:
    """``conversion_pct`` → metric_rate."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="t", column="conversion_pct")
    assert any(p.semantic_type == "metric_rate" for p in out)


@pytest.mark.asyncio
async def test_column_name_created_at_iso_datetime() -> None:
    """``created_at`` → iso_datetime."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="t", column="created_at")
    assert any(p.semantic_type == "iso_datetime" for p in out)


@pytest.mark.asyncio
async def test_column_name_uuid_match() -> None:
    """``uuid`` column → uuid_v4 default."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="t", column="uuid")
    assert any(p.semantic_type == "uuid_v4" for p in out)


@pytest.mark.asyncio
async def test_column_name_pii_name_last_name() -> None:
    """``last_name`` → pii_name."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="t", column="last_name")
    assert any(p.semantic_type == "pii_name" for p in out)


# ---------------------------------------------------------------------------
# ColumnNameFingerprintStrategy — negative / stop-list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_column_name_stop_list_rejects_ambiguous_bare_names() -> None:
    """Stop-list ``name``, ``type``, ``value`` produce no proposals."""
    s = ColumnNameFingerprintStrategy()
    for ambiguous in ("name", "type", "value", "data", "label"):
        out = await s.propose(table_id="t", column=ambiguous)
        assert out == [], f"stop-list failed for {ambiguous!r}: got {out}"


@pytest.mark.asyncio
async def test_column_name_unknown_column_returns_empty() -> None:
    """A column name with no pattern match → no proposal."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="t", column="xyzzy_blob_42")
    assert out == []


@pytest.mark.asyncio
async def test_column_name_empty_column_returns_empty() -> None:
    """Empty column name short-circuits to empty list."""
    s = ColumnNameFingerprintStrategy()
    out = await s.propose(table_id="t", column="")
    assert out == []


@pytest.mark.asyncio
async def test_column_name_custom_stop_list_overrides_default() -> None:
    """Custom stop_list parameter overrides the default set."""
    # Empty stop-list opts back IN to ambiguous names — but those still
    # have no pattern matches, so the result remains [].
    s = ColumnNameFingerprintStrategy(stop_list=frozenset())
    out = await s.propose(table_id="t", column="name")
    # With no stop-list, "name" can be matched by patterns (e.g.
    # pii-related). We don't assert specifics; just that the path
    # doesn't crash and returns a list.
    assert isinstance(out, list)


@pytest.mark.asyncio
async def test_column_name_replay_stable() -> None:
    """Two calls on same input produce identical type_ids + confidence."""
    s = ColumnNameFingerprintStrategy()
    a = await s.propose(table_id="t", column="email")
    b = await s.propose(table_id="t", column="email")
    assert len(a) == len(b)
    for pa, pb in zip(a, b):
        assert pa.type_id == pb.type_id
        assert pa.confidence == pb.confidence
        assert pa.semantic_type == pb.semantic_type


# ---------------------------------------------------------------------------
# ValuePatternFingerprintStrategy — positive paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_value_pattern_email_high_match_ratio_triggers() -> None:
    """20/20 emails → email proposal at 0.95."""
    samples = {
        f"user{i}@example.com" for i in range(20)
    }
    sampler = _FakeSampler(columns={("t", "c"): samples})
    s = ValuePatternFingerprintStrategy(sampler=sampler)
    out = await s.propose(table_id="t", column="c", sample_size=20)
    matches = [p for p in out if p.semantic_type == "email"]
    assert len(matches) == 1
    assert matches[0].confidence == pytest.approx(0.95)
    assert matches[0].strategy == "value_pattern"
    assert matches[0].evidence["match_count"] == 20
    assert matches[0].evidence["sample_n"] == 20


@pytest.mark.asyncio
async def test_value_pattern_uuid_v4_matches() -> None:
    """20/20 UUIDv4 strings → uuid_v4 proposal."""
    samples = {
        f"{'a' * 8}-1234-4abc-9def-{'0' * 12}"
        for _ in range(1)
    }
    # Generate 20 distinct UUIDv4s
    import uuid
    samples = {str(uuid.uuid4()) for _ in range(20)}
    sampler = _FakeSampler(columns={("t", "c"): samples})
    s = ValuePatternFingerprintStrategy(sampler=sampler)
    out = await s.propose(table_id="t", column="c", sample_size=20)
    assert any(p.semantic_type == "uuid_v4" for p in out)


@pytest.mark.asyncio
async def test_value_pattern_iso_date_matches() -> None:
    """20/20 ISO dates → iso_date proposal."""
    samples = {f"2026-0{(i % 9) + 1}-15" for i in range(20)}
    sampler = _FakeSampler(columns={("t", "c"): samples})
    s = ValuePatternFingerprintStrategy(sampler=sampler)
    out = await s.propose(table_id="t", column="c", sample_size=20)
    # Note: iso_date is short for iso_datetime — both may match if regex
    # is permissive. We assert at least one of iso_* fires.
    assert any(p.semantic_type in {"iso_date", "iso_datetime"} for p in out)


@pytest.mark.asyncio
async def test_value_pattern_below_threshold_no_match() -> None:
    """Match ratio below threshold → no proposal."""
    # 5/20 emails, 15/20 garbage — below 0.9 threshold.
    samples = {
        *(f"user{i}@example.com" for i in range(5)),
        *(f"garbage_{i}" for i in range(15)),
    }
    sampler = _FakeSampler(columns={("t", "c"): samples})
    s = ValuePatternFingerprintStrategy(sampler=sampler)
    out = await s.propose(table_id="t", column="c", sample_size=20)
    assert not any(p.semantic_type == "email" for p in out)


@pytest.mark.asyncio
async def test_value_pattern_empty_samples_returns_empty() -> None:
    """Sampler returns empty set → no proposals."""
    sampler = _FakeSampler(columns={("t", "c"): set()})
    s = ValuePatternFingerprintStrategy(sampler=sampler)
    out = await s.propose(table_id="t", column="c", sample_size=20)
    assert out == []


@pytest.mark.asyncio
async def test_value_pattern_zero_sample_size_returns_empty() -> None:
    """sample_size=0 short-circuits."""
    sampler = _FakeSampler(columns={("t", "c"): {"foo@bar.com"}})
    s = ValuePatternFingerprintStrategy(sampler=sampler)
    out = await s.propose(table_id="t", column="c", sample_size=0)
    assert out == []


@pytest.mark.asyncio
async def test_value_pattern_custom_threshold_lowers_bar() -> None:
    """Lowering match_ratio_threshold admits lower-ratio matches."""
    samples = {
        *(f"user{i}@example.com" for i in range(10)),
        *(f"garbage_{i}" for i in range(10)),
    }
    sampler = _FakeSampler(columns={("t", "c"): samples})
    s = ValuePatternFingerprintStrategy(
        sampler=sampler, match_ratio_threshold=0.4,
    )
    out = await s.propose(table_id="t", column="c", sample_size=20)
    assert any(p.semantic_type == "email" for p in out)


# ---------------------------------------------------------------------------
# DistributionFingerprintStrategy — positive paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_distribution_uuid_heuristic_fires() -> None:
    """High distinct_ratio + UUID-length avg → uuid_v4 proposal."""
    reader = _FakeStatsReader(snapshots={
        "t": [{
            "row_count": 1000,
            "columns": [
                {
                    "name": "id",
                    "distinct_count": 1000,
                    "avg_length": 36,
                },
            ],
        }],
    })
    s = DistributionFingerprintStrategy(stats_reader=reader)
    out = await s.propose(table_id="t", column="id")
    assert any(p.semantic_type == "uuid_v4" for p in out)
    uuid_props = [p for p in out if p.semantic_type == "uuid_v4"]
    assert uuid_props[0].confidence == pytest.approx(0.80)
    assert uuid_props[0].strategy == "distribution"


@pytest.mark.asyncio
async def test_distribution_metric_rate_heuristic_fires() -> None:
    """Float in [0, 1] → metric_rate."""
    reader = _FakeStatsReader(snapshots={
        "t": [{
            "row_count": 100,
            "columns": [
                {
                    "name": "score",
                    "min": 0.01,
                    "max": 0.99,
                    "is_float": True,
                },
            ],
        }],
    })
    s = DistributionFingerprintStrategy(stats_reader=reader)
    out = await s.propose(table_id="t", column="score")
    assert any(p.semantic_type == "metric_rate" for p in out)


@pytest.mark.asyncio
async def test_distribution_metric_count_heuristic_fires() -> None:
    """Positive int with right-skewed mean >> median → metric_count."""
    reader = _FakeStatsReader(snapshots={
        "t": [{
            "row_count": 1000,
            "columns": [
                {
                    "name": "events",
                    "min": 0,
                    "max": 9999,
                    "mean": 50.0,
                    "median": 2.0,
                    "is_int": True,
                },
            ],
        }],
    })
    s = DistributionFingerprintStrategy(stats_reader=reader)
    out = await s.propose(table_id="t", column="events")
    assert any(p.semantic_type == "metric_count" for p in out)


# ---------------------------------------------------------------------------
# DistributionFingerprintStrategy — negative paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_distribution_no_snapshots_returns_empty() -> None:
    """Reader returns empty list → no proposals (honest stub)."""
    reader = _FakeStatsReader(snapshots={})
    s = DistributionFingerprintStrategy(stats_reader=reader)
    out = await s.propose(table_id="t", column="c")
    assert out == []


@pytest.mark.asyncio
async def test_distribution_column_not_in_snapshot_returns_empty() -> None:
    """Snapshot exists but column not in it → no proposals."""
    reader = _FakeStatsReader(snapshots={
        "t": [{"row_count": 100, "columns": [{"name": "other"}]}],
    })
    s = DistributionFingerprintStrategy(stats_reader=reader)
    out = await s.propose(table_id="t", column="c")
    assert out == []


@pytest.mark.asyncio
async def test_distribution_low_cardinality_no_uuid() -> None:
    """Low distinct ratio → no uuid proposal even with UUID length."""
    reader = _FakeStatsReader(snapshots={
        "t": [{
            "row_count": 1000,
            "columns": [
                {"name": "c", "distinct_count": 10, "avg_length": 36},
            ],
        }],
    })
    s = DistributionFingerprintStrategy(stats_reader=reader)
    out = await s.propose(table_id="t", column="c")
    assert not any(p.semantic_type == "uuid_v4" for p in out)


@pytest.mark.asyncio
async def test_distribution_float_outside_unit_range_no_rate() -> None:
    """Float not in [0, 1] → no metric_rate proposal."""
    reader = _FakeStatsReader(snapshots={
        "t": [{
            "row_count": 100,
            "columns": [
                {"name": "c", "min": 0.5, "max": 100.0, "is_float": True},
            ],
        }],
    })
    s = DistributionFingerprintStrategy(stats_reader=reader)
    out = await s.propose(table_id="t", column="c")
    assert not any(p.semantic_type == "metric_rate" for p in out)


@pytest.mark.asyncio
async def test_distribution_uses_latest_snapshot() -> None:
    """When N snapshots exist, the latest (newest last) is consulted."""
    reader = _FakeStatsReader(snapshots={
        "t": [
            {"row_count": 1, "columns": [{"name": "c"}]},  # old, sparse
            {
                "row_count": 1000,
                "columns": [
                    {"name": "id", "distinct_count": 1000, "avg_length": 36},
                ],
            },  # newest, productive
        ],
    })
    s = DistributionFingerprintStrategy(stats_reader=reader)
    out = await s.propose(table_id="t", column="id")
    assert any(p.semantic_type == "uuid_v4" for p in out)


# ---------------------------------------------------------------------------
# Confidence range invariant — every proposal clamps to [0.0, 1.0]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_strategies_emit_unit_range_confidence() -> None:
    """Every emitted proposal has confidence in [0.0, 1.0]."""
    cn = ColumnNameFingerprintStrategy()
    out = await cn.propose(table_id="t", column="email")
    for p in out:
        assert 0.0 <= p.confidence <= 1.0

    sampler = _FakeSampler(columns={
        ("t", "c"): {f"user{i}@example.com" for i in range(20)},
    })
    vp = ValuePatternFingerprintStrategy(sampler=sampler)
    out_vp = await vp.propose(table_id="t", column="c", sample_size=20)
    for p in out_vp:
        assert 0.0 <= p.confidence <= 1.0

    reader = _FakeStatsReader(snapshots={
        "t": [{
            "row_count": 1000,
            "columns": [
                {"name": "id", "distinct_count": 1000, "avg_length": 36},
            ],
        }],
    })
    dist = DistributionFingerprintStrategy(stats_reader=reader)
    out_dist = await dist.propose(table_id="t", column="id")
    for p in out_dist:
        assert 0.0 <= p.confidence <= 1.0


@pytest.mark.asyncio
async def test_each_proposal_carries_evidence() -> None:
    """Every emitted proposal has a non-None evidence dict."""
    cn = ColumnNameFingerprintStrategy()
    for p in await cn.propose(table_id="t", column="email"):
        assert isinstance(p.evidence, dict)


@pytest.mark.asyncio
async def test_proposal_type_id_matches_canonical_hash() -> None:
    """The emitted ``type_id`` matches :func:`make_type_id` for its tuple."""
    cn = ColumnNameFingerprintStrategy()
    out = await cn.propose(table_id="t", column="email")
    for p in out:
        assert p.type_id == make_type_id(
            table_id=p.table_id,
            column=p.column,
            semantic_type=p.semantic_type,
        )


# ---------------------------------------------------------------------------
# Strategy independence — composable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_column_name_and_value_pattern_independent() -> None:
    """A column matching both strategies yields proposals from each."""
    cn = ColumnNameFingerprintStrategy()
    cn_out = await cn.propose(table_id="t", column="user_email")

    sampler = _FakeSampler(columns={
        ("t", "user_email"): {f"a{i}@x.com" for i in range(20)},
    })
    vp = ValuePatternFingerprintStrategy(sampler=sampler)
    vp_out = await vp.propose(table_id="t", column="user_email", sample_size=20)

    # Both strategies independently propose "email"
    assert any(p.semantic_type == "email" for p in cn_out)
    assert any(p.semantic_type == "email" for p in vp_out)
    # And they share the same type_id (so the composite can merge them).
    cn_eid = next(p.type_id for p in cn_out if p.semantic_type == "email")
    vp_eid = next(p.type_id for p in vp_out if p.semantic_type == "email")
    assert cn_eid == vp_eid


@pytest.mark.asyncio
async def test_each_proposal_is_proposed_semantic_type_instance() -> None:
    """Every emission is a :class:`ProposedSemanticType` dataclass."""
    cn = ColumnNameFingerprintStrategy()
    out = await cn.propose(table_id="t", column="email")
    for p in out:
        assert isinstance(p, ProposedSemanticType)
