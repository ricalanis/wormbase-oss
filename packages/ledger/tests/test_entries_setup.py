"""Setup payload validation tests (Block G of the production-dashboard PRD §17).

Three new payload kinds — setup_mode_chosen / setup_completed / setup_step_advanced
— must each:

* construct from valid args,
* reject extras (Pydantic ``extra='forbid'`` on EntryPayload),
* round-trip via ``model_dump`` → ``model_validate`` byte-equivalently,
* enforce kind registration in ``KIND_REGISTRY``,
* enforce tz-aware timestamps where applicable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E

TENANT_ID = UUID("0190a0a0-0000-7000-8000-0000000000c1")
PERSON_ID = UUID("0190a0a0-0000-7000-8000-0000000000c2")


SETUP_CASES: list[tuple[type[E.EntryPayload], dict[str, Any]]] = [
    (
        E.SetupModeChosenPayload,
        {
            "tenant_id": TENANT_ID,
            "mode": "wizard",
            "chosen_by_person_id": PERSON_ID,
        },
    ),
    (
        E.SetupModeChosenPayload,
        {
            "tenant_id": TENANT_ID,
            "mode": "bot",
            "chosen_by_person_id": PERSON_ID,
        },
    ),
    (
        E.SetupCompletedPayload,
        {
            "tenant_id": TENANT_ID,
            "completed_at": datetime(2026, 4, 26, 14, 0, 0, tzinfo=UTC),
        },
    ),
    (
        E.SetupStepAdvancedPayload,
        {
            "tenant_id": TENANT_ID,
            "step_id": "domain_pack",
            "advanced_by_person_id": PERSON_ID,
        },
    ),
    (
        E.SetupStepAdvancedPayload,
        {
            "tenant_id": TENANT_ID,
            "step_id": "first_kpi",
            "advanced_by_person_id": None,
        },
    ),
]


@pytest.mark.parametrize("model,data", SETUP_CASES)
def test_setup_constructs(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    assert obj.kind in E.KIND_REGISTRY
    assert E.KIND_REGISTRY[obj.kind] is model


@pytest.mark.parametrize("model,data", SETUP_CASES)
def test_setup_rejects_extras(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model(**{**data, "not_allowed": True})


@pytest.mark.parametrize("model,data", SETUP_CASES)
def test_setup_roundtrips(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    again = model.model_validate(obj.model_dump())
    assert again == obj


def test_setup_kind_strings() -> None:
    """Kind has no `emit_` prefix — that's applied by the write primitive."""
    assert E.SetupModeChosenPayload.kind == "setup_mode_chosen"
    assert E.SetupCompletedPayload.kind == "setup_completed"
    assert E.SetupStepAdvancedPayload.kind == "setup_step_advanced"


def test_setup_mode_must_be_wizard_or_bot() -> None:
    with pytest.raises(ValidationError):
        E.SetupModeChosenPayload(
            tenant_id=TENANT_ID,
            mode="other",  # type: ignore[arg-type]
            chosen_by_person_id=PERSON_ID,
        )


def test_setup_completed_requires_tz_aware() -> None:
    with pytest.raises(ValidationError):
        E.SetupCompletedPayload(
            tenant_id=TENANT_ID,
            completed_at=datetime(2026, 4, 26, 14, 0, 0),  # naive
        )


def test_setup_step_advanced_optional_advanced_by() -> None:
    """advanced_by_person_id is None when the worm advances itself (timeout)."""
    p = E.SetupStepAdvancedPayload(
        tenant_id=TENANT_ID,
        step_id="done",
    )
    assert p.advanced_by_person_id is None
