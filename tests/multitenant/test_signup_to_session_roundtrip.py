"""Phase 1B.H — cross-package contract: signup → install → completed.

Pairs with the spike + plan at:
  - docs/superpowers/notes/2026-05-04-multitenancy-v2-spike.md
  - docs/superpowers/plans/2026-05-04-multitenancy-v2.md

Verifies the canonical signup chain that the dashboard exercises on a
Slack OAuth callback:

  1. tenant_signup_initiated emitted for an unknown workspace.
  2. complete_install runs (writes the install + grants chain).
  3. tenant_signup_completed emitted after install_completed.

The chain produces an isolated, ordered ledger sequence per tenant.
Two parallel signups for two workspaces produce no cross-tenant leak.

The TypeScript companion at apps/dashboard/tests/lib/auth-session.test.ts
binds the cookie roundtrip at the Node layer.
"""
from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
import pytest_asyncio

from wormbase_core import write_actions
from wormbase_core.service import tenant_to_uuid
from wormbase_ledger import InMemoryLedger


SLACK_TEAM = "T1BTEST5"
TENANT_SLUG = f"slack_team_{SLACK_TEAM.lower()}"


@pytest_asyncio.fixture
async def ledger() -> InMemoryLedger:
    return InMemoryLedger()


async def test_signup_chain_round_trip(ledger: InMemoryLedger) -> None:
    """signup_initiated → install_completed → signup_completed produces a
    ledger sequence with the canonical ordering and the right entry kinds."""
    cid = tenant_to_uuid(TENANT_SLUG)

    # Step 1: signup_initiated (Slack callback would emit this on unknown workspace).
    pending_hash = hashlib.sha256(b"oauth-state-token").hexdigest()
    await write_actions.initiate_tenant_signup(
        ledger,
        cid,
        tenant_id=cid,
        slug=TENANT_SLUG,
        display_name="Test Workspace",
        signup_source="slack_oauth",
        signup_email="founder@test-workspace.com",
        pending_token_hash=pending_hash,
    )

    # Step 2: install completes (existing helper).
    install_result = await write_actions.complete_install(
        ledger,
        cid,
        tenant_id=cid,
        platform="slack",
        installer_email="founder@test-workspace.com",
        installer_name="Founder",
        installer_avatar_url=None,
        platform_user_id="U-FOUNDER",
        oauth_grant_ref="kms://wormbase/install/test",
        scopes=["chat:write"],
        bot_user_id="B-FOUNDER",
    )
    assert install_result["install_id"]

    # Step 3: signup_completed.
    await write_actions.complete_tenant_signup(
        ledger,
        cid,
        tenant_id=cid,
        signup_source="slack_oauth",
        assigned_tenant_slug=TENANT_SLUG,
        signup_email="founder@test-workspace.com",
    )

    # Step 4: ledger has both signup entries + the install chain in order.
    rows = await ledger.fetch(cid)
    kinds = [
        (r.get("payload") or {}).get("tool")
        for r in rows
        if r.get("kind") == "execute"
    ]
    assert "emit_tenant_signup_initiated" in kinds
    assert "emit_tenant_signup_completed" in kinds
    assert "emit_install_completed" in kinds
    # Ordering: initiated before install_completed before completed.
    initiated_idx = kinds.index("emit_tenant_signup_initiated")
    install_idx = kinds.index("emit_install_completed")
    completed_idx = kinds.index("emit_tenant_signup_completed")
    assert initiated_idx < install_idx < completed_idx, (
        f"signup chain out of order: initiated={initiated_idx}, "
        f"install={install_idx}, completed={completed_idx}"
    )


async def test_signup_chain_does_not_leak_to_other_tenants(
    ledger: InMemoryLedger,
) -> None:
    """Two parallel signups for two different workspaces produce two
    independent ledger streams; neither tenant's signup chain appears in
    the other's ledger fetch."""
    slug_a = f"slack_team_{uuid4().hex[:8]}"
    slug_b = f"slack_team_{uuid4().hex[:8]}"
    cid_a = tenant_to_uuid(slug_a)
    cid_b = tenant_to_uuid(slug_b)

    h = "a" * 64
    await write_actions.initiate_tenant_signup(
        ledger,
        cid_a,
        tenant_id=cid_a,
        slug=slug_a,
        display_name="A",
        signup_source="slack_oauth",
        signup_email="a@a.com",
        pending_token_hash=h,
    )
    await write_actions.initiate_tenant_signup(
        ledger,
        cid_b,
        tenant_id=cid_b,
        slug=slug_b,
        display_name="B",
        signup_source="slack_oauth",
        signup_email="b@b.com",
        pending_token_hash=h,
    )

    rows_a = await ledger.fetch(cid_a)
    rows_b = await ledger.fetch(cid_b)

    text_a = repr(rows_a)
    text_b = repr(rows_b)
    assert slug_b not in text_a
    assert slug_a not in text_b
    assert "a@a.com" not in text_b
    assert "b@b.com" not in text_a


