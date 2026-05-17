"""L7 Sub-wave A — three new lake-side quality-checks entry kinds.

Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=114.

Pins three new payload classes for the L7 compounding loop that proposes
quality checks on catalog tables/columns + the admin lifecycle that
confirms/rejects them:

* ``QualityCheckProposedPayload`` (kind ``quality_check_proposed``) —
  emitted by the inference-strategy Compounding axis with a candidate
  check on a catalog table/column.
* ``QualityCheckConfirmedPayload`` (kind ``quality_check_confirmed``) —
  operator approval of a previously-proposed check.
* ``QualityCheckRejectedPayload`` (kind ``quality_check_rejected``) —
  operator rejection with a categorical reason.

These tests pin:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Roundtrip via ``model_dump`` → ``model_validate`` byte-equivalently
  for full-field and minimal-field payloads.
* Strict validation: ``confidence`` in [0.0, 1.0]; ``reason`` enum
  pinned to the 5 documented values; ``check_kind`` enum pinned to
  the 7 documented values; non-empty ``check_id`` / ``table_id`` /
  ``strategy``.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    QualityCheckConfirmedPayload,
    QualityCheckProposedPayload,
    QualityCheckRejectedPayload,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "quality_check_proposed",
        "quality_check_confirmed",
        "quality_check_rejected",
    ],
)
def test_quality_check_kind_registered(kind: str) -> None:
    """Each new L7 kind auto-registers in KIND_REGISTRY + ALL_KINDS."""
    assert kind in KIND_REGISTRY
    assert kind in ALL_KINDS


# ---------------------------------------------------------------------------
# QualityCheckProposedPayload
# ---------------------------------------------------------------------------


def test_quality_check_proposed_roundtrip_full() -> None:
    """Full payload survives model_dump → model_validate byte-equivalently."""
    p = QualityCheckProposedPayload(
        check_id="check-abc-123",
        table_id="src-1.public.orders",
        column="customer_id",
        check_kind="not_null",
        config={"threshold": 0.99},
        confidence=0.95,
        strategy="historical_stats",
        reasoning=(
            "99.8% non-null ratio observed across 10K sampled rows; "
            "below-threshold violations are anomalous."
        ),
        evidence={
            "non_null_ratio": 0.998,
            "sampled_n": 10000,
            "nulls_seen": 20,
        },
    )
    assert QualityCheckProposedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "quality_check_proposed"


def test_quality_check_proposed_roundtrip_table_level_check() -> None:
    """column may be None (table-level check — e.g. row_count_range)."""
    p = QualityCheckProposedPayload(
        check_id="check-table-level",
        table_id="src-1.public.orders",
        column=None,
        check_kind="row_count_range",
        config={"min_rows": 1000, "max_rows": 100000},
        confidence=0.85,
        strategy="dbt_tests",
        reasoning="dbt schema.yml declares row count expectation.",
        evidence={"dbt_test_name": "expect_row_count_range"},
    )
    assert QualityCheckProposedPayload.model_validate(p.model_dump()) == p
    assert p.column is None


@pytest.mark.parametrize(
    "check_kind",
    [
        "not_null",
        "unique",
        "freshness",
        "row_count_range",
        "enum_membership",
        "type_stability",
        "value_range",
    ],
)
def test_quality_check_proposed_accepts_every_check_kind(check_kind: str) -> None:
    """Each documented check_kind enum value is accepted."""
    p = QualityCheckProposedPayload(
        check_id=f"check-{check_kind}",
        table_id="t1",
        column="c1",
        check_kind=check_kind,  # type: ignore[arg-type]
        config={},
        confidence=0.5,
        strategy="schema_pattern",
        reasoning="r",
        evidence={},
    )
    assert p.check_kind == check_kind


def test_quality_check_proposed_rejects_invalid_check_kind() -> None:
    """An out-of-enum check_kind raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        QualityCheckProposedPayload(
            check_id="check-bogus-kind",
            table_id="t1",
            column=None,
            check_kind="bogus_kind",  # type: ignore[arg-type]
            config={},
            confidence=0.5,
            strategy="schema_pattern",
            reasoning="r",
            evidence={},
        )
    assert "check_kind" in str(exc.value).lower()


def test_quality_check_proposed_rejects_confidence_above_unit() -> None:
    """confidence > 1.0 raises at validation time (strict gate at write)."""
    with pytest.raises(ValidationError) as exc:
        QualityCheckProposedPayload(
            check_id="check-bad",
            table_id="t1",
            column=None,
            check_kind="not_null",
            config={},
            confidence=1.5,
            strategy="schema_pattern",
            reasoning="r",
            evidence={},
        )
    assert "confidence" in str(exc.value)


def test_quality_check_proposed_rejects_confidence_below_zero() -> None:
    """confidence < 0.0 also raises — symmetric guard."""
    with pytest.raises(ValidationError) as exc:
        QualityCheckProposedPayload(
            check_id="check-bad",
            table_id="t1",
            column=None,
            check_kind="not_null",
            config={},
            confidence=-0.01,
            strategy="schema_pattern",
            reasoning="r",
            evidence={},
        )
    assert "confidence" in str(exc.value)


