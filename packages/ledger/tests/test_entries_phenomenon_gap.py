"""W5.A3 — round-trip + validation tests for ``phenomenon_gap_detected``.

Single polymorphic ledger entry kind across all four phenomenon-gap
detectors (kpi / domain / process / reactivity). Per W5.A3 spec, the
discriminator field is ``kind`` (aliased onto ``gap_kind`` to dodge the
``EntryPayload.kind`` ClassVar — same pattern as
``DataProductProposedPayload``).

Each kind variant must:

* construct from valid args,
* reject extras (Pydantic ``extra='forbid'``),
* round-trip via ``model_dump(by_alias=True)`` → ``model_validate``,
* enforce ``confidence`` ∈ [0, 1],
* enforce ``referenced_in_seq`` ≥ 0,
* enforce ``kind`` ∈ {kpi, domain, process, reactivity}.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E


GAP_CASES: list[dict[str, Any]] = [
    {
        "kind": "kpi",
        "referenced_in_seq": 42,
        "suggested_proposal": {
            "label": "nps",
            "domain_id": None,
            "formula": "PROPOSED",
            "unit": "count",
        },
        "confidence": 0.9,
        "novelty_key": "kpi:nps",
    },
    {
        "kind": "domain",
        "referenced_in_seq": 99,
        "suggested_proposal": {
            "label": "compliance",
            "default_classification": "internal",
        },
        "confidence": 0.85,
        "novelty_key": "domain:compliance",
    },
    {
        "kind": "process",
        "referenced_in_seq": 101,
        "suggested_proposal": {
            "process_name": "data-quality review",
            "domain": "data",
            "evidence_text": "every Friday we run the data-quality review",
        },
        "confidence": 0.85,
        "novelty_key": "process:data-quality review",
    },
    {
        "kind": "reactivity",
        "referenced_in_seq": 250,
        "suggested_proposal": {
            "reactivity_id": "every-friday-we-run-the-data-quality-review",
            "name": "every Friday we run the data-quality review",
            "description": "every Friday we run the data-quality review",
            "scope": "company",
            "predicate_spec": {"natural_language": "every friday"},
            "action_spec": {
                "natural_language": "run the data-quality review",
            },
            "natural_language": "every Friday we run the data-quality review",
            "requires_admin_edit": True,
        },
        "confidence": 0.85,
        "novelty_key": (
            "reactivity:every-friday-we-run-the-data-quality-review"
        ),
    },
]


@pytest.mark.parametrize("data", GAP_CASES)
def test_phenomenon_gap_constructs(data: dict[str, Any]) -> None:
    obj = E.PhenomenonGapDetectedPayload(**data)
    assert obj.kind == "phenomenon_gap_detected"  # ClassVar
    assert obj.gap_kind == data["kind"]
    assert E.KIND_REGISTRY["phenomenon_gap_detected"] is (
        E.PhenomenonGapDetectedPayload
    )


@pytest.mark.parametrize("data", GAP_CASES)
def test_phenomenon_gap_rejects_extras(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        E.PhenomenonGapDetectedPayload(**{**data, "not_allowed": True})


@pytest.mark.parametrize("data", GAP_CASES)
def test_phenomenon_gap_roundtrips(data: dict[str, Any]) -> None:
    obj = E.PhenomenonGapDetectedPayload(**data)
    # by_alias=True is the spec-shape: discriminator field on the wire is
    # ``kind``, matching the W5.A3 brief and other ledger writers.
    serialized = obj.model_dump(by_alias=True)
    again = E.PhenomenonGapDetectedPayload.model_validate(serialized)
    assert again == obj


def test_phenomenon_gap_rejects_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        E.PhenomenonGapDetectedPayload(
            kind="bogus",
            referenced_in_seq=1,
            suggested_proposal={},
            confidence=0.5,
            novelty_key="x:y",
        )


def test_phenomenon_gap_accepts_all_valid_kinds() -> None:
    for k in ("kpi", "domain", "process", "reactivity"):
        obj = E.PhenomenonGapDetectedPayload(
            kind=k,
            referenced_in_seq=1,
            suggested_proposal={},
            confidence=0.5,
            novelty_key=f"{k}:x",
        )
        assert obj.gap_kind == k


def test_phenomenon_gap_rejects_confidence_above_one() -> None:
    with pytest.raises(ValidationError):
        E.PhenomenonGapDetectedPayload(
            kind="kpi",
            referenced_in_seq=1,
            suggested_proposal={},
            confidence=1.5,
            novelty_key="kpi:x",
        )


def test_phenomenon_gap_rejects_negative_confidence() -> None:
    with pytest.raises(ValidationError):
        E.PhenomenonGapDetectedPayload(
            kind="kpi",
            referenced_in_seq=1,
            suggested_proposal={},
            confidence=-0.1,
            novelty_key="kpi:x",
        )


def test_phenomenon_gap_rejects_negative_seq() -> None:
    with pytest.raises(ValidationError):
        E.PhenomenonGapDetectedPayload(
            kind="kpi",
            referenced_in_seq=-1,
            suggested_proposal={},
            confidence=0.5,
            novelty_key="kpi:x",
        )


def test_phenomenon_gap_kind_string() -> None:
    """The ClassVar discriminator stays "phenomenon_gap_detected"."""
    assert E.PhenomenonGapDetectedPayload.kind == "phenomenon_gap_detected"
    assert "phenomenon_gap_detected" in E.ALL_KINDS
