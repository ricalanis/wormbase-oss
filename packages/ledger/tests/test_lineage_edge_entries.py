"""L3 Sub-wave A — three new lake-side lineage-discovery entry kinds.

Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=109.

Pins three new payload classes for the L3 compounding loop that proposes
catalog lineage edges + the admin lifecycle that confirms/rejects them:

* ``LineageEdgeProposedPayload`` (kind ``lineage_edge_proposed``) —
  emitted by the inference-strategy Compounding axis with a candidate
  edge between two catalog tables/columns.
* ``LineageEdgeConfirmedPayload`` (kind ``lineage_edge_confirmed``) —
  operator approval of a previously-proposed edge.
* ``LineageEdgeRejectedPayload`` (kind ``lineage_edge_rejected``) —
  operator rejection with a categorical reason.

These tests pin:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Roundtrip via ``model_dump`` → ``model_validate`` byte-equivalently
  for full-field and minimal-field payloads.
* Strict validation: ``confidence`` in [0.0, 1.0]; ``reason`` enum
  pinned to the 5 documented values; non-empty ``edge_id`` /
  ``src_table_id`` / ``tgt_table_id`` / ``strategy``.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    LineageEdgeConfirmedPayload,
    LineageEdgeProposedPayload,
    LineageEdgeRejectedPayload,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "lineage_edge_proposed",
        "lineage_edge_confirmed",
        "lineage_edge_rejected",
    ],
)
def test_lineage_edge_kind_registered(kind: str) -> None:
    """Each new L3 kind auto-registers in KIND_REGISTRY + ALL_KINDS."""
    assert kind in KIND_REGISTRY
    assert kind in ALL_KINDS


# ---------------------------------------------------------------------------
# LineageEdgeProposedPayload
# ---------------------------------------------------------------------------


def test_lineage_edge_proposed_roundtrip_full() -> None:
    """Full payload survives model_dump → model_validate byte-equivalently."""
    p = LineageEdgeProposedPayload(
        edge_id="edge-abc-123",
        src_table_id="src-1.public.orders",
        src_column="customer_id",
        tgt_table_id="src-2.public.customers",
        tgt_column="id",
        confidence=0.87,
        strategy="sample_overlap",
        reasoning=(
            "87% Jaccard overlap on 1000 sampled values; both columns "
            "carry the same canonical pattern."
        ),
        evidence={
            "sample_overlap_ratio": 0.87,
            "sampled_n": 1000,
            "values_in_common": 870,
        },
    )
    assert LineageEdgeProposedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "lineage_edge_proposed"


def test_lineage_edge_proposed_roundtrip_whole_table_edge() -> None:
    """src_column / tgt_column may be None (whole-table edge)."""
    p = LineageEdgeProposedPayload(
        edge_id="edge-whole-tbl",
        src_table_id="src-1.public.orders",
        src_column=None,
        tgt_table_id="src-1.staging.stg_orders",
        tgt_column=None,
        confidence=1.0,
        strategy="dbt_manifest",
        reasoning="Explicit dbt ref() between source and staging model.",
        evidence={"manifest_path": "models/staging/stg_orders.sql"},
    )
    assert LineageEdgeProposedPayload.model_validate(p.model_dump()) == p


def test_lineage_edge_proposed_rejects_confidence_above_unit() -> None:
    """confidence > 1.0 raises at validation time (strict gate at write)."""
    with pytest.raises(ValidationError) as exc:
        LineageEdgeProposedPayload(
            edge_id="edge-bad",
            src_table_id="t1",
            src_column=None,
            tgt_table_id="t2",
            tgt_column=None,
            confidence=1.5,
            strategy="naming_heuristic",
            reasoning="r",
            evidence={},
        )
    assert "confidence" in str(exc.value)


def test_lineage_edge_proposed_rejects_confidence_below_zero() -> None:
    """confidence < 0.0 also raises — symmetric guard."""
    with pytest.raises(ValidationError) as exc:
        LineageEdgeProposedPayload(
            edge_id="edge-bad",
            src_table_id="t1",
            src_column=None,
            tgt_table_id="t2",
            tgt_column=None,
            confidence=-0.01,
            strategy="naming_heuristic",
            reasoning="r",
            evidence={},
        )
    assert "confidence" in str(exc.value)


def test_lineage_edge_proposed_rejects_empty_edge_id() -> None:
    """edge_id must be non-empty (strict, payload-side)."""
    with pytest.raises(ValidationError) as exc:
        LineageEdgeProposedPayload(
            edge_id="",
            src_table_id="t1",
            src_column=None,
            tgt_table_id="t2",
            tgt_column=None,
            confidence=0.5,
            strategy="naming_heuristic",
            reasoning="r",
            evidence={},
        )
    assert "edge_id" in str(exc.value)


def test_lineage_edge_proposed_rejects_empty_table_ids() -> None:
    """src/tgt table ids must be non-empty."""
    with pytest.raises(ValidationError):
        LineageEdgeProposedPayload(
            edge_id="edge-1",
            src_table_id="",
            src_column=None,
            tgt_table_id="t2",
            tgt_column=None,
            confidence=0.5,
            strategy="naming_heuristic",
            reasoning="r",
            evidence={},
        )
    with pytest.raises(ValidationError):
        LineageEdgeProposedPayload(
            edge_id="edge-1",
            src_table_id="t1",
            src_column=None,
            tgt_table_id="",
            tgt_column=None,
            confidence=0.5,
            strategy="naming_heuristic",
            reasoning="r",
            evidence={},
        )


def test_lineage_edge_proposed_rejects_empty_strategy() -> None:
    """strategy must be non-empty (it's the keying field for strategy
    telemetry; an empty string is operator surface noise)."""
    with pytest.raises(ValidationError) as exc:
        LineageEdgeProposedPayload(
            edge_id="edge-1",
            src_table_id="t1",
            src_column=None,
            tgt_table_id="t2",
            tgt_column=None,
            confidence=0.5,
            strategy="",
            reasoning="r",
            evidence={},
        )
    assert "strategy" in str(exc.value)


def test_lineage_edge_proposed_confidence_boundary_unit_values() -> None:
    """0.0 and 1.0 are valid (boundary inclusive — needed for
    deterministic-rule strategies like dbt_manifest)."""
    for c in (0.0, 1.0):
        p = LineageEdgeProposedPayload(
            edge_id=f"edge-{c}",
            src_table_id="t1",
            src_column=None,
            tgt_table_id="t2",
            tgt_column=None,
            confidence=c,
            strategy="dbt_manifest",
            reasoning="boundary",
            evidence={},
        )
        assert p.confidence == c


# ---------------------------------------------------------------------------
# LineageEdgeConfirmedPayload
# ---------------------------------------------------------------------------


def test_lineage_edge_confirmed_roundtrip_full() -> None:
    """Full payload with notes survives roundtrip."""
    p = LineageEdgeConfirmedPayload(
        edge_id="edge-abc-123",
        confirmed_by_person_id="person-uuid-1",
        notes="Verified via the staging pipeline.",
    )
    assert LineageEdgeConfirmedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "lineage_edge_confirmed"


def test_lineage_edge_confirmed_minimal_no_notes() -> None:
    """notes is optional — default None."""
    p = LineageEdgeConfirmedPayload(
        edge_id="edge-abc-123",
        confirmed_by_person_id="person-uuid-1",
    )
    assert p.notes is None
    assert LineageEdgeConfirmedPayload.model_validate(p.model_dump()) == p


def test_lineage_edge_confirmed_rejects_empty_edge_id() -> None:
    """edge_id must be non-empty."""
    with pytest.raises(ValidationError) as exc:
        LineageEdgeConfirmedPayload(
            edge_id="",
            confirmed_by_person_id="person-uuid-1",
        )
    assert "edge_id" in str(exc.value)


# ---------------------------------------------------------------------------
# LineageEdgeRejectedPayload
# ---------------------------------------------------------------------------


def test_lineage_edge_rejected_roundtrip_full() -> None:
    """Full payload with notes + each enum reason survives roundtrip."""
    p = LineageEdgeRejectedPayload(
        edge_id="edge-abc-123",
        rejected_by_person_id="person-uuid-1",
        reason="false_positive",
        notes="Columns happen to share a 0-100 integer range; not joinable.",
    )
    assert LineageEdgeRejectedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "lineage_edge_rejected"


@pytest.mark.parametrize(
    "reason",
    [
        "false_positive",
        "wrong_direction",
        "low_confidence",
        "out_of_scope",
        "other",
    ],
)
def test_lineage_edge_rejected_accepts_every_enum_value(reason: str) -> None:
    """Each documented reason enum value is accepted."""
    p = LineageEdgeRejectedPayload(
        edge_id="edge-1",
        rejected_by_person_id="person-uuid-1",
        reason=reason,  # type: ignore[arg-type]
    )
    assert p.reason == reason


def test_lineage_edge_rejected_rejects_invalid_reason() -> None:
    """An out-of-enum reason raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        LineageEdgeRejectedPayload(
            edge_id="edge-1",
            rejected_by_person_id="person-uuid-1",
            reason="bogus_reason",  # type: ignore[arg-type]
        )
    assert "reason" in str(exc.value).lower()


def test_lineage_edge_rejected_rejects_empty_edge_id() -> None:
    """edge_id must be non-empty (symmetric with confirmed)."""
    with pytest.raises(ValidationError) as exc:
        LineageEdgeRejectedPayload(
            edge_id="",
            rejected_by_person_id="person-uuid-1",
            reason="false_positive",
        )
    assert "edge_id" in str(exc.value)
