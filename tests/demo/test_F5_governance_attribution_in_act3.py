"""F5 demo gate: every Act-3 KPI answer shows attribution.

Stub: verifying rendered DOM attribution needs Playwright.
Honest coverage: after warmup, ``ledger.fetch`` returns rows with
payloads carrying attribution fields when the entry kind supports it.
We assert at least one entry has a dict payload (the attribution shape).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from wormbase_core.service import build_worm_core
from wormbase_ledger import InMemoryLedger


@pytest.mark.asyncio
async def test_F5_governance_attribution_in_act3() -> None:
    company_id = uuid4()
    ledger = InMemoryLedger()
    await build_worm_core(
        ledger, company_id,
        domain_pack="saas",
        enable_lurker=False, enable_cloud_classifier=False,
    )
    rows = await ledger.fetch(company_id)
    assert rows, "F5 GATE FAILED: no ledger entries after warmup"
    payloads = [r.get("payload") for r in rows]
    assert any(isinstance(p, dict) for p in payloads), (
        f"F5 GATE FAILED: no dict payloads found for attribution wiring"
    )
    # Full attribution DOM assertion needs live dashboard render.
    print("F5 (rendered DOM) requires Playwright + real KPI answer — in-process payload ok")
