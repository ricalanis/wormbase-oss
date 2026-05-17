"""L4 Sub-wave A — three new lake-side schema-impact entry kinds.

Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=117.
Three kinds remain before the Wave F Addendum 1 ceiling at 120.

Pins three new payload classes for the L4 cross-axis lake loop that
proposes schema-evolution impacts on downstream tables/columns + the
admin lifecycle that confirms/rejects them:

* ``SchemaImpactProposedPayload`` (kind ``schema_impact_proposed``) —
  emitted by the L4 Compounding axis when a schema change in an
  upstream source propagates an impact to a downstream table/column.
* ``SchemaImpactConfirmedPayload`` (kind ``schema_impact_confirmed``) —
  operator approval of a previously-proposed impact.
* ``SchemaImpactRejectedPayload`` (kind ``schema_impact_rejected``) —
  operator rejection with a categorical reason.

These tests pin:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Roundtrip via ``model_dump`` → ``model_validate`` byte-equivalently
  for full-field and minimal-field payloads.
* Strict validation: ``confidence`` in [0.0, 1.0]; ``change_kind``
  pinned to the 3 documented values; ``impact_kind`` pinned to the 5
  documented values; ``reason`` pinned to the 5 documented values;
  non-empty ``impact_id`` / ``source_id`` / ``src_table`` /
  ``src_column`` / ``tgt_table_id`` / ``tgt_column`` / ``strategy``.
* ``upstream_lineage_edge_id`` is optional (None for type_coercion
  strategy proposals derived from sample-stats without an L3 edge).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    SchemaImpactConfirmedPayload,
    SchemaImpactProposedPayload,
    SchemaImpactRejectedPayload,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "schema_impact_proposed",
        "schema_impact_confirmed",
        "schema_impact_rejected",
    ],
)
def test_schema_impact_kind_registered(kind: str) -> None:
    """Each new L4 kind auto-registers in KIND_REGISTRY + ALL_KINDS."""
    assert kind in KIND_REGISTRY
    assert kind in ALL_KINDS


# ---------------------------------------------------------------------------
# SchemaImpactProposedPayload
# ---------------------------------------------------------------------------


def test_schema_impact_proposed_roundtrip_full() -> None:
    """Full payload survives model_dump → model_validate byte-equivalently."""
    p = SchemaImpactProposedPayload(
        impact_id="impact-abc-123",
        source_id="src-stripe-1",
        src_table="public.charges",
        src_column="amount_minor",
        change_kind="column_type_changed",
        impact_kind="tgt_column_type_mismatch",
        tgt_table_id="warehouse.fct_charges",
        tgt_column="amount_cents",
        upstream_lineage_edge_id="edge-stripe-charges-fct-charges",
        confidence=0.92,
        strategy="lineage_edge",
        reasoning=(
            "Upstream changed amount_minor from int → bigint; downstream "
            "fct_charges.amount_cents is still int and will overflow."
        ),
        evidence={
            "upstream_change_seq": 1234,
            "downstream_type": "INTEGER",
            "upstream_type": "BIGINT",
        },
    )
    assert SchemaImpactProposedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "schema_impact_proposed"


def test_schema_impact_proposed_roundtrip_minimal_no_upstream_edge() -> None:
    """``upstream_lineage_edge_id`` may be None (type_coercion strategy)."""
    p = SchemaImpactProposedPayload(
        impact_id="impact-type-coerce-1",
        source_id="src-postgres-1",
        src_table="public.orders",
        src_column="total",
        change_kind="column_type_changed",
        impact_kind="type_coercion_required",
        tgt_table_id="warehouse.dim_orders",
        tgt_column="total_cents",
        confidence=0.75,
        strategy="type_coercion",
        reasoning="Sample-stat detected type drift; no L3 edge confirmed yet.",
        evidence={"observed_types": ["numeric(10,2)", "bigint"]},
    )
    assert SchemaImpactProposedPayload.model_validate(p.model_dump()) == p
    assert p.upstream_lineage_edge_id is None


@pytest.mark.parametrize(
    "change_kind",
    [
        "column_added",
        "column_dropped",
        "column_type_changed",
    ],
)
def test_schema_impact_proposed_accepts_every_change_kind(change_kind: str) -> None:
    """Each documented change_kind enum value is accepted."""
    p = SchemaImpactProposedPayload(
        impact_id=f"impact-{change_kind}",
        source_id="src-1",
        src_table="t1",
        src_column="c1",
        change_kind=change_kind,  # type: ignore[arg-type]
        impact_kind="tgt_column_unaware",
        tgt_table_id="tgt-1",
        tgt_column="tc1",
        confidence=0.5,
        strategy="lineage_edge",
        reasoning="r",
        evidence={},
    )
    assert p.change_kind == change_kind


def test_schema_impact_proposed_rejects_invalid_change_kind() -> None:
    """An out-of-enum change_kind raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SchemaImpactProposedPayload(
            impact_id="impact-bogus",
            source_id="src-1",
            src_table="t1",
            src_column="c1",
            change_kind="bogus_change",  # type: ignore[arg-type]
            impact_kind="tgt_column_unaware",
            tgt_table_id="tgt-1",
            tgt_column="tc1",
            confidence=0.5,
            strategy="lineage_edge",
            reasoning="r",
            evidence={},
        )
    assert "change_kind" in str(exc.value).lower()