async def test_demo_seed_carousel_drives_canonical_signup_chain(
    ledger: InMemoryLedger,
) -> None:
    """The demo seed carousel uses the same write_actions surface
    that Slack OAuth and email magic-link use. Pin that the
    signup_source enum slot ``demo_seed`` produces a chain
    structurally identical to the Slack OAuth chain modulo the
    signup_source label."""
    slug = "wormbase-saas-demo"
    cid = tenant_to_uuid(slug)
    pending_hash = hashlib.sha256(b"demo-seed:wormbase-saas-demo").hexdigest()

    await write_actions.initiate_tenant_signup(
        ledger,
        cid,
        tenant_id=cid,
        slug=slug,
        display_name="WormBase SaaS Demo",
        signup_source="demo_seed",
        signup_email=None,
        pending_token_hash=pending_hash,
    )
    await write_actions.complete_tenant_signup(
        ledger,
        cid,
        tenant_id=cid,
        signup_source="demo_seed",
        assigned_tenant_slug=slug,
        signup_email=None,
    )

    rows = await ledger.fetch(cid)
    initiated_args = next(
        (r.get("payload", {}).get("args") for r in rows
         if r.get("kind") == "execute"
         and (r.get("payload") or {}).get("tool")
         == "emit_tenant_signup_initiated"),
        None,
    )
    completed_args = next(
        (r.get("payload", {}).get("args") for r in rows
         if r.get("kind") == "execute"
         and (r.get("payload") or {}).get("tool")
         == "emit_tenant_signup_completed"),
        None,
    )
    assert initiated_args is not None
    assert completed_args is not None
    assert initiated_args["signup_source"] == "demo_seed"
    assert completed_args["signup_source"] == "demo_seed"
    assert initiated_args["slug"] == slug
    assert completed_args["assigned_tenant_slug"] == slug


async def test_magic_link_carousel_chain_records_assigned_slug(
    ledger: InMemoryLedger,
) -> None:
    """For magic-link signups the initiated entry's slug is the
    evaluator's email-derived placeholder, but the completed entry's
    assigned_tenant_slug is the demo carousel slug picked by the
    round-robin policy. Pin that the contract permits this asymmetry."""
    eval_email = "evaluator@example.com"
    placeholder_slug = f"magiclink_{uuid4().hex[:8]}"
    placeholder_cid = tenant_to_uuid(placeholder_slug)
    pending_hash = hashlib.sha256(b"magic-link-token").hexdigest()

    await write_actions.initiate_tenant_signup(
        ledger,
        placeholder_cid,
        tenant_id=placeholder_cid,
        slug=placeholder_slug,
        display_name=f"Pending evaluator: {eval_email}",
        signup_source="email_magic_link",
        signup_email=eval_email,
        pending_token_hash=pending_hash,
    )

    # Confirm step picks a demo slug from the carousel — distinct from
    # the placeholder slug used in initiated.
    assigned_slug = "wormbase-fintech-demo"
    assigned_cid = tenant_to_uuid(assigned_slug)
    await write_actions.complete_tenant_signup(
        ledger,
        assigned_cid,
        tenant_id=assigned_cid,
        signup_source="email_magic_link",
        assigned_tenant_slug=assigned_slug,
        signup_email=eval_email,
    )

    placeholder_rows = await ledger.fetch(placeholder_cid)
    assigned_rows = await ledger.fetch(assigned_cid)

    placeholder_kinds = [
        (r.get("payload") or {}).get("tool")
        for r in placeholder_rows
        if r.get("kind") == "execute"
    ]
    assigned_kinds = [
        (r.get("payload") or {}).get("tool")
        for r in assigned_rows
        if r.get("kind") == "execute"
    ]
    # The placeholder ledger has only the initiated step.
    assert "emit_tenant_signup_initiated" in placeholder_kinds
    assert "emit_tenant_signup_completed" not in placeholder_kinds
    # The assigned demo tenant has only the completed step.
    assert "emit_tenant_signup_completed" in assigned_kinds
    assert "emit_tenant_signup_initiated" not in assigned_kinds
