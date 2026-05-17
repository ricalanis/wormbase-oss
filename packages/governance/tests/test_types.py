"""Tests for the new wormbase_governance.types surface."""
from __future__ import annotations

import pytest
from wormbase_governance.types import (
    GateDecision,
    InterjectionGateProtocol,
    PIIGateProtocol,
    PIIGateResult,
    PolicyGate,
)


def test_gate_decision_is_frozen_pydantic():
    d = GateDecision(allow=True, reason="ok")
    with pytest.raises(Exception):
        d.allow = False  # frozen


def test_pii_gate_result_round_trip():
    r = PIIGateResult(
        redacted_text="hi [REDACTED:email]",
        matches=[{"pattern_id": "email", "span": [3, 21], "original_hash": "abc"}],
        classification_escalation="pii",
        changed=True,
    )
    assert r.changed is True
    assert r.classification_escalation == "pii"


def test_policy_gate_protocol_is_runtime_checkable():
    class _MinimalGate:
        async def check(self, *args, **kwargs):
            return None
    assert isinstance(_MinimalGate(), PolicyGate)


def test_pii_gate_protocol_is_runtime_checkable():
    class _Stub:
        async def check(self, text: str, context: dict) -> object:
            return None
    assert isinstance(_Stub(), PIIGateProtocol)


def test_interjection_gate_protocol_is_runtime_checkable():
    class _Stub:
        async def allow(self, channel_id: str, question_type: str) -> bool:
            return True
    assert isinstance(_Stub(), InterjectionGateProtocol)


def test_governance_top_level_reexports():
    """Public surface ships the new types from `wormbase_governance` root."""
    from wormbase_governance import (
        GateDecision as _GD,
        PIIGateResult as _PR,
        PolicyGate as _PG,
    )
    assert _GD is GateDecision
    assert _PR is PIIGateResult
    assert _PG is PolicyGate
