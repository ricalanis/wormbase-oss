"""MentionedInConversationFlow + remote-archetype tests — lifted from
apps/worm-core/tests/test_flows.py in Wave B (D1)."""

from __future__ import annotations

import pytest

from wormbase_chat_presence.chat_flows import (
    MentionedInConversationFlow,
    propose_remote_archetype,
    recognized_remote_archetypes,
)
from wormbase_core.reactivity import InfraEvent, SemanticInterpretation
from wormbase_core.source_builder import SourceBuilder


class StubInterjectionGate:
    def __init__(self, allow=True):
        self._allow = allow
        self.calls = []

    async def allow(self, channel_id, qtype):
        self.calls.append((channel_id, qtype))
        return self._allow


# -- 3) mentioned_in_conversation -----------------------------------


async def test_mentioned_flow_fires_after_three_distinct_mentioners(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    gate = StubInterjectionGate(allow=True)
    flow = MentionedInConversationFlow(builder, ledger, gate)
    interp = SemanticInterpretation(
        concepts=["stripe"], event_type="data_mention", confidence=0.85
    )
    # 3 distinct people
    for i in range(3):
        clock.tick(seconds=10)
        event = InfraEvent(
            source="channel_message", payload={}, ts=clock.now(),
            company_id=company_id, channel_id="C1",
            person_id=f"U-{i}", text="we should pull stripe",
        )
        await flow.on_semantic_hit(event, interp)
    # On the third call, a proposal must have been emitted.
    rows = await ledger.fetch(company_id)
    proposals = [r for r in rows if r["kind"] == "execute"
                 and r["payload"]["tool"] == "emit_source_proposed"]
    assert len(proposals) == 1


async def test_mentioned_flow_same_person_repeated_does_not_fire(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    gate = StubInterjectionGate(allow=True)
    flow = MentionedInConversationFlow(builder, ledger, gate)
    interp = SemanticInterpretation(
        concepts=["stripe"], event_type="data_mention", confidence=0.85
    )
    for _ in range(5):
        clock.tick(seconds=5)
        event = InfraEvent(
            source="channel_message", payload={}, ts=clock.now(),
            company_id=company_id, channel_id="C1",
            person_id="U-A", text="stripe stripe stripe",
        )
        await flow.on_semantic_hit(event, interp)
    rows = await ledger.fetch(company_id)
    proposals = [r for r in rows if r["kind"] == "execute"
                 and r["payload"]["tool"] == "emit_source_proposed"]
    assert len(proposals) == 0


async def test_mentioned_flow_respects_interjection_budget(ledger, company_id, clock):
    builder = SourceBuilder(ledger, clock)
    gate = StubInterjectionGate(allow=False)
    flow = MentionedInConversationFlow(builder, ledger, gate)
    interp = SemanticInterpretation(
        concepts=["stripe"], event_type="data_mention", confidence=0.85
    )
    for i in range(3):
        clock.tick(seconds=5)
        event = InfraEvent(
            source="channel_message", payload={}, ts=clock.now(),
            company_id=company_id, channel_id="C1",
            person_id=f"U-{i}", text="stripe again",
        )
        await flow.on_semantic_hit(event, interp)
    rows = await ledger.fetch(company_id)
    proposals = [r for r in rows if r["kind"] == "execute"
                 and r["payload"]["tool"] == "emit_source_proposed"]
    assert len(proposals) == 0


# -- 6) remote-archetype mention recognizers -------------------------


def test_recognized_remote_archetypes_picks_up_known_keywords():
    assert recognized_remote_archetypes(
        "we should pull our stripe and salesforce data"
    ) == ["stripe", "salesforce"]
    assert recognized_remote_archetypes(
        "the postgres warehouse and s3 exports go via snowflake"
    ) == ["snowflake", "postgres", "s3"]
    assert recognized_remote_archetypes("nothing relevant here") == []


async def test_propose_remote_archetype_writes_source_proposed_with_uri_scheme(
    ledger, company_id, clock,
):
    builder = SourceBuilder(ledger, clock)
    cid = await propose_remote_archetype(
        builder,
        company_id=company_id,
        archetype="stripe",
        added_in_response_to="mentions:stripe",
    )
    assert cid is not None
    rows = await ledger.fetch(company_id)
    proposals = [r for r in rows if r["kind"] == "execute"
                 and r["payload"]["tool"] == "emit_source_proposed"]
    assert len(proposals) == 1
    args = proposals[0]["payload"]["args"]
    assert args["source_kind"] == "rest_api"
    assert args["uri"].startswith("https://api.stripe.com")
    assert args["added_via_flow"] == "mentioned_in_conversation"


async def test_propose_remote_archetype_snowflake_uses_database_kind(
    ledger, company_id, clock,
):
    builder = SourceBuilder(ledger, clock)
    await propose_remote_archetype(
        builder, company_id=company_id, archetype="snowflake",
    )
    rows = await ledger.fetch(company_id)
    proposals = [r for r in rows if r["kind"] == "execute"
                 and r["payload"]["tool"] == "emit_source_proposed"]
    args = proposals[0]["payload"]["args"]
    assert args["source_kind"] == "database"
    assert args["uri"].startswith("snowflake://")


async def test_propose_remote_archetype_unknown_keyword_raises(
    ledger, company_id, clock,
):
    builder = SourceBuilder(ledger, clock)
    with pytest.raises(ValueError):
        await propose_remote_archetype(
            builder, company_id=company_id, archetype="not_a_real_thing",
        )


# -- 7) on_proactive_mention (Step 2 proactivity hook) ---------------


async def test_on_proactive_mention_writes_source_proposed_and_offer(
    ledger, company_id, clock,
):
    """A single proactive mention writes BOTH a source_proposed and a
    proactive_offer entry, with the offer carrying the demo speech act."""
    builder = SourceBuilder(ledger, clock)
    flow = MentionedInConversationFlow(builder, ledger, StubInterjectionGate())
    event = InfraEvent(
        source="channel_message", payload={}, ts=clock.now(),
        company_id=company_id, channel_id="C-data", person_id="U-bob",
        message_id="msg-1", text="we should integrate Stripe data",
    )
    result = await flow.on_proactive_mention(event)
    assert result is not None
    assert result.archetype == "stripe"
    assert result.channel_id == "C-data"
    assert "Stripe" in result.offer_text
    assert "DM" in result.offer_text

    rows = await ledger.fetch(company_id)
    tools = [r["payload"]["tool"] for r in rows if r["kind"] == "execute"]
    assert "emit_source_proposed" in tools
    assert "emit_proactive_offer" in tools

    proposal = [
        r for r in rows
        if r["kind"] == "execute" and r["payload"]["tool"] == "emit_source_proposed"
    ][0]
    assert proposal["payload"]["args"]["added_via_flow"] == "mentioned_in_conversation"
    assert proposal["payload"]["args"]["added_in_response_to"].startswith(
        "proactive:stripe:"
    )

    offer = [
        r for r in rows
        if r["kind"] == "execute" and r["payload"]["tool"] == "emit_proactive_offer"
    ][0]
    args = offer["payload"]["args"]
    assert args["archetype"] == "stripe"
    assert args["channel_id"] == "C-data"
    assert args["prompted_by_message_id"] == "msg-1"
    assert args["prompted_by_person"] == "U-bob"


async def test_on_proactive_mention_returns_none_without_archetype(
    ledger, company_id, clock,
):
    builder = SourceBuilder(ledger, clock)
    flow = MentionedInConversationFlow(builder, ledger, StubInterjectionGate())
    event = InfraEvent(
        source="channel_message", payload={}, ts=clock.now(),
        company_id=company_id, channel_id="C1", person_id="U-1",
        message_id="m", text="totally unrelated chatter",
    )
    result = await flow.on_proactive_mention(event)
    assert result is None


async def test_on_proactive_mention_picks_first_archetype_when_multiple(
    ledger, company_id, clock,
):
    builder = SourceBuilder(ledger, clock)
    flow = MentionedInConversationFlow(builder, ledger, StubInterjectionGate())
    event = InfraEvent(
        source="channel_message", payload={}, ts=clock.now(),
        company_id=company_id, channel_id="C1", person_id="U-1",
        message_id="m", text="we should join stripe and salesforce",
    )
    result = await flow.on_proactive_mention(event)
    assert result is not None
    # `recognized_remote_archetypes` returns dict-order; stripe first.
    assert result.archetype == "stripe"
