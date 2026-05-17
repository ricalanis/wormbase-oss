"""Warmup -> ChatStore round-trip: warmup writes the company-wide template;
per-channel policy reads still see the default until admin sets one."""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_chat_presence.chat_store import _LedgerBackedChatStore
from wormbase_governance.policies import PolicyLoader
from wormbase_ledger import InMemoryLedger


@pytest.mark.asyncio
async def test_warmup_writes_template_but_channel_read_returns_default() -> None:
    company = uuid4()
    ledger = InMemoryLedger()
    store = _LedgerBackedChatStore(ledger=ledger)

    # Run warmup.
    loader = PolicyLoader(ledger)
    await loader.load_templates(company, domain_pack="saas")

    # Read a specific channel's policy — no per-channel write happened, so default.
    policy = await store.read_policy(company_id=company, channel_id="C_NEW")
    assert policy.talkativeness == "responsive"
    assert policy.daily_interjection_budget == 3

    # Verify the warmup template's policy_applied IS in the ledger
    # (audit trail check).
    rows = await ledger.fetch(company)
    template_entries = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_policy_applied"
        and r["payload"]["args"].get("policy_name") == "policy:channel_talkativeness"
    ]
    assert len(template_entries) == 1, (
        f"warmup must write the template entry once; got {len(template_entries)}"
    )
