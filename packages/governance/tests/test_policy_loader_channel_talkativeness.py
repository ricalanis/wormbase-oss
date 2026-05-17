"""PolicyLoader writes a policy_applied entry for channel_talkativeness."""
from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_governance.policies import PolicyLoader
from wormbase_ledger import InMemoryLedger


@pytest.mark.asyncio
async def test_policy_loader_emits_channel_talkativeness() -> None:
    company_id = uuid4()
    ledger = InMemoryLedger()
    loader = PolicyLoader(ledger)
    applied = await loader.load_templates(company_id, domain_pack="saas")

    names = [p.name for p in applied]
    assert "policy:channel_talkativeness" in names, (
        f"expected policy:channel_talkativeness in applied policies; got {names}"
    )

    # Verify a policy_applied entry was written.
    rows = await ledger.fetch(company_id)
    talkativeness_entries = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_policy_applied"
        and r["payload"]["args"].get("policy_name") == "policy:channel_talkativeness"
    ]
    assert len(talkativeness_entries) == 1, (
        f"expected exactly one policy_applied entry; got {len(talkativeness_entries)}"
    )
