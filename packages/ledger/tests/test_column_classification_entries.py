"""L6 Sub-wave A — three new lake-side column-classification entry kinds.

Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=123.
27 kinds remain before the Wave F Addendum 4 ceiling at 150. L-axis
family count = 15 of 30 cap (L3=3 + L7=3 + L4=3 + L5=3 + L6=3) per
Addendum 4 §E — well within cap.

Pins three new payload classes for the L6 lake loop that proposes
column-level governance classifications + the admin lifecycle that
confirms/rejects them. L6 is the 5th lake-side compounding axis AND
the 2nd cross-axis chain (after L4→L3) — the ``semantic_type``
strategy reads L5's confirmed semantic types and threads the
``upstream_semantic_type_id`` field back into the proposal.

* ``ColumnClassificationProposedPayload`` (kind
  ``column_classification_proposed``) — emitted by the L6
  Compounding axis when a strategy proposes a classification level
  for a column (e.g. inferred PII → ``regulated``).
* ``ColumnClassificationConfirmedPayload`` (kind
  ``column_classification_confirmed``) — operator approval of a
  previously-proposed classification.
* ``ColumnClassificationRejectedPayload`` (kind
  ``column_classification_rejected``) — operator rejection with a
  categorical reason. The L6-specific 5th reason is ``wrong_level``
  (distinct from L5's ``wrong_type``, L4's ``already_handled`` and
  L7's ``wrong_threshold``).

These tests pin:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Roundtrip via ``model_dump`` → ``model_validate`` byte-equivalently
  for full-field and minimal-field payloads.
* Strict validation: ``confidence`` in [0.0, 1.0];
  ``classification_level`` pinned to the 5 canonical governance
  levels per CLAUDE.md §"Ledger-native governance"; ``reason`` pinned
  to the 5 documented values; non-empty ``classification_id`` /
  ``table_id`` / ``column`` / ``strategy``.
* ``upstream_semantic_type_id`` accepts None (for naming_pattern /
  domain_default strategies that don't consult L5) and string values
  (for the semantic_type strategy — the L6→L5 cross-axis chain).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    ColumnClassificationConfirmedPayload,
    ColumnClassificationProposedPayload,
    ColumnClassificationRejectedPayload,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "column_classification_proposed",
        "column_classification_confirmed",
        "column_classification_rejected",
    ],
)
def test_column_classification_kind_registered(kind: str) -> None:
    """Each new L6 kind auto-registers in KIND_REGISTRY + ALL_KINDS."""
    assert kind in KIND_REGISTRY
    assert kind in ALL_KINDS


# ---------------------------------------------------------------------------
# ColumnClassificationProposedPayload
# ---------------------------------------------------------------------------


def test_column_classification_proposed_roundtrip_full() -> None:
    """Full payload (with cross-axis upstream link) survives model_dump
    → model_validate byte-equivalently."""
    p = ColumnClassificationProposedPayload(
        classification_id="cls-abc-123",
        table_id="warehouse.dim_users",
        column="ssn",
        classification_level="regulated",
        upstream_semantic_type_id="type-pii-ssn-1",
        confidence=0.95,
        strategy="semantic_type",
        reasoning="L5 confirmed semantic type pii_ssn → governance regulated",
        evidence={
            "upstream_semantic_type": "pii_ssn",
            "upstream_confidence": 0.97,
        },
    )
    assert (
        ColumnClassificationProposedPayload.model_validate(p.model_dump()) == p
    )
    assert p.kind == "column_classification_proposed"


def test_column_classification_proposed_roundtrip_naming_pattern_no_upstream() -> None:
    """``naming_pattern`` strategy (no L5 dependency) → no upstream link."""
    p = ColumnClassificationProposedPayload(
        classification_id="cls-naming-1",
        table_id="public.events",
        column="api_secret",
        classification_level="confidential",
        confidence=0.92,
        strategy="naming_pattern",
        reasoning="column name matches /_secret$/ pattern",
        evidence={"regex": r"_secret$"},
    )
    assert p.upstream_semantic_type_id is None
    assert (
        ColumnClassificationProposedPayload.model_validate(p.model_dump()) == p
    )


@pytest.mark.parametrize(
    "level",
    [
        "public",
        "internal",
        "confidential",
        "pii",
        "regulated",
    ],
)
def test_column_classification_proposed_accepts_every_level(level: str) -> None:
    """Each of the 5 canonical governance levels is accepted (per
    CLAUDE.md §"Ledger-native governance")."""
    p = ColumnClassificationProposedPayload(
        classification_id=f"cls-{level}",
        table_id="t1",
        column="c1",
        classification_level=level,  # type: ignore[arg-type]
        confidence=0.5,
        strategy="naming_pattern",
        reasoning="r",
        evidence={},
    )
    assert p.classification_level == level


def test_column_classification_proposed_rejects_invalid_level() -> None:
    """An out-of-enum classification_level raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        ColumnClassificationProposedPayload(
            classification_id="cls-bogus",
            table_id="t1",
            column="c1",
            classification_level="top_secret",  # type: ignore[arg-type]
            confidence=0.5,
            strategy="naming_pattern",
            reasoning="r",
            evidence={},
        )
    assert "classification_level" in str(exc.value).lower()


