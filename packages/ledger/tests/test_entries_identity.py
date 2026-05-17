"""Identity payload validation tests (Block A1 of the production-dashboard PRD).

Seven new payload kinds — person_proposed / _confirmed / _archived,
identity_linked / _unlinked, install_completed / _revoked — must each:

* construct from valid args,
* reject extras (Pydantic ``extra='forbid'`` is set on EntryPayload),
* round-trip via ``model_dump`` → ``model_validate`` byte-equivalently,
* enforce kind registration in ``KIND_REGISTRY``.

`InstallCompletedPayload.oauth_grant_ref` additionally enforces the
``kms://`` / ``vault://`` opaque-handle prefix so cleartext bearer tokens
cannot enter the ledger.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E

PERSON_ID = UUID("0190a0a0-0000-7000-8000-0000000000b1")
TENANT_ID = UUID("0190a0a0-0000-7000-8000-0000000000b2")
ADMIN_ID = UUID("0190a0a0-0000-7000-8000-0000000000b3")
INSTALL_ID = UUID("0190a0a0-0000-7000-8000-0000000000b4")


IDENTITY_CASES: list[tuple[type[E.EntryPayload], dict[str, Any]]] = [
    (
        E.PersonProposedPayload,
        {
            "person_id": PERSON_ID,
            "tenant_id": TENANT_ID,
            "name": "Bob",
            "email": "bob@example.co",
            "platform": "slack",
            "platform_user_id": "U-bob",
            "proposed_by": "worm",
        },
    ),
    (
        E.PersonProposedPayload,
        {
            "person_id": PERSON_ID,
            "tenant_id": TENANT_ID,
            "name": "Bob",
            "email": None,  # email is optional
            "platform": "slack",
            "platform_user_id": "U-bob",
            "proposed_by": str(ADMIN_ID),
            "position": "cfo",
        },
    ),
    (
        E.PersonConfirmedPayload,
        {"person_id": PERSON_ID, "confirmed_by": ADMIN_ID},
    ),
    (
        E.PersonArchivedPayload,
        {
            "person_id": PERSON_ID,
            "archived_by": ADMIN_ID,
            "reason": "merged into another Person",
        },
    ),
    (
        E.IdentityLinkedPayload,
        {
            "person_id": PERSON_ID,
            "platform": "discord",
            "platform_user_id": "bob#1234",
            "linked_by": ADMIN_ID,
        },
    ),
    (
        E.IdentityUnlinkedPayload,
        {
            "person_id": PERSON_ID,
            "platform": "slack",
            "platform_user_id": "U-bob",
            "unlinked_by": ADMIN_ID,
        },
    ),
    (
        E.InstallCompletedPayload,
        {
            "install_id": INSTALL_ID,
            "tenant_id": TENANT_ID,
            "platform": "slack",
            "installer_person_id": PERSON_ID,
            "oauth_grant_ref": "kms://wormbase/install/abc123",
            "scopes": ["chat:write", "files:read"],
            "bot_user_id": "B0X",
        },
    ),
    (
        E.InstallCompletedPayload,
        {
            "install_id": INSTALL_ID,
            "tenant_id": TENANT_ID,
            "platform": "slack",
            "installer_person_id": PERSON_ID,
            "oauth_grant_ref": "vault://wormbase/install/abc123",
            "scopes": [],
            "bot_user_id": "B0X",
        },
    ),
    (
        E.InstallRevokedPayload,
        {"install_id": INSTALL_ID, "revoked_by": ADMIN_ID},
    ),
]


@pytest.mark.parametrize("model,data", IDENTITY_CASES)
def test_identity_constructs(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    assert obj.kind in E.KIND_REGISTRY
    assert E.KIND_REGISTRY[obj.kind] is model


@pytest.mark.parametrize("model,data", IDENTITY_CASES)
def test_identity_rejects_extras(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model(**{**data, "not_allowed": True})


@pytest.mark.parametrize("model,data", IDENTITY_CASES)
def test_identity_roundtrips(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    again = model.model_validate(obj.model_dump())
    assert again == obj


def test_person_proposed_kind_string() -> None:
    """Kind has no `emit_` prefix — that's applied by the write primitive."""
    assert E.PersonProposedPayload.kind == "person_proposed"
    assert E.PersonConfirmedPayload.kind == "person_confirmed"
    assert E.PersonArchivedPayload.kind == "person_archived"
    assert E.IdentityLinkedPayload.kind == "identity_linked"
    assert E.IdentityUnlinkedPayload.kind == "identity_unlinked"
    assert E.InstallCompletedPayload.kind == "install_completed"
    assert E.InstallRevokedPayload.kind == "install_revoked"


