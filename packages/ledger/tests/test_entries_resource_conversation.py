"""W5.A2 — round-trip + validation tests for resource_conversation entry kinds.

Three kinds added by the Statement-to-Owner reactivity wave:
    * resource_conversation_proposed
    * resource_conversation_replied
    * resource_conversation_resolved

Each must construct, reject extras (Pydantic ``extra='forbid'``), and
roundtrip via ``model_dump`` → ``model_validate``. The ``resolved`` payload
also validates the outcome enum and the optional decision_seq.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E


CONVERSATION_ID = UUID("11111111-1111-1111-1111-111111111111")
OWNER_ID = UUID("22222222-2222-2222-2222-222222222222")
REPLIER_ID = UUID("33333333-3333-3333-3333-333333333333")
RESOLVER_ID = UUID("44444444-4444-4444-4444-444444444444")


RESOURCE_CONVERSATION_CASES: list[
    tuple[type[E.EntryPayload], dict[str, Any]]
] = [
    (
        E.ResourceConversationProposedPayload,
        {
            "conversation_id": CONVERSATION_ID,
            "topic": {
                "kind": "kpi",
                "id": "00000000-0000-0000-0000-0000000000aa",
                "label": "churn",
                "confidence": 0.82,
                "domain_id": "00000000-0000-0000-0000-0000000000ab",
            },
            "owner_id": OWNER_ID,
            "resources": {
                "kpis": [{"label": "churn", "value": 0.081}],
                "sources": [{"name": "stripe"}],
                "decisions": [],
                "processes": [],
                "data_products": [],
            },
            "statement_seq": 100,
            "channel": "slack:D012345",
        },
    ),
    (
        E.ResourceConversationRepliedPayload,
        {
            "conversation_id": CONVERSATION_ID,
            "replier_id": REPLIER_ID,
            "content": "Yeah, I saw the dip — let's check the SEPA cohort.",
            "seq": 105,
        },
    ),
    (
        E.ResourceConversationResolvedPayload,
        {
            "conversation_id": CONVERSATION_ID,
            "outcome": "decision",
            "resolved_by": RESOLVER_ID,
            "decision_seq": 110,
        },
    ),
]


@pytest.mark.parametrize("model,data", RESOURCE_CONVERSATION_CASES)
def test_resource_conversation_payload_constructs(
    model: type[E.EntryPayload], data: dict[str, Any],
) -> None:
    obj = model(**data)
    assert obj.kind in E.KIND_REGISTRY
    assert E.KIND_REGISTRY[obj.kind] is model


@pytest.mark.parametrize("model,data", RESOURCE_CONVERSATION_CASES)
def test_resource_conversation_payload_rejects_extras(
    model: type[E.EntryPayload], data: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        model(**{**data, "not_allowed": True})


@pytest.mark.parametrize("model,data", RESOURCE_CONVERSATION_CASES)
def test_resource_conversation_payload_roundtrips(
    model: type[E.EntryPayload], data: dict[str, Any],
) -> None:
    obj = model(**data)
    again = model.model_validate(obj.model_dump())
    assert again == obj


def test_resource_conversation_resolved_rejects_invalid_outcome() -> None:
    with pytest.raises(ValidationError):
        E.ResourceConversationResolvedPayload(
            conversation_id=CONVERSATION_ID,
            outcome="totally_invalid",
            resolved_by=RESOLVER_ID,
        )


def test_resource_conversation_resolved_accepts_all_valid_outcomes() -> None:
    for outcome in ("decision", "process_update", "no_action", "muted"):
        obj = E.ResourceConversationResolvedPayload(
            conversation_id=CONVERSATION_ID,
            outcome=outcome,
            resolved_by=RESOLVER_ID,
        )
        assert obj.outcome == outcome


def test_resource_conversation_resolved_decision_seq_optional() -> None:
    obj = E.ResourceConversationResolvedPayload(
        conversation_id=CONVERSATION_ID,
        outcome="no_action",
        resolved_by=RESOLVER_ID,
    )
    assert obj.decision_seq is None


def test_resource_conversation_resolved_decision_seq_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        E.ResourceConversationResolvedPayload(
            conversation_id=CONVERSATION_ID,
            outcome="decision",
            resolved_by=RESOLVER_ID,
            decision_seq=-1,
        )


def test_resource_conversation_proposed_statement_seq_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        E.ResourceConversationProposedPayload(
            conversation_id=CONVERSATION_ID,
            topic={"kind": "kpi", "id": "x", "label": "y", "confidence": 0.5},
            owner_id=OWNER_ID,
            statement_seq=-1,
            channel="slack:D012345",
        )


def test_resource_conversation_proposed_default_resources_empty() -> None:
    obj = E.ResourceConversationProposedPayload(
        conversation_id=CONVERSATION_ID,
        topic={"kind": "kpi", "id": "x", "label": "y", "confidence": 0.5},
        owner_id=OWNER_ID,
        statement_seq=0,
        channel="slack:D012345",
    )
    assert obj.resources == {}