def test_column_classification_proposed_rejects_confidence_above_unit() -> None:
    """confidence > 1.0 raises at validation time (strict gate at write)."""
    with pytest.raises(ValidationError) as exc:
        ColumnClassificationProposedPayload(
            classification_id="cls-bad-conf",
            table_id="t1",
            column="c1",
            classification_level="pii",
            confidence=1.5,
            strategy="semantic_type",
            reasoning="r",
            evidence={},
        )
    assert "confidence" in str(exc.value)


def test_column_classification_proposed_rejects_confidence_below_zero() -> None:
    """confidence < 0.0 also raises — symmetric guard."""
    with pytest.raises(ValidationError) as exc:
        ColumnClassificationProposedPayload(
            classification_id="cls-neg-conf",
            table_id="t1",
            column="c1",
            classification_level="public",
            confidence=-0.01,
            strategy="domain_default",
            reasoning="r",
            evidence={},
        )
    assert "confidence" in str(exc.value)


def test_column_classification_proposed_confidence_boundary_unit_values() -> None:
    """0.0 and 1.0 are valid (boundary inclusive — needed for
    deterministic-rule strategies like exact regex matches)."""
    for c in (0.0, 1.0):
        p = ColumnClassificationProposedPayload(
            classification_id=f"cls-bound-{c}",
            table_id="t1",
            column="c1",
            classification_level="regulated",
            confidence=c,
            strategy="naming_pattern",
            reasoning="boundary",
            evidence={},
        )
        assert p.confidence == c


@pytest.mark.parametrize(
    "field_name",
    [
        "classification_id",
        "table_id",
        "column",
        "strategy",
    ],
)
def test_column_classification_proposed_rejects_empty_required_id(
    field_name: str,
) -> None:
    """Each non-empty ID field rejects the empty string at validation time."""
    kwargs = dict(
        classification_id="cls-1",
        table_id="t1",
        column="c1",
        classification_level="internal",
        confidence=0.5,
        strategy="naming_pattern",
        reasoning="r",
        evidence={},
    )
    kwargs[field_name] = ""
    with pytest.raises(ValidationError) as exc:
        ColumnClassificationProposedPayload(**kwargs)  # type: ignore[arg-type]
    assert field_name in str(exc.value)


def test_column_classification_proposed_upstream_optional() -> None:
    """``upstream_semantic_type_id`` defaults to None (for strategies
    that don't consult L5)."""
    p = ColumnClassificationProposedPayload(
        classification_id="cls-no-upstream",
        table_id="t1",
        column="c1",
        classification_level="internal",
        confidence=0.6,
        strategy="domain_default",
        reasoning="domain pack default",
        evidence={},
    )
    assert p.upstream_semantic_type_id is None


