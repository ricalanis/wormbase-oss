"""Block C tests: reactivity triad."""

from __future__ import annotations

import pytest

from wormbase_core.reactivity import (
    DefaultInfrastructureTrigger,
    DefaultSemanticTrigger,
    InfraEvent,
    ReactivityPipeline,
    SemanticInterpretation,
)
from wormbase_core.relevance import RulesBasedRelevanceGate


# -- helpers ---------------------------------------------------------


class StubClassifier:
    """Returns whatever interpretation it's been pre-loaded with."""

    def __init__(self, interp: SemanticInterpretation) -> None:
        self.interp = interp
        self.calls: list[tuple[str, dict]] = []

    async def classify(self, text, context):  # type: ignore[no-untyped-def]
        self.calls.append((text, context))
        return self.interp


# -- infrastructure trigger ------------------------------------------


async def test_infra_trigger_normalizes_channel_message(ledger, company_id):
    trigger = DefaultInfrastructureTrigger(ledger, company_id)
    raw = {
        "type": "channel_message",
        "ts": "2026-04-22T12:00:00+00:00",
        "channel_id": "C123",
        "user_id": "U456",
        "text": "what's our churn?",
        "message_id": "1745330400.000100",
    }
    e = await trigger.handle(raw)
    assert isinstance(e, InfraEvent)
    assert e.source == "channel_message"
    assert e.channel_id == "C123"
    assert e.person_id == "U456"
    assert e.text == "what's our churn?"


async def test_infra_trigger_rejects_malformed_event(ledger, company_id):
    trigger = DefaultInfrastructureTrigger(ledger, company_id)
    with pytest.raises(ValueError):
        await trigger.handle({"type": "channel_message"})  # missing ts


async def test_infra_trigger_writes_ledger_entry(ledger, company_id):
    trigger = DefaultInfrastructureTrigger(ledger, company_id)
    await trigger.handle({
        "type": "channel_message",
        "ts": "2026-04-22T12:00:00+00:00",
        "text": "hi",
    })
    rows = await ledger.fetch(company_id)
    # PEVR write = 4 entries; one stage logged.
    assert len(rows) == 4
    assert any(
        r["kind"] == "execute"
        and r["payload"]["args"]["content"] == "reactivity_stage:infrastructure_trigger"
        for r in rows
    )


# -- semantic trigger ------------------------------------------------


async def test_semantic_trigger_passes_through_high_confidence(ledger, company_id):
    interp = SemanticInterpretation(
        concepts=["churn"], event_type="question", confidence=0.92
    )
    sem = DefaultSemanticTrigger(StubClassifier(interp), ledger, company_id)
    infra = InfraEvent(
        source="channel_message",
        payload={},
        ts=__import__("datetime").datetime(2026, 4, 22, 12, tzinfo=__import__("datetime").UTC),
        company_id=company_id,
        text="churn?",
    )
    result = await sem.handle(infra)
    assert result is not None
    assert result.event_type == "question"


async def test_semantic_trigger_returns_none_below_floor(ledger, company_id):
    interp = SemanticInterpretation(
        concepts=[], event_type="other", confidence=0.10
    )
    sem = DefaultSemanticTrigger(StubClassifier(interp), ledger, company_id,
                                 confidence_floor=0.30)
    from datetime import UTC, datetime
    infra = InfraEvent(
        source="channel_message", payload={},
        ts=datetime(2026, 4, 22, 12, tzinfo=UTC),
        company_id=company_id, text="lunch?",
    )
    assert await sem.handle(infra) is None


# -- relevance gate --------------------------------------------------


async def test_relevance_dm_always_reacts(ledger, company_id):
    gate = RulesBasedRelevanceGate(ledger, company_id, mention_handle="@worm")
    from datetime import UTC, datetime
    infra = InfraEvent(
        source="dm", payload={},
        ts=datetime(2026, 4, 22, 12, tzinfo=UTC),
        company_id=company_id, text="hi",
    )
    interp = SemanticInterpretation(confidence=0.0)
    decision = await gate.handle(infra, interp)
    assert decision.should_react
    assert decision.reason == "dm_always_respond"


async def test_relevance_mention_in_channel_reacts(ledger, company_id):
    gate = RulesBasedRelevanceGate(ledger, company_id, mention_handle="@worm")
    from datetime import UTC, datetime
    infra = InfraEvent(
        source="channel_message", payload={},
        ts=datetime(2026, 4, 22, 12, tzinfo=UTC),
        company_id=company_id,
        channel_id="C1", text="@worm what's MRR?",
    )
    interp = SemanticInterpretation(
        concepts=["mrr"], event_type="question", confidence=0.4
    )
    decision = await gate.handle(infra, interp)
    assert decision.should_react
    assert decision.reason == "mention"


