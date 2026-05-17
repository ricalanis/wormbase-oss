"""L8 Sub-wave A — three new lake-side entity-stitch entry kinds.

Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=126.
24 kinds remain before the Wave F Addendum 4 ceiling at 150. L-axis
family count = 18 of 30 cap (L3=3 + L7=3 + L4=3 + L5=3 + L6=3 + L8=3)
per Addendum 4 §E — well within cap.

Pins three new payload classes for the L8 lake loop that proposes
cross-source entity-stitch candidates between two ``(source, table,
column)`` triples sharing a probable entity identity + the admin
lifecycle that confirms/rejects them. L8 is the 6th lake-side
compounding axis AND the 3rd cross-axis chain (after L4→L3 and L6→L5)
— the strategies read L5's confirmed semantic types via the same
``ConfirmedSemanticTypeReader`` Protocol L6 introduced and thread the
``upstream_semantic_type_id`` field back into the proposal.

* ``EntityStitchProposedPayload`` (kind ``entity_stitch_proposed``) —
  emitted by the L8 Compounding axis when a strategy proposes a
  cross-source bridge between two columns referring to the same
  underlying entity (e.g. ``stripe.customers.email`` ↔
  ``salesforce.contacts.email``).
* ``EntityStitchConfirmedPayload`` (kind ``entity_stitch_confirmed``)
  — operator approval of a previously-proposed stitch.
* ``EntityStitchRejectedPayload`` (kind ``entity_stitch_rejected``) —
  operator rejection with a categorical reason. The L8-specific 5th
  reason is ``wrong_pairing`` (distinct from L6's ``wrong_level``,
  L5's ``wrong_type``, L4's ``already_handled`` and L7's
  ``wrong_threshold``).

These tests pin:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Roundtrip via ``model_dump`` → ``model_validate`` byte-equivalently
  for full-field and minimal-field payloads.
* Strict validation: ``confidence`` in [0.0, 1.0]; ``entity_kind``
  pinned to the 8 canonical values; ``reason`` pinned to the 5
  documented values; non-empty ``stitch_id`` / ``src_*`` /
  ``strategy``.
* ``upstream_semantic_type_id`` accepts None (for strategies that
  don't consult L5) and string values (the L8→L5 cross-axis chain).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    EntityStitchConfirmedPayload,
    EntityStitchProposedPayload,
    EntityStitchRejectedPayload,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    [
        "entity_stitch_proposed",
        "entity_stitch_confirmed",
        "entity_stitch_rejected",
    ],
)
def test_entity_stitch_kind_registered(kind: str) -> None:
    """Each new L8 kind auto-registers in KIND_REGISTRY + ALL_KINDS."""
    assert kind in KIND_REGISTRY
    assert kind in ALL_KINDS


# ---------------------------------------------------------------------------
# EntityStitchProposedPayload
# ---------------------------------------------------------------------------


def test_entity_stitch_proposed_roundtrip_full() -> None:
    """Full payload (with cross-axis upstream link) survives model_dump
    → model_validate byte-equivalently."""
    p = EntityStitchProposedPayload(
        stitch_id="stitch-abc-123",
        src_source_id_a="src-stripe-1",
        src_table_a="customers",
        src_column_a="email",
        src_source_id_b="src-salesforce-1",
        src_table_b="contacts",
        src_column_b="email",
        upstream_semantic_type_id="type-pii-email-1",
        entity_kind="person",
        confidence=0.93,
        strategy="sample_overlap",
        reasoning="87% of stripe.customers.email values found in salesforce.contacts.email",
        evidence={
            "sample_overlap_pct": 0.87,
            "endpoints_sampled": 200,
            "upstream_semantic_type": "pii_email",
        },
    )
    assert (
        EntityStitchProposedPayload.model_validate(p.model_dump()) == p
    )
    assert p.kind == "entity_stitch_proposed"


def test_entity_stitch_proposed_roundtrip_name_match_no_upstream() -> None:
    """``name_match`` strategy (no L5 dependency) → no upstream link."""
    p = EntityStitchProposedPayload(
        stitch_id="stitch-name-1",
        src_source_id_a="src-stripe-1",
        src_table_a="customers",
        src_column_a="customer_id",
        src_source_id_b="src-hubspot-1",
        src_table_b="contacts",
        src_column_b="customer_id",
        entity_kind="person",
        confidence=0.78,
        strategy="name_match",
        reasoning="exact column-name match across sources",
        evidence={"name_match": "customer_id"},
    )
    assert p.upstream_semantic_type_id is None
    assert (
        EntityStitchProposedPayload.model_validate(p.model_dump()) == p
    )


@pytest.mark.parametrize(
    "kind",
    [
        "person",
        "organization",
        "transaction",
        "product",
        "event",
        "location",
        "session",
        "other",
    ],
)
def test_entity_stitch_proposed_accepts_every_entity_kind(kind: str) -> None:
    """Each of the 8 canonical entity kinds is accepted."""
    p = EntityStitchProposedPayload(
        stitch_id=f"stitch-{kind}",
        src_source_id_a="s1",
        src_table_a="t1",
        src_column_a="c1",
        src_source_id_b="s2",
        src_table_b="t2",
        src_column_b="c2",
        entity_kind=kind,  # type: ignore[arg-type]
        confidence=0.5,
        strategy="name_match",
        reasoning="r",
        evidence={},
    )
    assert p.entity_kind == kind


def test_entity_stitch_proposed_rejects_invalid_entity_kind() -> None:
    """An out-of-enum entity_kind raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        EntityStitchProposedPayload(
            stitch_id="stitch-bogus",
            src_source_id_a="s1",
            src_table_a="t1",
            src_column_a="c1",
            src_source_id_b="s2",
            src_table_b="t2",
            src_column_b="c2",
            entity_kind="alien",  # type: ignore[arg-type]
            confidence=0.5,
            strategy="name_match",
            reasoning="r",
            evidence={},
        )
    assert "entity_kind" in str(exc.value)