def test_quality_check_proposed_rejects_empty_check_id() -> None:
    """check_id must be non-empty (strict, payload-side)."""
    with pytest.raises(ValidationError) as exc:
        QualityCheckProposedPayload(
            check_id="",
            table_id="t1",
            column=None,
            check_kind="not_null",
            config={},
            confidence=0.5,
            strategy="schema_pattern",
            reasoning="r",
            evidence={},
        )
    assert "check_id" in str(exc.value)


def test_quality_check_proposed_rejects_empty_table_id() -> None:
    """table_id must be non-empty."""
    with pytest.raises(ValidationError) as exc:
        QualityCheckProposedPayload(
            check_id="check-1",
            table_id="",
            column=None,
            check_kind="not_null",
            config={},
            confidence=0.5,
            strategy="schema_pattern",
            reasoning="r",
            evidence={},
        )
    assert "table_id" in str(exc.value)


def test_quality_check_proposed_rejects_empty_strategy() -> None:
    """strategy must be non-empty (the keying field for strategy
    telemetry; an empty string is operator surface noise)."""
    with pytest.raises(ValidationError) as exc:
        QualityCheckProposedPayload(
            check_id="check-1",
            table_id="t1",
            column=None,
            check_kind="not_null",
            config={},
            confidence=0.5,
            strategy="",
            reasoning="r",
            evidence={},
        )
    assert "strategy" in str(exc.value)


def test_quality_check_proposed_confidence_boundary_unit_values() -> None:
    """0.0 and 1.0 are valid (boundary inclusive — needed for
    deterministic-rule strategies like dbt_tests)."""
    for c in (0.0, 1.0):
        p = QualityCheckProposedPayload(
            check_id=f"check-{c}",
            table_id="t1",
            column=None,
            check_kind="not_null",
            config={},
            confidence=c,
            strategy="dbt_tests",
            reasoning="boundary",
            evidence={},
        )
        assert p.confidence == c


# ---------------------------------------------------------------------------
# QualityCheckConfirmedPayload
# ---------------------------------------------------------------------------


def test_quality_check_confirmed_roundtrip_full() -> None:
    """Full payload with notes survives roundtrip."""
    p = QualityCheckConfirmedPayload(
        check_id="check-abc-123",
        confirmed_by_person_id="person-uuid-1",
        notes="Verified the non-null contract via staging.",
    )
    assert QualityCheckConfirmedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "quality_check_confirmed"


def test_quality_check_confirmed_minimal_no_notes() -> None:
    """notes is optional — default None."""
    p = QualityCheckConfirmedPayload(
        check_id="check-abc-123",
        confirmed_by_person_id="person-uuid-1",
    )
    assert p.notes is None
    assert QualityCheckConfirmedPayload.model_validate(p.model_dump()) == p


def test_quality_check_confirmed_rejects_empty_check_id() -> None:
    """check_id must be non-empty."""
    with pytest.raises(ValidationError) as exc:
        QualityCheckConfirmedPayload(
            check_id="",
            confirmed_by_person_id="person-uuid-1",
        )
    assert "check_id" in str(exc.value)


# ---------------------------------------------------------------------------
# QualityCheckRejectedPayload
# ---------------------------------------------------------------------------


def test_quality_check_rejected_roundtrip_full() -> None:
    """Full payload with notes + each enum reason survives roundtrip."""
    p = QualityCheckRejectedPayload(
        check_id="check-abc-123",
        rejected_by_person_id="person-uuid-1",
        reason="false_positive",
        notes="Column is intentionally sparse; non-null check is wrong.",
    )
    assert QualityCheckRejectedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "quality_check_rejected"


@pytest.mark.parametrize(
    "reason",
    [
        "false_positive",
        "low_value",
        "wrong_threshold",
        "out_of_scope",
        "other",
    ],
)
def test_quality_check_rejected_accepts_every_enum_value(reason: str) -> None:
    """Each documented reason enum value is accepted."""
    p = QualityCheckRejectedPayload(
        check_id="check-1",
        rejected_by_person_id="person-uuid-1",
        reason=reason,  # type: ignore[arg-type]
    )
    assert p.reason == reason


def test_quality_check_rejected_rejects_invalid_reason() -> None:
    """An out-of-enum reason raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        QualityCheckRejectedPayload(
            check_id="check-1",
            rejected_by_person_id="person-uuid-1",
            reason="bogus_reason",  # type: ignore[arg-type]
        )
    assert "reason" in str(exc.value).lower()


def test_quality_check_rejected_rejects_empty_check_id() -> None:
    """check_id must be non-empty (symmetric with confirmed)."""
    with pytest.raises(ValidationError) as exc:
        QualityCheckRejectedPayload(
            check_id="",
            rejected_by_person_id="person-uuid-1",
            reason="false_positive",
        )
    assert "check_id" in str(exc.value)
