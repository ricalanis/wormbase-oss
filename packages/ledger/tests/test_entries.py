"""Step 3c — process retrieval payload roundtrip tests.

The four payload kinds added by the process_extractor service must each:

* construct from valid args,
* reject extras (Pydantic ``extra='forbid'`` is set on EntryPayload),
* roundtrip via ``model_dump`` → ``model_validate`` byte-equivalently.

These run alongside the existing ``test_entries_payloads.py`` matrix.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E

UID = UUID("0190a0a0-0000-7000-8000-0000000000a1")
PID = UUID("0190a0a0-0000-7000-8000-0000000000a2")
QID = UUID("0190a0a0-0000-7000-8000-0000000000a3")
TS = datetime(2026, 4, 24, 10, 0, tzinfo=UTC)


PROCESS_RETRIEVAL_CASES: list[tuple[type[E.EntryPayload], dict[str, Any]]] = [
    (
        E.DecisionRecordedPayload,
        {
            "decision_id": UID,
            "decision_text": "we'll push Q3 close to Friday",
            "decision_at": TS,
            "channel_id": "C-finance",
            "decided_by_persons": [PID],
            "evidence_message_ids": ["1714000.0001", "1714000.0002"],
            "confidence": 0.82,
        },
    ),
    (
        E.ProcessMapProposedPayload,
        {
            "process_id": UID,
            "process_name": "Q3 close",
            "steps": [
                {
                    "order": 1,
                    "actor": "Bob",
                    "action": "exports the trial balance",
                    "source_message_id": "m1",
                },
                {
                    "order": 2,
                    "actor": "Alice",
                    "action": "reviews",
                    "source_message_id": "m2",
                },
            ],
            "domain": "finance",
            "confidence": 0.74,
        },
    ),
    (
        E.SystemMapNodePayload,
        {
            "node_kind": "person",
            "node_id": str(PID),
            "edges": [
                {"kind": "asks", "target_id": "C-finance", "weight": 4.0},
                {"kind": "responds_to", "target_id": str(QID), "weight": 2.0},
            ],
        },
    ),
    (
        E.RecurringQuestionPayload,
        {
            "question_id": QID,
            "normalized_question": "what q3 net revenue",
            "asked_by_persons": [PID],
            "occurrences": 4,
            "first_seen_at": TS,
            "last_seen_at": TS,
            "suggested_automation": "daily Q3 net revenue digest",
        },
    ),
]


@pytest.mark.parametrize("model,data", PROCESS_RETRIEVAL_CASES)
def test_process_retrieval_constructs(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    assert obj.kind in E.KIND_REGISTRY
    assert E.KIND_REGISTRY[obj.kind] is model


@pytest.mark.parametrize("model,data", PROCESS_RETRIEVAL_CASES)
def test_process_retrieval_rejects_extras(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model(**{**data, "not_allowed": True})


@pytest.mark.parametrize("model,data", PROCESS_RETRIEVAL_CASES)
def test_process_retrieval_roundtrips(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    again = model.model_validate(obj.model_dump())
    assert again == obj


def test_decision_recorded_rejects_naive_decision_at() -> None:
    with pytest.raises(ValidationError):
        E.DecisionRecordedPayload(
            decision_id=UID,
            decision_text="Q3 close on Friday",
            decision_at=datetime(2026, 4, 24, 10, 0),  # naive
            channel_id="C",
            decided_by_persons=[PID],
            evidence_message_ids=["m1"],
            confidence=0.5,
        )


def test_decision_recorded_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        E.DecisionRecordedPayload(
            decision_id=UID,
            decision_text="x",
            decision_at=TS,
            channel_id="C",
            decided_by_persons=[],
            evidence_message_ids=[],
            confidence=1.5,
        )
    with pytest.raises(ValidationError):
        E.DecisionRecordedPayload(
            decision_id=UID,
            decision_text="x",
            decision_at=TS,
            channel_id="C",
            decided_by_persons=[],
            evidence_message_ids=[],
            confidence=-0.1,
        )


def test_process_map_steps_are_arbitrary_dicts() -> None:
    p = E.ProcessMapProposedPayload(
        process_id=UID,
        process_name="deploy",
        steps=[{"order": 1, "actor": "ci", "action": "build"}],
        domain="eng",
        confidence=0.5,
    )
    assert p.steps[0]["actor"] == "ci"


def test_recurring_question_occurrences_min_1() -> None:
    with pytest.raises(ValidationError):
        E.RecurringQuestionPayload(
            question_id=QID,
            normalized_question="x",
            asked_by_persons=[],
            occurrences=0,
            first_seen_at=TS,
            last_seen_at=TS,
        )


def test_system_map_node_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        E.SystemMapNodePayload(
            node_kind="bot",  # type: ignore[arg-type]
            node_id="x",
            edges=[],
        )


def test_recurring_question_suggested_automation_optional() -> None:
    p = E.RecurringQuestionPayload(
        question_id=QID,
        normalized_question="how runway",
        asked_by_persons=[PID],
        occurrences=2,
        first_seen_at=TS,
        last_seen_at=TS,
    )
    assert p.suggested_automation is None