# ---------------------------------------------------------------------------
# ColumnClassificationConfirmedPayload
# ---------------------------------------------------------------------------


def test_column_classification_confirmed_roundtrip_full() -> None:
    """Full payload with notes survives roundtrip."""
    p = ColumnClassificationConfirmedPayload(
        classification_id="cls-abc-123",
        confirmed_by_person_id="person-uuid-1",
        notes="Verified — column is indeed a regulated SSN field.",
    )
    assert (
        ColumnClassificationConfirmedPayload.model_validate(p.model_dump()) == p
    )
    assert p.kind == "column_classification_confirmed"


def test_column_classification_confirmed_minimal_no_notes() -> None:
    """notes is optional — default None."""
    p = ColumnClassificationConfirmedPayload(
        classification_id="cls-abc-123",
        confirmed_by_person_id="person-uuid-1",
    )
    assert p.notes is None
    assert (
        ColumnClassificationConfirmedPayload.model_validate(p.model_dump()) == p
    )


def test_column_classification_confirmed_rejects_empty_classification_id() -> None:
    """classification_id must be non-empty."""
    with pytest.raises(ValidationError) as exc:
        ColumnClassificationConfirmedPayload(
            classification_id="",
            confirmed_by_person_id="person-uuid-1",
        )
    assert "classification_id" in str(exc.value)


# ---------------------------------------------------------------------------
# ColumnClassificationRejectedPayload
# ---------------------------------------------------------------------------


def test_column_classification_rejected_roundtrip_full() -> None:
    """Full payload with notes + the L6-specific ``wrong_level`` reason
    survives roundtrip."""
    p = ColumnClassificationRejectedPayload(
        classification_id="cls-abc-123",
        rejected_by_person_id="person-uuid-1",
        reason="wrong_level",
        notes="Column is internal, not regulated — proposal over-classified.",
    )
    assert (
        ColumnClassificationRejectedPayload.model_validate(p.model_dump()) == p
    )
    assert p.kind == "column_classification_rejected"


@pytest.mark.parametrize(
    "reason",
    [
        "false_positive",
        "low_value",
        "wrong_level",
        "out_of_scope",
        "other",
    ],
)
def test_column_classification_rejected_accepts_every_enum_value(
    reason: str,
) -> None:
    """Each documented reason enum value is accepted (5 values total).

    L6-specific 5th value: ``wrong_level`` (distinct from L5's
    ``wrong_type``, L4's ``already_handled`` and L7's
    ``wrong_threshold``)."""
    p = ColumnClassificationRejectedPayload(
        classification_id="cls-1",
        rejected_by_person_id="person-uuid-1",
        reason=reason,  # type: ignore[arg-type]
    )
    assert p.reason == reason


def test_column_classification_rejected_rejects_invalid_reason() -> None:
    """An out-of-enum reason raises ValidationError.

    Particularly: ``wrong_type`` (L5-specific), ``already_handled``
    (L4-specific), and ``wrong_threshold`` (L7-specific) are NOT
    valid here."""
    for bogus in (
        "bogus_reason",
        "wrong_type",
        "already_handled",
        "wrong_threshold",
    ):
        with pytest.raises(ValidationError) as exc:
            ColumnClassificationRejectedPayload(
                classification_id="cls-1",
                rejected_by_person_id="person-uuid-1",
                reason=bogus,  # type: ignore[arg-type]
            )
        assert "reason" in str(exc.value).lower()


def test_column_classification_rejected_rejects_empty_classification_id() -> None:
    """classification_id must be non-empty (symmetric with confirmed)."""
    with pytest.raises(ValidationError) as exc:
        ColumnClassificationRejectedPayload(
            classification_id="",
            rejected_by_person_id="person-uuid-1",
            reason="false_positive",
        )
    assert "classification_id" in str(exc.value)
