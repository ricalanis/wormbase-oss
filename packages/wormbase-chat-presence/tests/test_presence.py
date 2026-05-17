"""Block F tests: Presence (formerly ConversationContract)."""

from __future__ import annotations

from wormbase_chat_presence.presence import ConversationContract
from wormbase_chat_presence.relevance import RulesBasedRelevanceGate
from wormbase_core.reactivity import InfraEvent, SemanticInterpretation


class _StubInterjectionGate:
    def __init__(self, allow=True):
        self._allow = allow

    async def allow(self, channel_id, qtype):
        return self._allow


def make_event(*, source, text, channel_id=None, ts, company_id, person_id=None):
    return InfraEvent(
        source=source, payload={}, ts=ts, company_id=company_id,
        channel_id=channel_id, text=text, person_id=person_id,
    )


async def test_dm_always_speaks(ledger, company_id, clock):
    rg = RulesBasedRelevanceGate(ledger, company_id, mention_handle="@worm")
    cc = ConversationContract(rg, _StubInterjectionGate(), ledger, company_id)
    e = make_event(source="dm", text="hi", ts=clock.now(),
                   company_id=company_id, person_id="U1")
    speak, reason = await cc.should_speak(
        e, SemanticInterpretation(confidence=0.0)
    )
    assert speak
    assert reason == "dm_always_respond"


async def test_channel_mention_speaks(ledger, company_id, clock):
    rg = RulesBasedRelevanceGate(ledger, company_id, mention_handle="@worm")
    cc = ConversationContract(rg, _StubInterjectionGate(), ledger, company_id)
    e = make_event(source="channel_message", text="@worm churn?", channel_id="C1",
                   ts=clock.now(), company_id=company_id)
    speak, reason = await cc.should_speak(
        e, SemanticInterpretation(concepts=["churn"], event_type="question",
                                  confidence=0.8)
    )
    assert speak
    assert reason == "mention"


async def test_lurker_channel_never_speaks(ledger, company_id, clock):
    rg = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
        talkativeness={"C1": "lurker"},
    )
    cc = ConversationContract(rg, _StubInterjectionGate(), ledger, company_id)
    e = make_event(source="channel_message", text="MRR is up",
                   channel_id="C1", ts=clock.now(), company_id=company_id)
    speak, reason = await cc.should_speak(
        e, SemanticInterpretation(concepts=["mrr"], event_type="question",
                                  confidence=0.99)
    )
    assert not speak


async def test_responsive_consumes_interjection_budget(ledger, company_id, clock):
    rg = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
        talkativeness={"C1": "responsive"},
    )
    gate = _StubInterjectionGate(allow=False)
    cc = ConversationContract(rg, gate, ledger, company_id)
    e = make_event(source="channel_message", text="we should pull stripe",
                   channel_id="C1", ts=clock.now(), company_id=company_id)
    interp = SemanticInterpretation(
        concepts=["stripe"], event_type="data_mention", confidence=0.85
    )
    speak, reason = await cc.should_speak(e, interp)
    assert not speak
    assert reason == "interjection_budget"


async def test_listen_for_ingest_always_true(ledger, company_id, clock):
    rg = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
        talkativeness={"C1": "lurker"},
    )
    cc = ConversationContract(rg, _StubInterjectionGate(False), ledger, company_id)
    e = make_event(source="channel_message", text="anything", channel_id="C1",
                   ts=clock.now(), company_id=company_id)
    assert cc.should_ingest(e) is True


async def test_digest_tick_fires_once_per_day(ledger, company_id, clock):
    rg = RulesBasedRelevanceGate(ledger, company_id, mention_handle="@worm")
    cc = ConversationContract(rg, _StubInterjectionGate(), ledger, company_id)
    first = await cc.on_digest_tick("C1", now=clock.now())
    assert first
    second = await cc.on_digest_tick("C1", now=clock.now())
    assert not second
    clock.tick(days=2)
    third = await cc.on_digest_tick("C1", now=clock.now())
    assert third
