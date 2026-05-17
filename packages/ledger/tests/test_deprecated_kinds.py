"""Regression tests for entry kinds annotated DEPRECATED.

Per Rule 3 of the schema-evolution doctrine, deprecated entry kinds are NOT
deleted from ``wormbase_ledger.entries`` — historical ledgers in deployed
tenants may contain these entries, and deletion would break replay. Each
deprecated payload class carries a ``DEPRECATED: True`` ClassVar and a
docstring noting it is no longer emitted.

This module asserts every such kind still deserializes cleanly from a
canonical fixture payload.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from wormbase_ledger import entries as E

UID = UUID("0190a0a0-0000-7000-8000-000000000010")
TS = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)


# Each entry: (payload class, canonical payload dict). Add a row when a kind
# transitions to DEPRECATED.
DEPRECATED_CASES: list[tuple[type[E.EntryPayload], dict[str, Any]]] = [
    (
        E.HeuristicExperimentPayload,
        {
            "experiment_id": UID,
            "metric": "classifier_precision_on_seed_bank",
            "before": "0.80",
            "after": "0.82",
            "kept": True,
        },
    ),
]


@pytest.mark.parametrize("cls,data", DEPRECATED_CASES)
def test_deprecated_kind_marker_present(
    cls: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    """Each case in DEPRECATED_CASES must actually carry the marker."""
    assert getattr(cls, "DEPRECATED", False) is True, (
        f"{cls.__name__} is listed in DEPRECATED_CASES but does not set "
        "DEPRECATED: ClassVar[bool] = True. Either add the marker or "
        "remove the row."
    )


@pytest.mark.parametrize("cls,data", DEPRECATED_CASES)
def test_deprecated_kind_remains_parseable_for_replay(
    cls: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    """Historical entries with deprecated kinds must still deserialize.

    Wave C₁ deleted the ``heuristic_loop`` emitter (zero production callers
    pre-deletion), but historical ledger entries with these kinds remain
    valid for replay. Verify each deprecated kind still loads from a
    canonical fixture payload and roundtrips through model_dump →
    model_validate without loss.
    """
    instance = cls(**data)
    dumped = instance.model_dump()
    revived = cls.model_validate(dumped)
    assert revived.model_dump() == dumped
    # Kind discriminator survives the roundtrip.
    assert cls.kind == instance.kind == revived.kind
