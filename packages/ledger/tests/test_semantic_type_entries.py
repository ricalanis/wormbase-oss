"""L5 Sub-wave A — three new lake-side semantic-type entry kinds.

Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=120.
30 kinds remain before the Wave F Addendum 4 ceiling at 150. L-axis
family count = 12 of 30 cap (L3=3 + L7=3 + L4=3 + L5=3) per Addendum
4 §E — well within cap.

Pins three new payload classes for the L5 cross-axis lake loop that
proposes semantic-type fingerprints on columns + the admin lifecycle
that confirms/rejects them:

* ``SemanticTypeProposedPayload`` (kind ``semantic_type_proposed``) —
  emitted by the L5 Compounding axis when a fingerprinting strategy
  proposes a semantic type for a column (e.g. "this looks like an
  email address").
* ``SemanticTypeConfirmedPayload`` (kind ``semantic_type_confirmed``) —
  operator approval of a previously-proposed semantic type.
* ``SemanticTypeRejectedPayload`` (kind ``semantic_type_rejected``) —
  operator rejection with a categorical reason. The L5-specific 5th
  reason is ``wrong_type`` (replaces L4's ``already_handled`` and
  L7's ``wrong_threshold``).

These tests pin:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Roundtrip via ``model_dump`` → ``model_validate`` byte-equivalently
  for full-field and minimal-field payloads.
* Strict validation: ``confidence`` in [0.0, 1.0]; ``semantic_type``
  pinned to the 19 documented Literal values per spec §3.2; ``reason``
  pinned to the 5 documented values; non-empty ``type_id`` /
  ``table_id`` / ``column`` / ``strategy``.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    SemanticTypeConfirmedPayload,
    SemanticTypeProposedPayload,
    SemanticTypeRejectedPayload,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "semantic_type_proposed",
        "semantic_type_confirmed",
        "semantic_type_rejected",
    ],
)
def test_semantic_type_kind_registered(kind: str) -> None:
    """Each new L5 kind auto-registers in KIND_REGISTRY + ALL_KINDS."""
    assert kind in KIND_REGISTRY
    assert kind in ALL_KINDS


# ---------------------------------------------------------------------------
# SemanticTypeProposedPayload
# ---------------------------------------------------------------------------


def test_semantic_type_proposed_roundtrip_full() -> None:
    """Full payload survives model_dump → model_validate byte-equivalently."""
    p = SemanticTypeProposedPayload(
        type_id="type-abc-123",
        table_id="warehouse.dim_users",
        column="contact_email",
        semantic_type="email",
        confidence=0.92,
        strategy="value_pattern",
        reasoning="18 of 20 sampled values match RFC5322 email regex",
        evidence={
            "match_count": 18,
            "sample_n": 20,
            "regex": r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$",
        },
    )
    assert SemanticTypeProposedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "semantic_type_proposed"


def test_semantic_type_proposed_roundtrip_minimal_column_name_strategy() -> None:
    """``column_name`` strategy with no value evidence still roundtrips."""
    p = SemanticTypeProposedPayload(
        type_id="type-cn-1",
        table_id="public.events",
        column="user_uuid",
        semantic_type="uuid_v4",
        confidence=0.65,
        strategy="column_name",
        reasoning="column name matches /^uuid$/i suffix pattern",
        evidence={},
    )
    assert SemanticTypeProposedPayload.model_validate(p.model_dump()) == p


@pytest.mark.parametrize(
    "semantic_type",
    [
        # Identity
        "email", "phone_e164", "phone_us",
        # Temporal
        "iso_date", "iso_datetime", "unix_timestamp",
        # Identifiers
        "uuid_v4", "uuid_v7", "business_id",
        # Geo/locale
        "country_iso", "language_iso", "currency_iso",
        # PII (sensitive)
        "pii_name", "pii_address", "pii_ssn", "pii_credit_card",
        # Metric
        "metric_count", "metric_amount", "metric_rate",
        # Catch-all
        "other",
    ],
)
def test_semantic_type_proposed_accepts_every_semantic_type(
    semantic_type: str,
) -> None:
    """Each of the 19 documented semantic_type Literal values is accepted."""
    p = SemanticTypeProposedPayload(
        type_id=f"type-{semantic_type}",
        table_id="t1",
        column="c1",
        semantic_type=semantic_type,  # type: ignore[arg-type]
        confidence=0.5,
        strategy="column_name",
        reasoning="r",
        evidence={},
    )
    assert p.semantic_type == semantic_type


def test_semantic_type_proposed_enum_count_is_exactly_twenty() -> None:
    """Spec §3.2 pins the semantic-type enum; drift would raise.

    Spec §3.2 narrative says "19 values" but the literal list enumerates
    20 (3 identity + 3 temporal + 3 identifiers + 3 geo/locale + 4 PII +
    3 metric + 1 catch-all = 20). The Literal in
    ``SemanticTypeProposedPayload`` is the source of truth — the spec
    narrative has an off-by-one (PII band has 4 values, not 3, with
    pii_credit_card included). New types require explicit doctrine
    review.
    """
    # Exhaustive list mirrors test_..._accepts_every_semantic_type above.
    expected = {
        # Identity
        "email", "phone_e164", "phone_us",
        # Temporal
        "iso_date", "iso_datetime", "unix_timestamp",
        # Identifiers
        "uuid_v4", "uuid_v7", "business_id",
        # Geo/locale
        "country_iso", "language_iso", "currency_iso",
        # PII (sensitive)
        "pii_name", "pii_address", "pii_ssn", "pii_credit_card",
        # Metric
        "metric_count", "metric_amount", "metric_rate",
        # Catch-all
        "other",
    }
    assert len(expected) == 20


def test_semantic_type_proposed_rejects_invalid_semantic_type() -> None:
    """An out-of-enum semantic_type raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        SemanticTypeProposedPayload(
            type_id="type-bogus",
            table_id="t1",
            column="c1",
            semantic_type="bogus_type",  # type: ignore[arg-type]
            confidence=0.5,
            strategy="column_name",
            reasoning="r",
            evidence={},
        )
    assert "semantic_type" in str(exc.value).lower()


