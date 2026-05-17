"""L5 Sub-wave B — protocol/dataclass tests.

Pins:

  * :func:`make_type_id` determinism / replay stability.
  * Per-tuple distinguishability (every component of the canonical
    tuple affects the hash; ``confidence`` + ``strategy`` are NOT in
    the hash so multi-strategy proposals can merge).
  * Each strategy implements the :class:`FingerprintStrategy` Protocol
    (runtime_checkable).
  * :data:`SemanticType` Literal covers exactly the 19 spec values
    (mirrors the ledger payload).
  * :class:`ProposedSemanticType` is frozen.
"""
from __future__ import annotations

import typing

import pytest

from wormbase_agent_gateway.semantic_type import (
    ColumnNameFingerprintStrategy,
    DistributionFingerprintStrategy,
    FingerprintStrategy,
    ProposedSemanticType,
    SemanticType,
    ValuePatternFingerprintStrategy,
    make_type_id,
)


# ---------------------------------------------------------------------------
# make_type_id — determinism + distinguishability
# ---------------------------------------------------------------------------


def test_make_type_id_is_deterministic() -> None:
    """Same inputs → same type_id across calls (replay-stable)."""
    a = make_type_id(
        table_id="src-001.public.users",
        column="email",
        semantic_type="email",
    )
    b = make_type_id(
        table_id="src-001.public.users",
        column="email",
        semantic_type="email",
    )
    assert a == b
    assert len(a) == 32
    assert all(c in "0123456789abcdef" for c in a)


def test_make_type_id_distinguishes_every_tuple_component() -> None:
    """Each of the 3 inputs participates in the hash distinctly."""
    base = dict(
        table_id="src-001.public.users",
        column="email",
        semantic_type="email",
    )
    base_id = make_type_id(**base)
    for key, mutated in [
        ("table_id", "src-001.public.other"),
        ("column", "other"),
        ("semantic_type", "pii_name"),
    ]:
        kwargs = dict(base)
        kwargs[key] = mutated
        assert make_type_id(**kwargs) != base_id, (
            f"type_id collided when mutating {key}"
        )


def test_make_type_id_distinct_semantic_types_yield_distinct_ids() -> None:
    """Same (table_id, column) but different semantic_type → different id.

    This is critical: it ensures multiple strategies that propose
    different semantic_types for the same column produce different
    type_ids (each ledgered as its own proposal row).
    """
    a = make_type_id(
        table_id="t1", column="c1", semantic_type="email",
    )
    b = make_type_id(
        table_id="t1", column="c1", semantic_type="pii_name",
    )
    assert a != b


def test_make_type_id_omits_confidence_and_strategy_from_hash() -> None:
    """``confidence`` + ``strategy`` are deliberately NOT in the hash.

    Two strategies proposing the same (table_id, column, semantic_type)
    MUST produce identical type_ids so the composite can merge them.
    The signature explicitly takes only the 3 tuple components.
    """
    # Smoke-test via the public signature: no kw for confidence/strategy.
    import inspect
    sig = inspect.signature(make_type_id)
    assert set(sig.parameters) == {"table_id", "column", "semantic_type"}


# ---------------------------------------------------------------------------
# SemanticType Literal — 19 canonical values
# ---------------------------------------------------------------------------


EXPECTED_SEMANTIC_TYPE_VALUES: frozenset[str] = frozenset({
    # Identity
    "email", "phone_e164", "phone_us",
    # Temporal
    "iso_date", "iso_datetime", "unix_timestamp",
    # Identifiers
    "uuid_v4", "uuid_v7", "business_id",
    # Geo/locale
    "country_iso", "language_iso", "currency_iso",
    # PII
    "pii_name", "pii_address", "pii_ssn", "pii_credit_card",
    # Metric
    "metric_count", "metric_amount", "metric_rate",
    # Catch-all
    "other",
})


