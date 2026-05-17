"""Block E flow tests — non-lifted flows only.

Per Wave B (D1): the four chat-driven flows lifted to
``packages/wormbase-chat-presence/tests/chat_flows/``. The two flows
that stay in worm-core (DashboardFormFlow, LakeDiscoveryFlow) keep their
tests here. LakeDiscoveryFlow has its own dedicated test file
(``test_lake_builder.py``); only DashboardFormFlow lives here.
"""

from __future__ import annotations

from uuid import uuid4

from wormbase_core.flows import (
    DashboardFormFlow,
    DashboardSourceSubmission,
)
from wormbase_core.source_builder import SourceBuilder
from wormbase_core.types import PIIGateResult


class StubPIIGate:
    async def check(self, text, context):
        return PIIGateResult(redacted_text=text, matches=[], changed=False)


# -- 4) dashboard_form ------------------------------------------------


async def test_dashboard_form_submission_writes_full_sequence(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    flow = DashboardFormFlow(builder, StubPIIGate())
    submission = DashboardSourceSubmission(
        submission_id="sub-1",
        uri="https://api.example.com/data",
        type="rest_api",
        domain="finance",
        classification="internal",
        owner_person_id=uuid4(),
        submitter_person_id=uuid4(),
        company_id=company_id,
    )
    await flow.on_submission(submission)
    rows = await ledger.fetch(company_id)
    tools = [r["payload"]["tool"] for r in rows if r["kind"] == "execute"]
    for t in ("emit_source_proposed", "emit_source_confirmed",
              "emit_source_connected", "emit_source_profiled"):
        assert t in tools
