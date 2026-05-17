"""Conformance: every concrete gate satisfies the PolicyGate Protocol.

Wave D Block E. PolicyGate is structural (runtime_checkable), so this
test enumerates the six gates explicitly and asserts isinstance. If a
future gate is added, this test must be extended — that is the point.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from wormbase_governance import (
    InterjectionGate,
    KnowledgeGate,
    MaskedColumnRefusalGate,
    PIIGate,
    WarmupGate,
)
from wormbase_governance.relevance import RulesBasedRelevanceGate
from wormbase_governance.types import (
    InterjectionGateProtocol,
    PIIGateProtocol,
    PolicyGate,
)
from wormbase_ledger import InMemoryLedger
from wormbase_ontology_seed import Loader


@pytest.fixture
def company_id():
    return uuid4()


@pytest.fixture
def ledger():
    return InMemoryLedger()


@pytest.fixture
def loader():
    return Loader()


def test_pii_gate_satisfies_policy_gate(ledger, company_id, loader):
    gate = PIIGate(ledger, company_id, loader)
    assert isinstance(gate, PolicyGate)
    assert isinstance(gate, PIIGateProtocol)


def test_warmup_gate_satisfies_policy_gate(ledger, company_id):
    async def _ramp_reader(_cid):
        class _R:
            schema_axis = 0.0
        return _R()
    gate = WarmupGate(_ramp_reader, ledger, company_id)
    assert isinstance(gate, PolicyGate)


def test_interjection_gate_satisfies_policy_gate(ledger, company_id):
    gate = InterjectionGate(ledger, company_id)
    # InterjectionGate has `allow`, not `check` — does NOT satisfy PolicyGate.
    # It satisfies the narrower InterjectionGateProtocol instead.
    assert isinstance(gate, InterjectionGateProtocol)
    assert not isinstance(gate, PolicyGate)


def test_knowledge_gate_satisfies_policy_gate(ledger, company_id):
    gate = KnowledgeGate(["a"], [], ledger, company_id)
    assert isinstance(gate, PolicyGate)


def test_masked_column_refusal_gate_satisfies_policy_gate(ledger, company_id):
    gate = MaskedColumnRefusalGate(ledger, company_id)
    assert isinstance(gate, PolicyGate)


def test_relevance_gate_satisfies_policy_gate(ledger, company_id):
    # RulesBasedRelevanceGate's primary entry point is `handle()`, but it also
    # exposes `talkativeness_for()` and `is_mentioned()`. It does NOT satisfy
    # PolicyGate (no `check` method). This is intentional: the relevance
    # decision is observation-grade, not gate-fired (see spike §0 caveat 2).
    gate = RulesBasedRelevanceGate(ledger, company_id)
    assert not isinstance(gate, PolicyGate)
