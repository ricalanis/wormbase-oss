"""Phase 1B.F — Person-tenant binding gate added in authorize_caller.

A token claiming ``(person_id, tenant_slug)`` MUST fail authorization if
no unrevoked Person row exists at projection_persons[(person_id,
tenant_slug)]. Closes the loophole where a forged compact token with
arbitrary person_id + tenant_slug could resolve to a (person, company)
pair without the Person actually existing in that tenant.

Pairs with the spike + plan at:
  - docs/superpowers/notes/2026-05-04-multitenancy-v2-spike.md
  - docs/superpowers/plans/2026-05-04-multitenancy-v2.md
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_core import write_actions
from wormbase_core.mcp_tools.auth import (
    authorize_caller,
    encode_compact_token,
)
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger


API_TOKEN = "test-1bf-secret"


def _bearer_ctx(token: str):
    """Build a fake FastMCP-style Context carrying only the bearer."""

    class _H:
        def __init__(self, h):
            self.h = h

        def get(self, k):
            return self.h.get(k.lower())

    class _Req:
        def __init__(self, h):
            self.headers = _H(h)

    class _RC:
        def __init__(self, h):
            self.request = _Req(h)

    class _Ctx:
        def __init__(self, h):
            self.request_context = _RC(h)

    return _Ctx({"authorization": f"Bearer {token}"})


async def test_synthetic_person_in_token_is_rejected() -> None:
    """A token whose person_id has no Person row in the bound tenant
    raises PermissionError — the new 1B.F gate."""
    ledger = InMemoryLedger()
    forged_person = uuid4()
    token = encode_compact_token(
        secret=API_TOKEN,
        person_id=forged_person,
        tenant_slug="baseworm",
    )
    ctx = _bearer_ctx(token)
    with pytest.raises(PermissionError, match="no such Person"):
        await authorize_caller(
            ctx,
            ledger=ledger,
            api_token=API_TOKEN,
            fallback_company_id=None,
        )


async def test_existing_confirmed_person_in_token_is_accepted() -> None:
    """Sanity: if the Person row exists and is confirmed, authorize_caller
    succeeds — the gate doesn't break the legitimate path."""
    ledger = InMemoryLedger()
    cid = tenant_to_uuid("baseworm")
    pid = uuid4()
    await write_actions.propose_person(
        ledger,
        cid,
        person_id=pid,
        tenant_id=cid,
        name="Alice",
        email="alice@example.com",
        platform="slack",
        platform_user_id="UALICE",
        position=None,
        proposed_by="test",
    )
    await write_actions.confirm_person(
        ledger,
        cid,
        person_id=pid,
        confirmed_by=pid,
    )
    token = encode_compact_token(
        secret=API_TOKEN,
        person_id=pid,
        tenant_slug="baseworm",
    )
    ctx = _bearer_ctx(token)
    result = await authorize_caller(
        ctx,
        ledger=ledger,
        api_token=API_TOKEN,
        fallback_company_id=None,
    )
    assert result["caller_person_id"] == pid


async def test_archived_person_in_token_is_rejected() -> None:
    """Archived Person — even if proposed once — must not authorize."""
    ledger = InMemoryLedger()
    cid = tenant_to_uuid("baseworm")
    pid = uuid4()
    await write_actions.propose_person(
        ledger,
        cid,
        person_id=pid,
        tenant_id=cid,
        name="Bob",
        email="bob@example.com",
        platform="slack",
        platform_user_id="UBOB",
        position=None,
        proposed_by="test",
    )
    await write_actions.confirm_person(
        ledger,
        cid,
        person_id=pid,
        confirmed_by=pid,
    )
    await write_actions.archive_person(
        ledger,
        cid,
        person_id=pid,
        archived_by=pid,
        reason="test",
    )
    token = encode_compact_token(
        secret=API_TOKEN,
        person_id=pid,
        tenant_slug="baseworm",
    )
    ctx = _bearer_ctx(token)
    with pytest.raises(PermissionError, match="no such Person"):
        await authorize_caller(
            ctx,
            ledger=ledger,
            api_token=API_TOKEN,
            fallback_company_id=None,
        )


async def test_person_in_other_tenant_does_not_satisfy_gate() -> None:
    """A Person row in tenant A does not authorize a token claiming
    tenant_slug='B' for the same person_id — the ledger fetch is
    company_id-scoped, so the row simply doesn't appear in the
    other tenant's fetch."""
    ledger = InMemoryLedger()
    cid_a = tenant_to_uuid("baseworm")
    pid = uuid4()
    await write_actions.propose_person(
        ledger,
        cid_a,
        person_id=pid,
        tenant_id=cid_a,
        name="Carol",
        email="carol@a.com",
        platform="slack",
        platform_user_id="UCAROL",
        position=None,
        proposed_by="test",
    )
    await write_actions.confirm_person(
        ledger,
        cid_a,
        person_id=pid,
        confirmed_by=pid,
    )
    # Token claims tenant B, but pid only exists in A.
    token = encode_compact_token(
        secret=API_TOKEN,
        person_id=pid,
        tenant_slug="democorp",
    )
    ctx = _bearer_ctx(token)
    with pytest.raises(PermissionError, match="no such Person"):
        await authorize_caller(
            ctx,
            ledger=ledger,
            api_token=API_TOKEN,
            fallback_company_id=None,
        )


async def test_flat_token_path_unaffected_by_gate() -> None:
    """A flat (legacy) token has no person_id claim, so the new gate
    doesn't fire — backstage admin path keeps working."""
    ledger = InMemoryLedger()

    class _H:
        def __init__(self, h):
            self.h = h

        def get(self, k):
            return self.h.get(k.lower())

    class _Req:
        def __init__(self, h):
            self.headers = _H(h)

    class _RC:
        def __init__(self, h):
            self.request = _Req(h)

    class _Ctx:
        def __init__(self, h):
            self.request_context = _RC(h)

    ctx = _Ctx(
        {"authorization": f"Bearer {API_TOKEN}", "x-tenant-slug": "baseworm"}
    )
    result = await authorize_caller(
        ctx,
        ledger=ledger,
        api_token=API_TOKEN,
        fallback_company_id=None,
    )
    assert result["caller_person_id"] is None
    assert result["tenancy_role"] == "admin"