def test_person_proposed_email_optional() -> None:
    p = E.PersonProposedPayload(
        person_id=PERSON_ID,
        tenant_id=TENANT_ID,
        name="Eve",
        platform="slack",
        platform_user_id="U-eve",
        proposed_by="worm",
    )
    assert p.email is None
    assert p.position is None


def test_person_proposed_requires_name() -> None:
    with pytest.raises(ValidationError):
        E.PersonProposedPayload(
            person_id=PERSON_ID,
            tenant_id=TENANT_ID,
            # name missing
            platform="slack",
            platform_user_id="U-bob",
            proposed_by="worm",
        )


def test_person_proposed_requires_platform_user_id() -> None:
    with pytest.raises(ValidationError):
        E.PersonProposedPayload(
            person_id=PERSON_ID,
            tenant_id=TENANT_ID,
            name="Bob",
            platform="slack",
            # platform_user_id missing
            proposed_by="worm",
        )


def test_install_completed_rejects_raw_token() -> None:
    """Raw bearer tokens must never enter the ledger."""
    with pytest.raises(ValidationError):
        E.InstallCompletedPayload(
            install_id=INSTALL_ID,
            tenant_id=TENANT_ID,
            platform="slack",
            installer_person_id=PERSON_ID,
            oauth_grant_ref="xoxb-1234567890",  # raw Slack token
            scopes=["chat:write"],
            bot_user_id="B0X",
        )


def test_install_completed_rejects_https_url() -> None:
    """Even a non-secret HTTPS URL is wrong shape — must be opaque ref."""
    with pytest.raises(ValidationError):
        E.InstallCompletedPayload(
            install_id=INSTALL_ID,
            tenant_id=TENANT_ID,
            platform="slack",
            installer_person_id=PERSON_ID,
            oauth_grant_ref="https://example.com/grant",
            scopes=[],
            bot_user_id="B0X",
        )


def test_install_completed_accepts_kms_prefix() -> None:
    p = E.InstallCompletedPayload(
        install_id=INSTALL_ID,
        tenant_id=TENANT_ID,
        platform="slack",
        installer_person_id=PERSON_ID,
        oauth_grant_ref="kms://wormbase/install/x",
        scopes=["chat:write"],
        bot_user_id="B0X",
    )
    assert p.oauth_grant_ref.startswith("kms://")


def test_install_completed_accepts_vault_prefix() -> None:
    p = E.InstallCompletedPayload(
        install_id=INSTALL_ID,
        tenant_id=TENANT_ID,
        platform="slack",
        installer_person_id=PERSON_ID,
        oauth_grant_ref="vault://wormbase/install/x",
        scopes=[],
        bot_user_id="B0X",
    )
    assert p.oauth_grant_ref.startswith("vault://")


def test_identity_linked_requires_uuid_for_linked_by() -> None:
    with pytest.raises(ValidationError):
        E.IdentityLinkedPayload(
            person_id=PERSON_ID,
            platform="slack",
            platform_user_id="U-bob",
            linked_by="not-a-uuid",  # type: ignore[arg-type]
        )


def test_install_revoked_round_trip_preserves_ids() -> None:
    p = E.InstallRevokedPayload(install_id=INSTALL_ID, revoked_by=ADMIN_ID)
    again = E.InstallRevokedPayload.model_validate(p.model_dump())
    assert again.install_id == INSTALL_ID
    assert again.revoked_by == ADMIN_ID
