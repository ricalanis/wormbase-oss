"""L5 Sub-wave B — composite tests.

Pins the L5-specific wiring of the shared :class:`LakeLoopComposite`:

  * Factory returns a :class:`LakeLoopComposite` (not a custom class).
  * Optional-Effect Injection case 12: each slot independently
    ``None``-able; all-None yields ``[]`` + ``no_op`` counter.
  * Telemetry keys are axis-namespaced: ``fingerprint_inference_*``.
  * Merge dedup by ``type_id``: two strategies proposing the same
    ``(table_id, column, semantic_type)`` → 1 merged proposal.
  * Strategy execution order: column_name → value_pattern → distribution.

Minimal — the generic shape is already pinned by
``test_lake_loop_composite.py`` and the three pre-extraction axes.
"""
from __future__ import annotations

import pytest

from wormbase_agent_gateway.lake_loop import LakeLoopComposite
from wormbase_agent_gateway.semantic_type import (
    ColumnNameFingerprintStrategy,
    ProposedSemanticType,
    ValuePatternFingerprintStrategy,
    make_composite_semantic_type_service,
    make_type_id,
)


class _FakeSampler:
    def __init__(self, samples: dict[tuple[str, str], set[str]] | None = None) -> None:
        self.samples = samples or {}

    async def sample_column(self, table_id, column, n):
        return self.samples.get((table_id, column), set())

    async def estimate_table_size(self, table_id):
        return 0


# ---------------------------------------------------------------------------
# Factory shape — validates LakeLoopComposite reuse
# ---------------------------------------------------------------------------


def test_factory_returns_lake_loop_composite_instance() -> None:
    """The smoking-gun validation: composite IS a :class:`LakeLoopComposite`.

    Pin: L5 does NOT define a custom composite class. The factory
    function delegates entirely to the shared generic. Validates the
    DRY refactor at ``a4a62c2`` pays off for new consumers.
    """
    composite = make_composite_semantic_type_service()
    assert isinstance(composite, LakeLoopComposite)


def test_factory_uses_fingerprint_inference_case_name() -> None:
    """Composite's case_name is ``fingerprint_inference``."""
    composite = make_composite_semantic_type_service()
    assert composite.case_name == "fingerprint_inference"


def test_factory_strategy_slots_match_spec() -> None:
    """Strategy slots are ``column_name`` / ``value_pattern`` / ``distribution``
    in declaration order."""
    composite = make_composite_semantic_type_service()
    slots = list(composite.strategies)
    assert slots == ["column_name", "value_pattern", "distribution"]


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_all_none_returns_empty_and_counts_no_op() -> None:
    """All strategy slots None → empty proposal list + no_op counter."""
    composite = make_composite_semantic_type_service()
    proposals = await composite.propose(
        table_id="src-001.public.users", column="email",
    )
    assert proposals == []
    metrics = composite.metrics()
    assert metrics["fingerprint_inference_invocations"] == 1
    assert metrics["fingerprint_inference_no_op"] == 1
    assert metrics["fingerprint_inference_types_proposed"] == 0
    assert metrics["fingerprint_inference_strategy_invocations.column_name"] == 0
    assert metrics["fingerprint_inference_strategy_invocations.value_pattern"] == 0
    assert metrics["fingerprint_inference_strategy_invocations.distribution"] == 0


@pytest.mark.asyncio
async def test_composite_only_column_name_runs() -> None:
    """``column_name`` set, others None → only that counter increments."""
    composite = make_composite_semantic_type_service(
        column_name=ColumnNameFingerprintStrategy(),
    )
    proposals = await composite.propose(
        table_id="t", column="email",
    )
    assert len(proposals) == 1
    assert proposals[0].semantic_type == "email"
    metrics = composite.metrics()
    assert metrics["fingerprint_inference_strategy_invocations.column_name"] == 1
    assert metrics["fingerprint_inference_strategy_invocations.value_pattern"] == 0
    assert metrics["fingerprint_inference_strategy_invocations.distribution"] == 0
    assert metrics["fingerprint_inference_no_op"] == 0


@pytest.mark.asyncio
async def test_composite_merge_dedup_when_two_strategies_propose_same_type() -> None:
    """ColumnName + ValuePattern both propose email for same (table, column)
    → 1 merged proposal labelled ``composite``."""
    sampler = _FakeSampler(samples={
        ("t", "user_email"): {f"a{i}@x.com" for i in range(20)},
    })
    composite = make_composite_semantic_type_service(
        column_name=ColumnNameFingerprintStrategy(),
        value_pattern=ValuePatternFingerprintStrategy(sampler=sampler),
    )
    proposals = await composite.propose(
        table_id="t", column="user_email", sample_size=20,
    )
    # 1 email proposal — the two strategies merged on the same type_id.
    email_props = [p for p in proposals if p.semantic_type == "email"]
    assert len(email_props) == 1
    p = email_props[0]
    assert p.strategy == "composite"
    # Composite reasoning concatenates both strategies' explanations.
    assert "column-name regex" in p.reasoning
    assert "value_pattern" in p.reasoning or "RFC5322" in p.reasoning
    # Both per-strategy evidences preserved
    assert "column_name" in p.evidence
    assert "value_pattern" in p.evidence


@pytest.mark.asyncio
async def test_composite_max_confidence_wins_on_merge() -> None:
    """Merged proposal carries max confidence from the contributors."""
    sampler = _FakeSampler(samples={
        ("t", "email"): {f"a{i}@x.com" for i in range(20)},
    })
    composite = make_composite_semantic_type_service(
        column_name=ColumnNameFingerprintStrategy(),
        value_pattern=ValuePatternFingerprintStrategy(sampler=sampler),
    )
    proposals = await composite.propose(
        table_id="t", column="email", sample_size=20,
    )
    email_props = [p for p in proposals if p.semantic_type == "email"]
    assert len(email_props) == 1
    # column_name "email" exact: 0.90; value_pattern email: 0.95.
    # Max = 0.95.
    assert email_props[0].confidence == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_composite_type_id_is_canonical_hash() -> None:
    """Composite proposal's ``type_id`` matches :func:`make_type_id`."""
    composite = make_composite_semantic_type_service(
        column_name=ColumnNameFingerprintStrategy(),
    )
    proposals = await composite.propose(
        table_id="t", column="email",
    )
    p = proposals[0]
    expected = make_type_id(
        table_id="t", column="email", semantic_type="email",
    )
    assert p.type_id == expected


@pytest.mark.asyncio
async def test_composite_strategy_returns_empty_no_op_not_incremented() -> None:
    """Strategy wired but returns [] → no proposals, but no_op NOT fired."""
    composite = make_composite_semantic_type_service(
        column_name=ColumnNameFingerprintStrategy(),
    )
    proposals = await composite.propose(table_id="t", column="xyzzy_blob_42")
    assert proposals == []
    metrics = composite.metrics()
    # Strategy ran (counter = 1) but produced nothing — not a no-op.
    assert metrics["fingerprint_inference_strategy_invocations.column_name"] == 1
    assert metrics["fingerprint_inference_no_op"] == 0
    assert metrics["fingerprint_inference_types_proposed"] == 0


@pytest.mark.asyncio
async def test_composite_returns_proposed_semantic_type_instances() -> None:
    """Composite output is a list of :class:`ProposedSemanticType`."""
    composite = make_composite_semantic_type_service(
        column_name=ColumnNameFingerprintStrategy(),
    )
    out = await composite.propose(table_id="t", column="email")
    assert isinstance(out, list)
    assert all(isinstance(p, ProposedSemanticType) for p in out)