@pytest.mark.parametrize("bad", [-0.01, 1.01, 2.0, -1.0])
def test_entity_stitch_proposed_rejects_out_of_range_confidence(bad: float) -> None:
    """confidence outside [0.0, 1.0] raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        EntityStitchProposedPayload(
            stitch_id="stitch-bad-conf",
            src_source_id_a="s1",
            src_table_a="t1",
            src_column_a="c1",
            src_source_id_b="s2",
            src_table_b="t2",
            src_column_b="c2",
            entity_kind="person",
            confidence=bad,
            strategy="name_match",
            reasoning="r",
            evidence={},
        )
    assert "confidence" in str(exc.value)


@pytest.mark.parametrize(
    "field",
    [
        "stitch_id",
        "src_source_id_a",
        "src_table_a",
        "src_column_a",
        "src_source_id_b",
        "src_table_b",
        "src_column_b",
        "strategy",
    ],
)
def test_entity_stitch_proposed_rejects_empty_required_string(field: str) -> None:
    """Each required identifier / strategy field rejects the empty string."""
    valid = dict(
        stitch_id="stitch-x",
        src_source_id_a="s1",
        src_table_a="t1",
        src_column_a="c1",
        src_source_id_b="s2",
        src_table_b="t2",
        src_column_b="c2",
        entity_kind="person",
        confidence=0.5,
        strategy="name_match",
        reasoning="r",
        evidence={},
    )
    valid[field] = ""
    with pytest.raises(ValidationError) as exc:
        EntityStitchProposedPayload(**valid)  # type: ignore[arg-type]
    assert field in str(exc.value) or "non-empty" in str(exc.value)


def test_entity_stitch_proposed_accepts_same_source_stitch() -> None:
    """No same-source guard at payload layer — strategies may legitimately
    propose intra-source stitches; drift prevention lives in strategy
    logic, not in the ledger entry validator."""
    p = EntityStitchProposedPayload(
        stitch_id="stitch-intra-1",
        src_source_id_a="src-stripe-1",
        src_table_a="customers",
        src_column_a="email",
        src_source_id_b="src-stripe-1",
        src_table_b="invoices",
        src_column_b="customer_email",
        entity_kind="person",
        confidence=0.81,
        strategy="sample_overlap",
        reasoning="intra-source same-entity bridge",
        evidence={"sample_overlap_pct": 0.81},
    )
    assert p.src_source_id_a == p.src_source_id_b


# ---------------------------------------------------------------------------
# EntityStitchConfirmedPayload
# ---------------------------------------------------------------------------


def test_entity_stitch_confirmed_roundtrip_full() -> None:
    """Full payload survives model_dump → model_validate."""
    p = EntityStitchConfirmedPayload(
        stitch_id="stitch-abc-123",
        confirmed_by_person_id="person-uuid-1",
        notes="reviewed and accepted",
    )
    assert (
        EntityStitchConfirmedPayload.model_validate(p.model_dump()) == p
    )
    assert p.kind == "entity_stitch_confirmed"


def test_entity_stitch_confirmed_roundtrip_minimal() -> None:
    """Minimal payload (no notes) survives roundtrip."""
    p = EntityStitchConfirmedPayload(
        stitch_id="stitch-abc-123",
        confirmed_by_person_id="person-uuid-1",
    )
    assert p.notes is None
    assert (
        EntityStitchConfirmedPayload.model_validate(p.model_dump()) == p
    )


def test_entity_stitch_confirmed_rejects_empty_stitch_id() -> None:
    """Empty stitch_id raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        EntityStitchConfirmedPayload(
            stitch_id="",
            confirmed_by_person_id="person-uuid-1",
        )
    assert "stitch_id" in str(exc.value) or "non-empty" in str(exc.value)