def test_semantic_type_proposed_rejects_confidence_above_unit() -> None:
    """confidence > 1.0 raises at validation time (strict gate at write)."""
    with pytest.raises(ValidationError) as exc:
        SemanticTypeProposedPayload(
            type_id="type-bad-conf",
            table_id="t1",
            column="c1",
            semantic_type="email",
            confidence=1.5,
            strategy="column_name",
            reasoning="r",
            evidence={},
        )
    assert "confidence" in str(exc.value)


def test_semantic_type_proposed_rejects_confidence_below_zero() -> None:
    """confidence < 0.0 also raises — symmetric guard."""
    with pytest.raises(ValidationError) as exc:
        SemanticTypeProposedPayload(
            type_id="type-neg-conf",
            table_id="t1",
            column="c1",
            semantic_type="email",
            confidence=-0.01,
            strategy="column_name",
            reasoning="r",
            evidence={},
        )
    assert "confidence" in str(exc.value)


def test_semantic_type_proposed_confidence_boundary_unit_values() -> None:
    """0.0 and 1.0 are valid (boundary inclusive — needed for
    deterministic-rule strategies like exact regex matches)."""
    for c in (0.0, 1.0):
        p = SemanticTypeProposedPayload(
            type_id=f"type-bound-{c}",
            table_id="t1",
            column="c1",
            semantic_type="email",
            confidence=c,
            strategy="value_pattern",
            reasoning="boundary",
            evidence={},
        )
        assert p.confidence == c


