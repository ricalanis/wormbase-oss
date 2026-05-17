"""Tests for ``DomainPackSelectedPayload`` — Onboarding Sub-wave C (2026-05-30).

Pins the new ledger entry kind that backs the Tier 2 domain pack
picker:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Round-trip via ``model_dump`` → ``model_validate`` byte-equivalently.
* ``pack_id`` + ``pack_version`` + ``selected_by_person_id`` are
  required; ``notes`` is optional free-text audit prose.
* The entry is the audit anchor for a pack pick; the actual
  domain/policy seeding happens via the existing
  ``emit_domain_registered`` + ``emit_policy_applied`` PEVR cycles
  fired by ``pack_seeder.seed_pack`` in the same batch sequence.

KIND_REGISTRY grew 109 → 111 paired with ``PersonInvitedPayload``
(additive per schema-evolution doctrine Rule 2; under the 120-kind
Wave F Addendum 1 ceiling).
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from wormbase_ledger.entries import (
    KIND_REGISTRY,
    DomainPackSelectedPayload,
)


def test_domain_pack_selected_kind_registered() -> None:
    """Auto-registration via EntryPayload.__init_subclass__ — the kind
    appears in ``KIND_REGISTRY`` and maps back to the payload class."""
    assert "domain_pack_selected" in KIND_REGISTRY
    assert KIND_REGISTRY["domain_pack_selected"] is DomainPackSelectedPayload


def test_domain_pack_selected_roundtrip_full_fields() -> None:
    """All fields populated round-trip byte-equivalently via model_dump
    → model_validate."""
    pid = uuid4()
    p = DomainPackSelectedPayload(
        pack_id="saas",
        pack_version="v1.0",
        selected_by_person_id=pid,
        notes="Tier 2 installer picked SaaS pack at 2026-05-30T12:00:00Z",
    )
    assert DomainPackSelectedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "domain_pack_selected"


def test_domain_pack_selected_notes_optional() -> None:
    """``notes`` defaults to None and is preserved on round-trip."""
    pid = uuid4()
    p = DomainPackSelectedPayload(
        pack_id="fintech",
        pack_version="v1.0",
        selected_by_person_id=pid,
    )
    assert p.notes is None
    assert DomainPackSelectedPayload.model_validate(p.model_dump()) == p


def test_domain_pack_selected_requires_selected_by_person_id() -> None:
    """``selected_by_person_id`` is required — defense in depth:
    admin role check lives on the dashboard server action AND the
    HTTP endpoint; this is the ledger-side belt+braces."""
    with pytest.raises(Exception):
        DomainPackSelectedPayload(  # type: ignore[call-arg]
            pack_id="generic",
            pack_version="v1.0",
            # selected_by_person_id missing
        )


def test_domain_pack_selected_pack_id_is_free_string() -> None:
    """``pack_id`` is intentionally a free-form string (not a Literal)
    so adding a new pack YAML does not require a payload-class schema
    bump. The four canonical packs (generic / saas / marketplace /
    fintech) and any future packs all round-trip identically."""
    for pack_id in ("generic", "saas", "marketplace", "fintech"):
        p = DomainPackSelectedPayload(
            pack_id=pack_id,
            pack_version="v1.0",
            selected_by_person_id=uuid4(),
        )
        assert p.pack_id == pack_id
        assert DomainPackSelectedPayload.model_validate(p.model_dump()) == p


def test_domain_pack_selected_pack_version_required() -> None:
    """``pack_version`` is required — bumps when the bundled YAML
    contents change so audit trails distinguish installs done against
    different baselines (wire-replay determinism)."""
    with pytest.raises(Exception):
        DomainPackSelectedPayload(  # type: ignore[call-arg]
            pack_id="saas",
            # pack_version missing
            selected_by_person_id=uuid4(),
        )


def test_domain_pack_selected_person_id_is_uuid() -> None:
    """``selected_by_person_id`` is typed UUID — non-UUID strings are
    rejected. Mirrors the rest of the role-grant payloads."""
    with pytest.raises(Exception):
        DomainPackSelectedPayload(
            pack_id="saas",
            pack_version="v1.0",
            selected_by_person_id="not-a-uuid",  # type: ignore[arg-type]
        )


def test_domain_pack_selected_is_frozen() -> None:
    """All EntryPayload subclasses are frozen — mutating fails."""
    p = DomainPackSelectedPayload(
        pack_id="generic",
        pack_version="v1.0",
        selected_by_person_id=uuid4(),
    )
    with pytest.raises(Exception):
        p.pack_id = "marketplace"  # type: ignore[misc]


def test_domain_pack_selected_extra_forbid() -> None:
    """``extra="forbid"`` on the model_config — unknown fields raise."""
    with pytest.raises(Exception):
        DomainPackSelectedPayload(
            pack_id="saas",
            pack_version="v1.0",
            selected_by_person_id=uuid4(),
            unknown_field="should be rejected",  # type: ignore[call-arg]
        )


def test_domain_pack_selected_uuid_roundtrip_preserved() -> None:
    """UUID round-trips through JSON dump/validate without precision
    loss (defensive — pydantic v2 serializes UUIDs as strings)."""
    pid = UUID("12345678-1234-1234-1234-123456789abc")
    p = DomainPackSelectedPayload(
        pack_id="marketplace",
        pack_version="v2.1",
        selected_by_person_id=pid,
        notes="multi-version pick",
    )
    dumped = p.model_dump(mode="json")
    assert dumped["selected_by_person_id"] == str(pid)
    rebuilt = DomainPackSelectedPayload.model_validate(dumped)
    assert rebuilt.selected_by_person_id == pid
