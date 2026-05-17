"""Tests for ``PersonInvitedPayload`` — Onboarding Sub-wave C (2026-05-30).

Pins the new ledger entry kind that backs Tier 2's previously-synthetic
co-admin invite affordance:

* Registration in ``KIND_REGISTRY``.
* Round-trip via ``model_dump`` → ``model_validate`` byte-equivalently.
* At least one of ``invitee_email`` / ``invitee_platform_id`` must be
  supplied; enforced at the call site (write_actions helper raises
  ``ValueError``) and at the HTTP endpoint (returns 400). The payload
  itself keeps both fields ``str | None`` so the validity rule lives
  at the boundary, not on the immutable on-the-wire entry shape.
* ``invited_by_person_id`` is required (admin doing the invite).
* ``role_intent`` defaults to "member"; "admin" and "observer" are
  also accepted via Literal.

KIND_REGISTRY grew 109 → 111 paired with ``DomainPackSelectedPayload``.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from wormbase_ledger.entries import (
    KIND_REGISTRY,
    PersonInvitedPayload,
)


def test_person_invited_kind_registered() -> None:
    """Auto-registration via EntryPayload.__init_subclass__."""
    assert "person_invited" in KIND_REGISTRY
    assert KIND_REGISTRY["person_invited"] is PersonInvitedPayload


def test_person_invited_roundtrip_full_fields() -> None:
    """All fields populated round-trip byte-equivalently."""
    inviter = uuid4()
    p = PersonInvitedPayload(
        invitee_email="alice@example.com",
        invitee_platform_id="slack:U01ALICE",
        invited_by_person_id=inviter,
        role_intent="admin",
        notes="adding co-admin for the finance domain",
    )
    assert PersonInvitedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "person_invited"


def test_person_invited_email_only() -> None:
    """``invitee_platform_id=None`` for an email-only invite — the
    payload accepts this; the at-least-one rule is enforced at the
    call site, not on the payload class."""
    p = PersonInvitedPayload(
        invitee_email="bob@example.com",
        invited_by_person_id=uuid4(),
    )
    assert p.invitee_platform_id is None
    assert p.role_intent == "member"  # default
    assert PersonInvitedPayload.model_validate(p.model_dump()) == p


def test_person_invited_platform_id_only() -> None:
    """``invitee_email=None`` for a platform-only invite (e.g. invite
    by @slack-mention without a known email)."""
    p = PersonInvitedPayload(
        invitee_platform_id="slack:U01CAROL",
        invited_by_person_id=uuid4(),
        role_intent="observer",
    )
    assert p.invitee_email is None
    assert p.role_intent == "observer"
    assert PersonInvitedPayload.model_validate(p.model_dump()) == p


def test_person_invited_role_intent_default() -> None:
    """``role_intent`` defaults to "member" when not supplied."""
    p = PersonInvitedPayload(
        invitee_email="dave@example.com",
        invited_by_person_id=uuid4(),
    )
    assert p.role_intent == "member"


def test_person_invited_role_intent_rejects_invalid() -> None:
    """``role_intent`` is a Literal — invalid roles are rejected at
    payload-construction time."""
    with pytest.raises(Exception):
        PersonInvitedPayload(
            invitee_email="eve@example.com",
            invited_by_person_id=uuid4(),
            role_intent="superuser",  # type: ignore[arg-type]
        )


def test_person_invited_requires_invited_by() -> None:
    """``invited_by_person_id`` is required."""
    with pytest.raises(Exception):
        PersonInvitedPayload(  # type: ignore[call-arg]
            invitee_email="frank@example.com",
            # invited_by_person_id missing
        )


def test_person_invited_both_none_payload_valid() -> None:
    """The payload itself accepts both invitee fields as None — the
    at-least-one rule lives at the boundary (HTTP endpoint + write
    action). Keeps the entry shape purely additive.

    Defense in depth: the dashboard form catches the case client-side,
    the HTTP endpoint returns 400, and the write_action helper raises
    ValueError. The ledger entry itself can be written with both None
    (e.g. for a "test-mode" audit trail) without breaking schema."""
    p = PersonInvitedPayload(
        invited_by_person_id=uuid4(),
    )
    assert p.invitee_email is None
    assert p.invitee_platform_id is None
    # Round-trip still works.
    assert PersonInvitedPayload.model_validate(p.model_dump()) == p


def test_person_invited_uuid_roundtrip_preserved() -> None:
    """UUID round-trips through JSON dump/validate."""
    inviter = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    p = PersonInvitedPayload(
        invitee_email="grace@example.com",
        invited_by_person_id=inviter,
    )
    dumped = p.model_dump(mode="json")
    assert dumped["invited_by_person_id"] == str(inviter)
    rebuilt = PersonInvitedPayload.model_validate(dumped)
    assert rebuilt.invited_by_person_id == inviter


def test_person_invited_is_frozen() -> None:
    """EntryPayload subclasses are frozen — mutating fails."""
    p = PersonInvitedPayload(
        invitee_email="henry@example.com",
        invited_by_person_id=uuid4(),
    )
    with pytest.raises(Exception):
        p.invitee_email = "different@example.com"  # type: ignore[misc]


def test_person_invited_extra_forbid() -> None:
    """``extra="forbid"`` — unknown fields raise."""
    with pytest.raises(Exception):
        PersonInvitedPayload(
            invitee_email="ivy@example.com",
            invited_by_person_id=uuid4(),
            unknown_field="rejected",  # type: ignore[call-arg]
        )
