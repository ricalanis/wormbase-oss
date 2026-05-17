"""W5.A1 — round-trip + validation tests for the reactivity entry kinds.

Four kinds added by the Reactivity Protocol wave:
    * reactivity_proposed
    * reactivity_confirmed
    * reactivity_disabled
    * reactivity_fired

Each must construct, reject extras (Pydantic ``extra='forbid'``), and
roundtrip via ``model_dump`` → ``model_validate``.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E

REACTIVITY_CASES: list[tuple[type[E.EntryPayload], dict[str, Any]]] = [
    (
        E.ReactivityProposedPayload,
        {
            "reactivity_id": "statement_to_owner",
            "name": "Statement to Owner",
            "description": "DM resource owner with related KPIs/sources.",
            "scope": "domain",
            "predicate_spec": {"kind": "chat_received"},
            "condition_spec": {"per_owner_per_day": 3},
            "action_spec": {"channel": "dm"},
            "proposed_by": "worm",
        },
    ),
    (
        E.ReactivityConfirmedPayload,
        {
            "reactivity_id": "statement_to_owner",
            "confirmed_by": "00000000-0000-0000-0000-0000000000aa",
        },
    ),
    (
        E.ReactivityDisabledPayload,
        {
            "reactivity_id": "statement_to_owner",
            "disabled_by": "00000000-0000-0000-0000-0000000000aa",
            "reason": "noisy in #revenue",
        },
    ),
    (
        E.ReactivityFiredPayload,
        {
            "reactivity_id": "identity_discovery",
            "source_seq": 42,
            "novelty_key": "slack:U-bob",
            "action_seqs": [43, 44, 45, 46],
            "budget_used": {"per_tenant": 1},
        },
    ),
]


@pytest.mark.parametrize("model,data", REACTIVITY_CASES)
def test_reactivity_payload_constructs(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    assert obj.kind in E.KIND_REGISTRY
    assert E.KIND_REGISTRY[obj.kind] is model


@pytest.mark.parametrize("model,data", REACTIVITY_CASES)
def test_reactivity_payload_rejects_extras(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model(**{**data, "not_allowed": True})


@pytest.mark.parametrize("model,data", REACTIVITY_CASES)
def test_reactivity_payload_roundtrips(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    again = model.model_validate(obj.model_dump())
    assert again == obj


def test_reactivity_proposed_rejects_invalid_scope() -> None:
    with pytest.raises(ValidationError):
        E.ReactivityProposedPayload(
            reactivity_id="x",
            name="X",
            description="X",
            scope="totally_invalid",
            proposed_by="worm",
        )


def test_reactivity_proposed_accepts_all_valid_scopes() -> None:
    for scope in ("company", "team", "domain", "person"):
        obj = E.ReactivityProposedPayload(
            reactivity_id="x",
            name="X",
            description="X",
            scope=scope,
            proposed_by="worm",
        )
        assert obj.scope == scope


def test_reactivity_fired_rejects_negative_source_seq() -> None:
    with pytest.raises(ValidationError):
        E.ReactivityFiredPayload(
            reactivity_id="x",
            source_seq=-1,
        )


def test_reactivity_fired_default_action_seqs_is_empty() -> None:
    obj = E.ReactivityFiredPayload(reactivity_id="x", source_seq=0)
    assert obj.action_seqs == []
    assert obj.budget_used == {}
    assert obj.novelty_key == ""