def test_semantic_type_literal_covers_canonical_spec_values() -> None:
    """:data:`SemanticType` is a Literal with exactly the 19 spec values
    plus the ``other`` catch-all (20 total — mirrors the ledger payload).

    Pin: mirrors the ledger payload's Literal (see
    :attr:`wormbase_ledger.entries.SemanticTypeProposedPayload.semantic_type`).
    Drift here must be matched by a ledger migration.
    """
    args = typing.get_args(SemanticType)
    actual = frozenset(args)
    assert actual == EXPECTED_SEMANTIC_TYPE_VALUES, (
        f"SemanticType Literal drift: "
        f"extra={actual - EXPECTED_SEMANTIC_TYPE_VALUES}, "
        f"missing={EXPECTED_SEMANTIC_TYPE_VALUES - actual}"
    )
    # 19 productive types + 1 catch-all = 20.
    assert len(args) == 20
    assert "other" in actual


# ---------------------------------------------------------------------------
# FingerprintStrategy Protocol — runtime conformance
# ---------------------------------------------------------------------------


def test_strategies_satisfy_fingerprint_strategy_protocol() -> None:
    """All 3 strategies are instances of :class:`FingerprintStrategy` per
    ``runtime_checkable``."""

    class _FakeSampler:
        async def sample_column(self, table_id, column, n):
            return set()

        async def estimate_table_size(self, table_id):
            return 0

    class _FakeStatsReader:
        async def get_snapshots_for_table(self, table_id):
            return []

    cn = ColumnNameFingerprintStrategy()
    vp = ValuePatternFingerprintStrategy(sampler=_FakeSampler())
    dist = DistributionFingerprintStrategy(stats_reader=_FakeStatsReader())

    for service in (cn, vp, dist):
        assert isinstance(service, FingerprintStrategy), (
            f"{type(service).__name__} does not satisfy FingerprintStrategy"
        )
        assert hasattr(service, "name")
        assert isinstance(service.name, str)


def test_strategy_names_match_spec() -> None:
    """Strategy ``name`` attributes match the spec's canonical identifiers."""
    assert ColumnNameFingerprintStrategy.name == "column_name"
    assert ValuePatternFingerprintStrategy.name == "value_pattern"
    assert DistributionFingerprintStrategy.name == "distribution"


# ---------------------------------------------------------------------------
# Dataclass shape + frozenness
# ---------------------------------------------------------------------------


def test_proposed_semantic_type_is_frozen() -> None:
    """:class:`ProposedSemanticType` is a frozen dataclass."""
    p = ProposedSemanticType(
        type_id="abc",
        table_id="t1",
        column="c1",
        semantic_type="email",
        confidence=0.85,
        strategy="column_name",
        reasoning="test",
        evidence={},
    )
    try:
        p.type_id = "modified"  # type: ignore[misc]
    except (AttributeError, Exception):
        pass
    else:
        raise AssertionError("ProposedSemanticType should be frozen")


def test_proposed_semantic_type_field_surface() -> None:
    """:class:`ProposedSemanticType` carries the documented 8 fields."""
    p = ProposedSemanticType(
        type_id="abc",
        table_id="t1",
        column="c1",
        semantic_type="email",
        confidence=0.85,
        strategy="column_name",
        reasoning="test",
        evidence={"k": "v"},
    )
    expected = {
        "type_id", "table_id", "column", "semantic_type",
        "confidence", "strategy", "reasoning", "evidence",
    }
    actual = set(p.__dataclass_fields__)
    assert actual == expected, (
        f"ProposedSemanticType field surface drift: "
        f"extra={actual - expected}, missing={expected - actual}"
    )


@pytest.mark.asyncio
async def test_fingerprint_strategy_protocol_async_propose() -> None:
    """A fingerprint strategy's ``propose`` is async + returns proposals."""
    cn = ColumnNameFingerprintStrategy()
    out = await cn.propose(
        table_id="src-001.public.users", column="email",
    )
    assert isinstance(out, list)
    assert all(isinstance(p, ProposedSemanticType) for p in out)