async def test_relevance_lurker_channel_suppresses_unconditionally(ledger, company_id):
    gate = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
        talkativeness={"C1": "lurker"},
    )
    from datetime import UTC, datetime
    infra = InfraEvent(
        source="channel_message", payload={},
        ts=datetime(2026, 4, 22, 12, tzinfo=UTC),
        company_id=company_id, channel_id="C1", text="MRR is 1.2M",
    )
    interp = SemanticInterpretation(
        concepts=["mrr"], event_type="question", confidence=0.99
    )
    decision = await gate.handle(infra, interp)
    assert not decision.should_react
    assert decision.reason == "lurker_suppress"


async def test_relevance_proactive_channel_fires_on_data_mention(ledger, company_id):
    gate = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
        talkativeness={"C1": "proactive"},
    )
    from datetime import UTC, datetime
    infra = InfraEvent(
        source="channel_message", payload={},
        ts=datetime(2026, 4, 22, 12, tzinfo=UTC),
        company_id=company_id, channel_id="C1", text="we should pull stripe",
    )
    interp = SemanticInterpretation(
        concepts=["stripe"], event_type="data_mention", confidence=0.80
    )
    decision = await gate.handle(infra, interp)
    assert decision.should_react


async def test_relevance_responsive_below_threshold_suppresses(ledger, company_id):
    gate = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
        talkativeness={"C1": "responsive"},
    )
    from datetime import UTC, datetime
    infra = InfraEvent(
        source="channel_message", payload={},
        ts=datetime(2026, 4, 22, 12, tzinfo=UTC),
        company_id=company_id, channel_id="C1", text="ehh",
    )
    interp = SemanticInterpretation(
        concepts=[], event_type="other", confidence=0.4
    )
    decision = await gate.handle(infra, interp)
    assert not decision.should_react


async def test_relevance_records_decision_to_ledger(ledger, company_id):
    gate = RulesBasedRelevanceGate(ledger, company_id, mention_handle="@worm")
    from datetime import UTC, datetime
    infra = InfraEvent(
        source="dm", payload={},
        ts=datetime(2026, 4, 22, 12, tzinfo=UTC),
        company_id=company_id, text="hi",
    )
    interp = SemanticInterpretation(confidence=0.0)
    await gate.handle(infra, interp)
    rows = await ledger.fetch(company_id)
    assert any(
        r["kind"] == "execute"
        and "relevance_decision" in r["payload"]["args"]["tags"]
        for r in rows
    )


# -- pipeline glue ---------------------------------------------------


async def test_pipeline_short_circuits_when_semantic_returns_none(ledger, company_id):
    interp = SemanticInterpretation(confidence=0.05)
    sem = DefaultSemanticTrigger(StubClassifier(interp), ledger, company_id)
    infra_t = DefaultInfrastructureTrigger(ledger, company_id)
    gate = RulesBasedRelevanceGate(ledger, company_id, mention_handle="@worm")
    pipeline = ReactivityPipeline(infra_t, sem, gate, ledger, company_id)
    result = await pipeline.process({
        "type": "channel_message",
        "ts": "2026-04-22T12:00:00+00:00",
        "channel_id": "C1",
        "user_id": "U1",
        "text": "lunch?",
    })
    assert result is None
    rows = await ledger.fetch(company_id)
    # infra_trigger + semantic_trigger should be present, NO relevance_decision.
    contents = [
        r["payload"]["args"]["content"]
        for r in rows if r["kind"] == "execute"
    ]
    assert "reactivity_stage:infrastructure_trigger" in contents
    assert "reactivity_stage:semantic_trigger" in contents
    assert not any("relevance" in c for c in contents)


async def test_pipeline_full_flow_produces_three_stages(ledger, company_id):
    interp = SemanticInterpretation(
        concepts=["churn"], event_type="question", confidence=0.95
    )
    sem = DefaultSemanticTrigger(StubClassifier(interp), ledger, company_id)
    infra_t = DefaultInfrastructureTrigger(ledger, company_id)
    gate = RulesBasedRelevanceGate(ledger, company_id, mention_handle="@worm")
    pipeline = ReactivityPipeline(infra_t, sem, gate, ledger, company_id)
    decision = await pipeline.process({
        "type": "dm",
        "ts": "2026-04-22T12:00:00+00:00",
        "user_id": "U1",
        "text": "what's churn?",
    })
    assert decision is not None
    assert decision.should_react
