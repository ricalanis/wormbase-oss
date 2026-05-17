"""Tests asserting that legacy import paths resolve to governance-canonical types."""
from __future__ import annotations


def test_worm_core_gate_decision_is_governance():
    from wormbase_core.types import GateDecision as A
    from wormbase_governance.types import GateDecision as B
    assert A is B


def test_worm_core_pii_gate_result_is_governance():
    from wormbase_core.types import PIIGateResult as A
    from wormbase_governance.types import PIIGateResult as B
    assert A is B


def test_chat_presence_pii_proto_alias():
    from wormbase_chat_presence.chat_flows._shared import _PIIGateProto as A
    from wormbase_governance.types import PIIGateProtocol as B
    assert A is B


def test_chat_presence_interjection_proto_alias():
    from wormbase_chat_presence.chat_flows._shared import _InterjectionGateProto as A
    from wormbase_governance.types import InterjectionGateProtocol as B
    assert A is B
