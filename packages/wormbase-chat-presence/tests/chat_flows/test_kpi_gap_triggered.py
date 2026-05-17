"""KpiGapTriggeredFlow tests — lifted from apps/worm-core/tests/test_flows.py
in Wave B (D1)."""

from __future__ import annotations

from wormbase_chat_presence.chat_flows import KpiGap, KpiGapTriggeredFlow
from wormbase_core.source_builder import SourceBuilder


class StubInterjectionGate:
    def __init__(self, allow=True):
        self._allow = allow
        self.calls = []

    async def allow(self, channel_id, qtype):
        self.calls.append((channel_id, qtype))
        return self._allow


class StubChat:
    def __init__(self):
        self.sent = []

    async def send(self, channel_id, text, *, speech_act="proposal"):
        self.sent.append((channel_id, text, speech_act))


# -- 5) kpi_gap_triggered ---------------------------------------------


async def test_kpi_gap_proposes_and_posts_chat_intent(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    gate = StubInterjectionGate(allow=True)
    chat = StubChat()
    flow = KpiGapTriggeredFlow(builder, ledger, gate, chat)
    gap = KpiGap(kpi_id="churn", owner_channel_id="C-finance")
    cid = await flow.propose_for_gap(company_id, gap, now=clock.now())
    assert cid is not None
    rows = await ledger.fetch(company_id)
    proposals = [r for r in rows if r["kind"] == "execute"
                 and r["payload"]["tool"] == "emit_source_proposed"]
    assert len(proposals) == 1
    assert proposals[0]["payload"]["args"]["added_in_response_to"] == "kpi:churn"
    assert chat.sent and "churn" in chat.sent[0][1]


async def test_kpi_gap_skips_when_recent_proposal_exists(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    gate = StubInterjectionGate(allow=True)
    chat = StubChat()
    flow = KpiGapTriggeredFlow(builder, ledger, gate, chat)
    gap = KpiGap(kpi_id="churn", owner_channel_id="C-finance")
    await flow.propose_for_gap(company_id, gap, now=clock.now())
    clock.tick(hours=1)
    second = await flow.propose_for_gap(company_id, gap, now=clock.now())
    assert second is None


async def test_kpi_gap_respects_interjection_budget(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    gate = StubInterjectionGate(allow=False)
    chat = StubChat()
    flow = KpiGapTriggeredFlow(builder, ledger, gate, chat)
    gap = KpiGap(kpi_id="churn", owner_channel_id="C-finance")
    cid = await flow.propose_for_gap(company_id, gap, now=clock.now())
    assert cid is None
    rows = await ledger.fetch(company_id)
    proposals = [r for r in rows if r["kind"] == "execute"
                 and r["payload"]["tool"] == "emit_source_proposed"]
    assert len(proposals) == 0
