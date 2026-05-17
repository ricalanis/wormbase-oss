"""Step 2 (proactivity hook) tests for the relevance gate.

Extends test coverage for the data-source-mention rule that lets the worm
react to "we should pull from Stripe" without an @-mention. See the gate's
``_DATA_SOURCE_KEYWORDS`` constant in ``wormbase_chat_presence.relevance``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from wormbase_chat_presence.relevance import (
    _DATA_SOURCE_KEYWORDS,
    RulesBasedRelevanceGate,
)
from wormbase_core.reactivity import InfraEvent, SemanticInterpretation


def _channel_event(text: str, *, company_id: UUID) -> InfraEvent:
    return InfraEvent(
        source="channel_message",
        payload={},
        ts=datetime(2026, 4, 26, 12, tzinfo=UTC),
        company_id=company_id,
        channel_id="C1",
        person_id="U-bob",
        text=text,
    )


def _data_mention_interp(concepts: list[str], conf: float = 0.84) -> SemanticInterpretation:
    return SemanticInterpretation(
        concepts=concepts,
        event_type="data_mention",
        confidence=conf,
    )


@pytest.mark.parametrize("kw", list(_DATA_SOURCE_KEYWORDS))
async def test_data_source_mention_fires_proactively(kw, ledger, company_id):
    gate = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
        talkativeness={"C1": "responsive"},
    )
    infra = _channel_event(f"we should pull from {kw} for q3", company_id=company_id)
    interp = _data_mention_interp([kw])
    decision = await gate.handle(infra, interp)
    assert decision.should_react, kw
    assert decision.suggested_flow == "mentioned_in_conversation"
    assert "data_source_mention" in decision.reason


async def test_data_source_mention_below_confidence_floor_suppresses(
    ledger, company_id,
):
    gate = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
        talkativeness={"C1": "responsive"},
    )
    infra = _channel_event("stripe maybe?", company_id=company_id)
    interp = _data_mention_interp(["stripe"], conf=0.50)
    decision = await gate.handle(infra, interp)
    # Below 0.6 -> falls through to talkativeness (responsive 0.85).
    assert not decision.should_react


async def test_data_source_mention_in_lurker_channel_is_suppressed(
    ledger, company_id,
):
    gate = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
        talkativeness={"C1": "lurker"},
    )
    infra = _channel_event("we should pull from stripe", company_id=company_id)
    interp = _data_mention_interp(["stripe"])
    decision = await gate.handle(infra, interp)
    assert not decision.should_react
    assert decision.reason == "lurker_suppress"


async def test_data_source_mention_records_decision_with_keyword_in_reason(
    ledger, company_id,
):
    gate = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
        talkativeness={"C1": "responsive"},
    )
    infra = _channel_event("we use snowflake for everything", company_id=company_id)
    interp = _data_mention_interp(["snowflake"])
    decision = await gate.handle(infra, interp)
    assert decision.should_react
    assert "snowflake" in decision.reason


async def test_non_data_mention_event_type_does_not_trigger_proactive_path(
    ledger, company_id,
):
    """A statement that happens to contain 'stripe' but isn't a data_mention
    event_type must NOT fire the proactivity rule. The classifier's typing
    is the gate."""
    gate = RulesBasedRelevanceGate(
        ledger, company_id, mention_handle="@worm",
        talkativeness={"C1": "responsive"},
    )
    infra = _channel_event(
        "stripe is a great company", company_id=company_id,
    )
    interp = SemanticInterpretation(
        concepts=["stripe"], event_type="statement", confidence=0.80,
    )
    decision = await gate.handle(infra, interp)
    # Falls through to talkativeness rules; statement isn't in
    # _REACT_EVENT_TYPES, so suppressed.
    assert not decision.should_react


async def test_keyword_list_aligned_with_remote_archetypes():
    """The ``_DATA_SOURCE_KEYWORDS`` set must include every key in
    ``flows._REMOTE_ARCHETYPE_URIS`` (the proactivity hook would otherwise
    detect a keyword the propose-step can't translate)."""
    from wormbase_chat_presence.chat_flows.mentioned_in_conversation import (
        _REMOTE_ARCHETYPE_URIS,
    )

    for archetype in _REMOTE_ARCHETYPE_URIS:
        assert archetype in _DATA_SOURCE_KEYWORDS, archetype


async def test_dm_path_is_unchanged_by_proactivity_hook(ledger, company_id):
    """DM source short-circuits at the top of ``handle`` regardless of text
    content — the proactivity hook lives in the channel branch only."""
    gate = RulesBasedRelevanceGate(ledger, company_id, mention_handle="@worm")
    infra = InfraEvent(
        source="dm", payload={},
        ts=datetime(2026, 4, 26, 12, tzinfo=UTC),
        company_id=company_id, text="here's my stripe key",
    )
    interp = SemanticInterpretation(
        concepts=["stripe"], event_type="credential_offer", confidence=0.95,
    )
    decision = await gate.handle(infra, interp)
    assert decision.should_react
    assert decision.reason == "dm_always_respond"