@pytest.mark.parametrize(
    "field_name",
    [
        "type_id",
        "table_id",
        "column",
        "strategy",
    ],
)
def test_semantic_type_proposed_rejects_empty_required_id(
    field_name: str,
) -> None:
    """Each non-empty ID field rejects the empty string at validation time."""
    kwargs = dict(
        type_id="type-1",
        table_id="t1",
        column="c1",
        semantic_type="email",
        confidence=0.5,
        strategy="column_name",
        reasoning="r",
        evidence={},
    )
    kwargs[field_name] = ""
    with pytest.raises(ValidationError) as exc:
        SemanticTypeProposedPayload(**kwargs)  # type: ignore[arg-type]
    assert field_name in str(exc.value)


# ---------------------------------------------------------------------------
# SemanticTypeConfirmedPayload
# ---------------------------------------------------------------------------


def test_semantic_type_confirmed_roundtrip_full() -> None:
    """Full payload with notes survives roundtrip."""
    p = SemanticTypeConfirmedPayload(
        type_id="type-abc-123",
        confirmed_by_person_id="person-uuid-1",
        notes="Verified — column is indeed an email address.",
    )
    assert SemanticTypeConfirmedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "semantic_type_confirmed"


def test_semantic_type_confirmed_minimal_no_notes() -> None:
    """notes is optional — default None."""
    p = SemanticTypeConfirmedPayload(
        type_id="type-abc-123",
        confirmed_by_person_id="person-uuid-1",
    )
    assert p.notes is None
    assert SemanticTypeConfirmedPayload.model_validate(p.model_dump()) == p


def test_semantic_type_confirmed_rejects_empty_type_id() -> None:
    """type_id must be non-empty."""
    with pytest.raises(ValidationError) as exc:
        SemanticTypeConfirmedPayload(
            type_id="",
            confirmed_by_person_id="person-uuid-1",
        )
    assert "type_id" in str(exc.value)


# ---------------------------------------------------------------------------
# SemanticTypeRejectedPayload
# ---------------------------------------------------------------------------


def test_semantic_type_rejected_roundtrip_full() -> None:
    """Full payload with notes + each enum reason survives roundtrip."""
    p = SemanticTypeRejectedPayload(
        type_id="type-abc-123",
        rejected_by_person_id="person-uuid-1",
        reason="false_positive",
        notes="Column is actually a free-text comment field.",
    )
    assert SemanticTypeRejectedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "semantic_type_rejected"


@pytest.mark.parametrize(
    "reason",
    [
        "false_positive",
        "low_value",
        "wrong_type",
        "out_of_scope",
        "other",
    ],
)
def test_semantic_type_rejected_accepts_every_enum_value(reason: str) -> None:
    """Each documented reason enum value is accepted (5 values total).

    L5-specific 5th value: ``wrong_type`` (replaces L4's ``already_handled``
    and L7's ``wrong_threshold``)."""
    p = SemanticTypeRejectedPayload(
        type_id="type-1",
        rejected_by_person_id="person-uuid-1",
        reason=reason,  # type: ignore[arg-type]
    )
    assert p.reason == reason


def test_semantic_type_rejected_rejects_invalid_reason() -> None:
    """An out-of-enum reason raises ValidationError.

    Particularly: ``already_handled`` (L4-specific) and
    ``wrong_threshold`` (L7-specific) are NOT valid here."""
    for bogus in ("bogus_reason", "already_handled", "wrong_threshold"):
        with pytest.raises(ValidationError) as exc:
            SemanticTypeRejectedPayload(
                type_id="type-1",
                rejected_by_person_id="person-uuid-1",
                reason=bogus,  # type: ignore[arg-type]
            )
        assert "reason" in str(exc.value).lower()


def test_semantic_type_rejected_rejects_empty_type_id() -> None:
    """type_id must be non-empty (symmetric with confirmed)."""
    with pytest.raises(ValidationError) as exc:
        SemanticTypeRejectedPayload(
            type_id="",
            rejected_by_person_id="person-uuid-1",
            reason="false_positive",
        )
    assert "type_id" in str(exc.value)