@pytest.mark.parametrize(
    "impact_kind",
    [
        "tgt_column_orphaned",
        "tgt_column_type_mismatch",
        "tgt_column_unaware",
        "dbt_test_breakage",
        "type_coercion_required",
    ],
)
def test_schema_impact_proposed_accepts_every_impact_kind(impact_kind: str) -> None:
    """Each documented impact_kind enum value is accepted."""
    p = SchemaImpactProposedPayload(
        impact_id=f"impact-{impact_kind}",
        source_id="src-1",
        src_table="t1",
        src_column="c1",
        change_kind="column_added",
        impact_kind=impact_kind,  # type: ignore[arg-type]
        tgt_table_id="tgt-1",
        tgt_column="tc1",
        confidence=0.5,
        strategy="lineage_edge",
        reasoning="r",
        evidence={},
    )
    assert p.impact_kind == impact_kind


def test_schema_impact_proposed_rejects_invalid_impact_kind() -> None:
    """An out-of-enum impact_kind raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SchemaImpactProposedPayload(
            impact_id="impact-bogus-impact",
            source_id="src-1",
            src_table="t1",
            src_column="c1",
            change_kind="column_added",
            impact_kind="bogus_impact",  # type: ignore[arg-type]
            tgt_table_id="tgt-1",
            tgt_column="tc1",
            confidence=0.5,
            strategy="lineage_edge",
            reasoning="r",
            evidence={},
        )
    assert "impact_kind" in str(exc.value).lower()


def test_schema_impact_proposed_rejects_confidence_above_unit() -> None:
    """confidence > 1.0 raises at validation time (strict gate at write)."""
    with pytest.raises(ValidationError) as exc:
        SchemaImpactProposedPayload(
            impact_id="impact-bad-conf",
            source_id="src-1",
            src_table="t1",
            src_column="c1",
            change_kind="column_added",
            impact_kind="tgt_column_unaware",
            tgt_table_id="tgt-1",
            tgt_column="tc1",
            confidence=1.5,
            strategy="lineage_edge",
            reasoning="r",
            evidence={},
        )
    assert "confidence" in str(exc.value)


def test_schema_impact_proposed_rejects_confidence_below_zero() -> None:
    """confidence < 0.0 also raises — symmetric guard."""
    with pytest.raises(ValidationError) as exc:
        SchemaImpactProposedPayload(
            impact_id="impact-neg-conf",
            source_id="src-1",
            src_table="t1",
            src_column="c1",
            change_kind="column_added",
            impact_kind="tgt_column_unaware",
            tgt_table_id="tgt-1",
            tgt_column="tc1",
            confidence=-0.01,
            strategy="lineage_edge",
            reasoning="r",
            evidence={},
        )
    assert "confidence" in str(exc.value)


def test_schema_impact_proposed_confidence_boundary_unit_values() -> None:
    """0.0 and 1.0 are valid (boundary inclusive — needed for
    deterministic-rule strategies like dbt_test)."""
    for c in (0.0, 1.0):
        p = SchemaImpactProposedPayload(
            impact_id=f"impact-bound-{c}",
            source_id="src-1",
            src_table="t1",
            src_column="c1",
            change_kind="column_added",
            impact_kind="tgt_column_unaware",
            tgt_table_id="tgt-1",
            tgt_column="tc1",
            confidence=c,
            strategy="dbt_test",
            reasoning="boundary",
            evidence={},
        )
        assert p.confidence == c


@pytest.mark.parametrize(
    "field_name",
    [
        "impact_id",
        "source_id",
        "src_table",
        "src_column",
        "tgt_table_id",
        "tgt_column",
        "strategy",
    ],
)
def test_schema_impact_proposed_rejects_empty_required_id(field_name: str) -> None:
    """Each non-empty ID field rejects the empty string at validation time."""
    kwargs = dict(
        impact_id="impact-1",
        source_id="src-1",
        src_table="t1",
        src_column="c1",
        change_kind="column_added",
        impact_kind="tgt_column_unaware",
        tgt_table_id="tgt-1",
        tgt_column="tc1",
        confidence=0.5,
        strategy="lineage_edge",
        reasoning="r",
        evidence={},
    )
    kwargs[field_name] = ""
    with pytest.raises(ValidationError) as exc:
        SchemaImpactProposedPayload(**kwargs)  # type: ignore[arg-type]
    assert field_name in str(exc.value)


# ---------------------------------------------------------------------------
# SchemaImpactConfirmedPayload
# ---------------------------------------------------------------------------


def test_schema_impact_confirmed_roundtrip_full() -> None:
    """Full payload with notes survives roundtrip."""
    p = SchemaImpactConfirmedPayload(
        impact_id="impact-abc-123",
        confirmed_by_person_id="person-uuid-1",
        notes="Verified the impact; downstream pipeline patched.",
    )
    assert SchemaImpactConfirmedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "schema_impact_confirmed"


def test_schema_impact_confirmed_minimal_no_notes() -> None:
    """notes is optional — default None."""
    p = SchemaImpactConfirmedPayload(
        impact_id="impact-abc-123",
        confirmed_by_person_id="person-uuid-1",
    )
    assert p.notes is None
    assert SchemaImpactConfirmedPayload.model_validate(p.model_dump()) == p


def test_schema_impact_confirmed_rejects_empty_impact_id() -> None:
    """impact_id must be non-empty."""
    with pytest.raises(ValidationError) as exc:
        SchemaImpactConfirmedPayload(
            impact_id="",
            confirmed_by_person_id="person-uuid-1",
        )
    assert "impact_id" in str(exc.value)


# ---------------------------------------------------------------------------
# SchemaImpactRejectedPayload
# ---------------------------------------------------------------------------


def test_schema_impact_rejected_roundtrip_full() -> None:
    """Full payload with notes + each enum reason survives roundtrip."""
    p = SchemaImpactRejectedPayload(
        impact_id="impact-abc-123",
        rejected_by_person_id="person-uuid-1",
        reason="false_positive",
        notes="Downstream table is being deprecated next week.",
    )
    assert SchemaImpactRejectedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "schema_impact_rejected"


@pytest.mark.parametrize(
    "reason",
    [
        "false_positive",
        "already_handled",
        "low_value",
        "out_of_scope",
        "other",
    ],
)
def test_schema_impact_rejected_accepts_every_enum_value(reason: str) -> None:
    """Each documented reason enum value is accepted."""
    p = SchemaImpactRejectedPayload(
        impact_id="impact-1",
        rejected_by_person_id="person-uuid-1",
        reason=reason,  # type: ignore[arg-type]
    )
    assert p.reason == reason


def test_schema_impact_rejected_rejects_invalid_reason() -> None:
    """An out-of-enum reason raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SchemaImpactRejectedPayload(
            impact_id="impact-1",
            rejected_by_person_id="person-uuid-1",
            reason="bogus_reason",  # type: ignore[arg-type]
        )
    assert "reason" in str(exc.value).lower()


def test_schema_impact_rejected_rejects_empty_impact_id() -> None:
    """impact_id must be non-empty (symmetric with confirmed)."""
    with pytest.raises(ValidationError) as exc:
        SchemaImpactRejectedPayload(
            impact_id="",
            rejected_by_person_id="person-uuid-1",
            reason="false_positive",
        )
    assert "impact_id" in str(exc.value)
