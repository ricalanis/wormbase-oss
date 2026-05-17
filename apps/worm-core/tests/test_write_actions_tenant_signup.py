"""Phase 1B.B — write_actions for tenant signup chain.

Pairs with the spike + plan at:
  - docs/superpowers/notes/2026-05-04-multitenancy-v2-spike.md
  - docs/superpowers/plans/2026-05-04-multitenancy-v2.md

The two helpers (``initiate_tenant_signup`` + ``complete_tenant_signup``)
are the only writers of ``emit_tenant_signup_*`` entries. Both Slack
OAuth and email magic-link flows funnel through this pair.
"""
from __future__ import annotations

import hashlib

import pytest

from wormbase_core import write_actions
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger


@pytest.fixture
async def ledger() -> InMemoryLedger:
    return InMemoryLedger()


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


async def test_initiate_tenant_signup_writes_pevr_cycle(
    ledger: InMemoryLedger,
) -> None:
    cid = tenant_to_uuid("baseworm")
    result = await write_actions.initiate_tenant_signup(
        ledger,
        cid,
        tenant_id=cid,
        slug="slack_team_t12345",
        display_name="Test Workspace",
        signup_source="slack_oauth",
        signup_email="founder@test.com",
        pending_token_hash=_hash("oauth-state"),
    )
    # PEVR cycle: 4 entries.
    assert len(result.entry_ids) == 4

    rows = await ledger.fetch(cid)
    kinds = [r["kind"] for r in rows]
    assert "propose" in kinds
    assert "execute" in kinds
    assert "verify" in kinds
    assert "resolve" in kinds

    execute_rows = [r for r in rows if r["kind"] == "execute"]
    tools = [(r["payload"] or {}).get("tool") for r in execute_rows]
    assert "emit_tenant_signup_initiated" in tools


async def test_complete_tenant_signup_writes_pevr_cycle(
    ledger: InMemoryLedger,
) -> None:
    cid = tenant_to_uuid("baseworm")
    result = await write_actions.complete_tenant_signup(
        ledger,
        cid,
        tenant_id=cid,
        signup_source="email_magic_link",
        assigned_tenant_slug="wormbase-saas-demo",
        signup_email="evaluator@example.com",
    )
    assert len(result.entry_ids) == 4

    rows = await ledger.fetch(cid)
    execute_rows = [r for r in rows if r["kind"] == "execute"]
    tools = [(r["payload"] or {}).get("tool") for r in execute_rows]
    assert "emit_tenant_signup_completed" in tools


async def test_signup_chain_initiated_then_completed(
    ledger: InMemoryLedger,
) -> None:
    """Canonical signup chain: initiated then completed, in order."""
    cid = tenant_to_uuid("baseworm")
    await write_actions.initiate_tenant_signup(
        ledger,
        cid,
        tenant_id=cid,
        slug="slack_team_test",
        display_name="Test",
        signup_source="slack_oauth",
        signup_email=None,
        pending_token_hash=_hash("x"),
    )
    await write_actions.complete_tenant_signup(
        ledger,
        cid,
        tenant_id=cid,
        signup_source="slack_oauth",
        assigned_tenant_slug="slack_team_test",
        signup_email=None,
    )
    rows = await ledger.fetch(cid)
    execute_tools = [
        (r["payload"] or {}).get("tool")
        for r in rows if r["kind"] == "execute"
    ]
    assert execute_tools.index("emit_tenant_signup_initiated") < (
        execute_tools.index("emit_tenant_signup_completed")
    )


async def test_initiate_signup_rejects_invalid_signup_source(
    ledger: InMemoryLedger,
) -> None:
    cid = tenant_to_uuid("baseworm")
    with pytest.raises(Exception):  # Pydantic ValidationError → exception
        await write_actions.initiate_tenant_signup(
            ledger,
            cid,
            tenant_id=cid,
            slug="x",
            display_name="X",
            signup_source="not_real",
            signup_email=None,
            pending_token_hash=_hash("x"),
        )


async def test_signup_chain_does_not_pollute_other_tenants(
    ledger: InMemoryLedger,
) -> None:
    """Two tenants signing up don't leak rows into each other's fold."""
    cid_a = tenant_to_uuid("baseworm")
    cid_b = tenant_to_uuid("democorp")
    await write_actions.initiate_tenant_signup(
        ledger,
        cid_a,
        tenant_id=cid_a,
        slug="baseworm",
        display_name="Baseworm",
        signup_source="slack_oauth",
        signup_email="a@a.com",
        pending_token_hash=_hash("a"),
    )
    await write_actions.initiate_tenant_signup(
        ledger,
        cid_b,
        tenant_id=cid_b,
        slug="democorp",
        display_name="Democorp",
        signup_source="slack_oauth",
        signup_email="b@b.com",
        pending_token_hash=_hash("b"),
    )
    rows_a = await ledger.fetch(cid_a)
    rows_b = await ledger.fetch(cid_b)
    text_a = repr(rows_a)
    text_b = repr(rows_b)
    assert "democorp" not in text_a
    assert "baseworm" not in text_b
    assert "b@b.com" not in text_a
    assert "a@a.com" not in text_b
