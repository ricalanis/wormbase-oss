"""Role payload validation tests (Block A2 of the production-dashboard PRD).

Four new payload kinds — role_assigned, role_revoked, domain_role_assigned,
resource_role_assigned — must each:

* construct from valid args,
* reject extras (Pydantic ``extra='forbid'`` is set on EntryPayload),
* round-trip via ``model_dump`` → ``model_validate`` byte-equivalently,
* enforce kind registration in ``KIND_REGISTRY``,
* reject roles outside the allowed set with a clear error message.

The three role facets (tenancy / domain / resource) each have their own
allowed role set; ``ResourceRoleAssignedPayload`` additionally validates
``resource_type`` against the registered resource registries.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E

PERSON_ID = UUID("0190a0a0-0000-7000-8000-0000000000c1")
DOMAIN_ID = UUID("0190a0a0-0000-7000-8000-0000000000c2")
RESOURCE_ID = UUID("0190a0a0-0000-7000-8000-0000000000c3")
ADMIN_ID = UUID("0190a0a0-0000-7000-8000-0000000000c4")


# ---------------------------------------------------------------------------
# Happy-path construction + roundtrip + registry registration.
# ---------------------------------------------------------------------------

ROLE_CASES: list[tuple[type[E.EntryPayload], dict[str, Any]]] = [
    (
        E.RoleAssignedPayload,
        {"person_id": PERSON_ID, "role": "admin", "granted_by": ADMIN_ID},
    ),
    (
        E.RoleAssignedPayload,
        {"person_id": PERSON_ID, "role": "installer", "granted_by": ADMIN_ID},
    ),
    (
        E.RoleAssignedPayload,
        {"person_id": PERSON_ID, "role": "member", "granted_by": ADMIN_ID},
    ),
    (
        E.RoleAssignedPayload,
        {"person_id": PERSON_ID, "role": "observer", "granted_by": ADMIN_ID},
    ),
    (
        E.RoleRevokedPayload,
        {"person_id": PERSON_ID, "role": "admin", "revoked_by": ADMIN_ID},
    ),
    (
        E.DomainRoleAssignedPayload,
        {
            "person_id": PERSON_ID,
            "domain_id": DOMAIN_ID,
            "role": "owner",
            "granted_by": ADMIN_ID,
        },
    ),
    (
        E.DomainRoleAssignedPayload,
        {
            "person_id": PERSON_ID,
            "domain_id": DOMAIN_ID,
            "role": "contributor",
            "granted_by": ADMIN_ID,
        },
    ),
    (
        E.ResourceRoleAssignedPayload,
        {
            "person_id": PERSON_ID,
            "resource_id": RESOURCE_ID,
            "resource_type": "source",
            "role": "maintainer",
            "granted_by": ADMIN_ID,
        },
    ),
    (
        E.ResourceRoleAssignedPayload,
        {
            "person_id": PERSON_ID,
            "resource_id": RESOURCE_ID,
            "resource_type": "kpi",
            "role": "contributor",
            "granted_by": ADMIN_ID,
        },
    ),
]


@pytest.mark.parametrize("model,data", ROLE_CASES)
def test_role_constructs(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    assert obj.kind in E.KIND_REGISTRY
    assert E.KIND_REGISTRY[obj.kind] is model


@pytest.mark.parametrize("model,data", ROLE_CASES)
def test_role_rejects_extras(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model(**{**data, "not_allowed": True})


@pytest.mark.parametrize("model,data", ROLE_CASES)
def test_role_roundtrips(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    again = model.model_validate(obj.model_dump())
    assert again == obj


# ---------------------------------------------------------------------------
# Kind strings (no ``emit_`` prefix at the payload-class layer).
# ---------------------------------------------------------------------------


def test_role_kind_strings_have_no_emit_prefix() -> None:
    """``emit_`` is added by the write primitive, not by the entry kind."""
    assert E.RoleAssignedPayload.kind == "role_assigned"
    assert E.RoleRevokedPayload.kind == "role_revoked"
    assert E.DomainRoleAssignedPayload.kind == "domain_role_assigned"
    assert E.ResourceRoleAssignedPayload.kind == "resource_role_assigned"


# ---------------------------------------------------------------------------
# Tenancy-role validation: the four allowed roles + a sample of bad ones.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_role", ["superuser", "owner", "maintainer", "", "ADMIN", "root"]
)
def test_role_assigned_rejects_invalid_tenancy_role(bad_role: str) -> None:
    with pytest.raises(ValidationError) as exc:
        E.RoleAssignedPayload(
            person_id=PERSON_ID, role=bad_role, granted_by=ADMIN_ID,
        )
    msg = str(exc.value)
    assert "invalid tenancy role" in msg
    assert "installer" in msg  # error message lists allowed roles


@pytest.mark.parametrize(
    "bad_role", ["superuser", "owner", "maintainer", "", "ADMIN"]
)
def test_role_revoked_rejects_invalid_tenancy_role(bad_role: str) -> None:
    with pytest.raises(ValidationError) as exc:
        E.RoleRevokedPayload(
            person_id=PERSON_ID, role=bad_role, revoked_by=ADMIN_ID,
        )
    assert "invalid tenancy role" in str(exc.value)


# ---------------------------------------------------------------------------
# Domain-role validation: only owner | contributor.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_role", ["admin", "installer", "maintainer", "member", "observer"]
)
def test_domain_role_rejects_non_domain_role(bad_role: str) -> None:
    with pytest.raises(ValidationError) as exc:
        E.DomainRoleAssignedPayload(
            person_id=PERSON_ID,
            domain_id=DOMAIN_ID,
            role=bad_role,
            granted_by=ADMIN_ID,
        )
    msg = str(exc.value)
    assert "invalid domain role" in msg
    assert "owner" in msg  # error lists allowed roles


# ---------------------------------------------------------------------------
# Resource-role validation: only maintainer | contributor.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_role", ["admin", "owner", "installer", "member", "observer"]
)
def test_resource_role_rejects_non_resource_role(bad_role: str) -> None:
    with pytest.raises(ValidationError) as exc:
        E.ResourceRoleAssignedPayload(
            person_id=PERSON_ID,
            resource_id=RESOURCE_ID,
            resource_type="source",
            role=bad_role,
            granted_by=ADMIN_ID,
        )
    msg = str(exc.value)
    assert "invalid resource role" in msg
    assert "maintainer" in msg


@pytest.mark.parametrize(
    "bad_type", ["foo", "user", "person", "", "Source", "TABLE"]
)
def test_resource_role_rejects_unknown_resource_type(bad_type: str) -> None:
    with pytest.raises(ValidationError) as exc:
        E.ResourceRoleAssignedPayload(
            person_id=PERSON_ID,
            resource_id=RESOURCE_ID,
            resource_type=bad_type,
            role="maintainer",
            granted_by=ADMIN_ID,
        )
    msg = str(exc.value)
    assert "invalid resource_type" in msg
    assert "source" in msg


@pytest.mark.parametrize(
    "ok_type", ["source", "table", "kpi", "process", "policy", "domain"],
)
def test_resource_role_accepts_each_resource_type(ok_type: str) -> None:
    obj = E.ResourceRoleAssignedPayload(
        person_id=PERSON_ID,
        resource_id=RESOURCE_ID,
        resource_type=ok_type,
        role="contributor",
        granted_by=ADMIN_ID,
    )
    assert obj.resource_type == ok_type


# ---------------------------------------------------------------------------
# Type guards: UUID fields must be UUIDs.
# ---------------------------------------------------------------------------


def test_role_assigned_requires_uuid_for_granted_by() -> None:
    with pytest.raises(ValidationError):
        E.RoleAssignedPayload(
            person_id=PERSON_ID,
            role="admin",
            granted_by="not-a-uuid",  # type: ignore[arg-type]
        )


def test_domain_role_assigned_requires_uuid_for_domain_id() -> None:
    with pytest.raises(ValidationError):
        E.DomainRoleAssignedPayload(
            person_id=PERSON_ID,
            domain_id="not-a-uuid",  # type: ignore[arg-type]
            role="owner",
            granted_by=ADMIN_ID,
        )


def test_resource_role_assigned_requires_uuid_for_resource_id() -> None:
    with pytest.raises(ValidationError):
        E.ResourceRoleAssignedPayload(
            person_id=PERSON_ID,
            resource_id="not-a-uuid",  # type: ignore[arg-type]
            resource_type="source",
            role="maintainer",
            granted_by=ADMIN_ID,
        )