# ---------------------------------------------------------------------------
# EntityStitchRejectedPayload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "false_positive",
        "low_value",
        "wrong_pairing",
        "out_of_scope",
        "other",
    ],
)
def test_entity_stitch_rejected_accepts_every_reason(reason: str) -> None:
    """All 5 documented rejection reasons are accepted (including the
    L8-specific ``wrong_pairing``)."""
    p = EntityStitchRejectedPayload(
        stitch_id="stitch-abc-123",
        rejected_by_person_id="person-uuid-1",
        reason=reason,  # type: ignore[arg-type]
    )
    assert p.reason == reason
    assert (
        EntityStitchRejectedPayload.model_validate(p.model_dump()) == p
    )


def test_entity_stitch_rejected_includes_wrong_pairing() -> None:
    """``wrong_pairing`` is the L8-specific reason (distinct from L6's
    ``wrong_level``, L5's ``wrong_type``, L4's ``already_handled``
    and L7's ``wrong_threshold``)."""
    p = EntityStitchRejectedPayload(
        stitch_id="stitch-abc-123",
        rejected_by_person_id="person-uuid-1",
        reason="wrong_pairing",
        notes="endpoints describe two different person entities",
    )
    assert p.reason == "wrong_pairing"
    assert p.kind == "entity_stitch_rejected"


def test_entity_stitch_rejected_rejects_unknown_reason() -> None:
    """An out-of-enum reason raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        EntityStitchRejectedPayload(
            stitch_id="stitch-abc-123",
            rejected_by_person_id="person-uuid-1",
            reason="bogus_reason",  # type: ignore[arg-type]
        )
    assert "reason" in str(exc.value)


def test_entity_stitch_rejected_rejects_empty_stitch_id() -> None:
    """Empty stitch_id raises ValidationError."""
    with pytest.raises(ValidationError) as exc:
        EntityStitchRejectedPayload(
            stitch_id="",
            rejected_by_person_id="person-uuid-1",
            reason="false_positive",
        )
    assert "stitch_id" in str(exc.value) or "non-empty" in str(exc.value)
