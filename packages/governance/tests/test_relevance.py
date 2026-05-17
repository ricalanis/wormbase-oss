"""Tests for wormbase_governance.relevance after Block B lift."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from wormbase_governance.relevance import (
    RulesBasedRelevanceGate,
    _DATA_SOURCE_KEYWORDS,
)
from wormbase_ledger import InMemoryLedger
from wormbase_core.reactivity import (
    InfraEvent,
    SemanticInterpretation,
)


@pytest.fixture
def company_id():
    return uuid4()


@pytest.fixture
def ledger():
    return InMemoryLedger()


async def test_dm_always_reacts(ledger, company_id):
    gate = RulesBasedRelevanceGate(ledger, company_id, mention_handle="@worm")
    infra = InfraEvent(
        source="dm", payload={}, ts=datetime.now(UTC),
        company_id=company_id, channel_id=None, person_id="u1",
        message_id="m1", text="hi worm",
    )
    interp = SemanticInterpretation(event_type="question", confidence=0.5)
    decision = await gate.handle(infra, interp)
    assert decision.should_react is True
    assert decision.reason == "dm_always_respond"


async def test_data_source_keyword_constant_present():
    """Predicate parity with wormbase_chat_presence.predicates."""
    assert "stripe" in _DATA_SOURCE_KEYWORDS
    assert "snowflake" in _DATA_SOURCE_KEYWORDS


async def test_legacy_worm_core_path_still_works():
    """Block B shim: wormbase_core.relevance.RulesBasedRelevanceGate is the same class."""
    from wormbase_core.relevance import RulesBasedRelevanceGate as LegacyA
    assert LegacyA is RulesBasedRelevanceGate


async def test_legacy_chat_presence_path_still_works():
    """Block B shim: wormbase_chat_presence.relevance.RulesBasedRelevanceGate is the same class."""
    from wormbase_chat_presence.relevance import RulesBasedRelevanceGate as LegacyB
    assert LegacyB is RulesBasedRelevanceGate
