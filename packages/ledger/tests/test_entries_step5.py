"""Step 5 — user structure + per-user autoresearch payload tests.

Mirrors the Step 3c test matrix in ``test_entries.py`` for the eight new
payloads added to ``packages/ledger/src/wormbase_ledger/entries.py``:

  * person_registered
  * position_assigned
  * position_metric_added
  * position_question_pattern
  * experiment_proposed
  * experiment_run
  * experiment_resolved
  * metric_observed

Each payload must:
  * construct from valid args,
  * reject extras (Pydantic ``extra='forbid'`` on EntryPayload),
  * roundtrip via ``model_dump`` → ``model_validate`` byte-equivalently.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E

UID = UUID("0190a0a0-0000-7000-8000-0000000000c1")
PID = UUID("0190a0a0-0000-7000-8000-0000000000c2")
INSTALLER = UUID("0190a0a0-0000-7000-8000-0000000000c3")
EXP_ID = UUID("0190a0a0-0000-7000-8000-0000000000c4")
TS = datetime(2026, 4, 24, 10, 0, tzinfo=UTC)
TS_LATER = datetime(2026, 4, 24, 10, 1, tzinfo=UTC)


STEP5_CASES: list[tuple[type[E.EntryPayload], dict[str, Any]]] = [
    (
        E.PersonRegisteredPayload,
        {
            "person_id": PID,
            "name": "Carol",
            "email": "carol@example.com",
            "role": "admin",
            "registered_at": TS,
        },
    ),
    (
        E.PositionAssignedPayload,
        {
            "person_id": PID,
            "position": "cfo",
            "assigned_by_person_id": INSTALLER,
            "at": TS,
        },
    ),
    (
        E.PositionMetricAddedPayload,
        {
            "position": "cfo",
            "metric_id": "revenue",
            "weight": 0.9,
            "by_person_id": PID,
        },
    ),
    (
        E.PositionQuestionPatternPayload,
        {
            "position": "cfo",
            "pattern": "what's our",
            "frequency_observed": 4,
            "last_seen_at": TS,
        },
    ),
    (
        E.ExperimentProposedPayload,
        {
            "experiment_id": EXP_ID,
            "for_person_id": PID,
            "position": "cfo",
            "headline_metric": "revenue",
            "proposed_change": {"kind": "kpi_definition", "target": "revenue_forecast"},
            "expected_delta": 0.04,
            "proposed_at": TS,
        },
    ),
    (
        E.ExperimentRunPayload,
        {
            "experiment_id": EXP_ID,
            "started_at": TS,
            "finished_at": TS_LATER,
            "log": {"iterations": 1, "synthetic_runtime_s": 60},
        },
    ),
    (
        E.ExperimentResolvedPayload,
        {
            "experiment_id": EXP_ID,
            "outcome": "keep",
            "observed_delta": 0.036,
            "rationale": "win: hit 90% of expected",
            "resolved_at": TS_LATER,
        },
    ),
    (
        E.MetricObservedPayload,
        {
            "metric_id": "revenue",
            "position": "cfo",
            "value": 1_420_000.0,
            "observed_at": TS,
        },
    ),
]


@pytest.mark.parametrize("model,data", STEP5_CASES)
def test_step5_constructs(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    assert obj.kind in E.KIND_REGISTRY
    assert E.KIND_REGISTRY[obj.kind] is model


@pytest.mark.parametrize("model,data", STEP5_CASES)
def test_step5_rejects_extras(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        model(**{**data, "not_allowed": True})


@pytest.mark.parametrize("model,data", STEP5_CASES)
def test_step5_roundtrips(
    model: type[E.EntryPayload], data: dict[str, Any]
) -> None:
    obj = model(**data)
    again = model.model_validate(obj.model_dump())
    assert again == obj


def test_person_registered_rejects_naive_ts() -> None:
    with pytest.raises(ValidationError):
        E.PersonRegisteredPayload(
            person_id=PID,
            name="Carol",
            registered_at=datetime(2026, 4, 24, 10, 0),  # naive
        )


def test_position_metric_weight_bounds() -> None:
    with pytest.raises(ValidationError):
        E.PositionMetricAddedPayload(
            position="cfo", metric_id="revenue", weight=1.5,
        )
    with pytest.raises(ValidationError):
        E.PositionMetricAddedPayload(
            position="cfo", metric_id="revenue", weight=-0.1,
        )


def test_position_question_pattern_min_freq() -> None:
    with pytest.raises(ValidationError):
        E.PositionQuestionPatternPayload(
            position="cfo",
            pattern="what's our",
            frequency_observed=0,
            last_seen_at=TS,
        )


def test_experiment_resolved_rejects_unknown_outcome() -> None:
    with pytest.raises(ValidationError):
        E.ExperimentResolvedPayload(
            experiment_id=EXP_ID,
            outcome="maybe",  # type: ignore[arg-type]
            observed_delta=0.0,
            rationale="x",
            resolved_at=TS,
        )


def test_experiment_run_rejects_naive_finished_at() -> None:
    with pytest.raises(ValidationError):
        E.ExperimentRunPayload(
            experiment_id=EXP_ID,
            started_at=TS,
            finished_at=datetime(2026, 4, 24, 10, 1),  # naive
            log={},
        )


def test_metric_observed_optional_source_id() -> None:
    p = E.MetricObservedPayload(
        metric_id="revenue",
        position="cfo",
        value=1_000_000.0,
        observed_at=TS,
    )
    assert p.source_id is None


def test_step5_kinds_registered() -> None:
    expected = {
        "person_registered",
        "position_assigned",
        "position_metric_added",
        "position_question_pattern",
        "experiment_proposed",
        "experiment_run",
        "experiment_resolved",
        "metric_observed",
    }
    assert expected.issubset(E.ALL_KINDS)


# ----------------------------------------------------------------------
# W5.A4 — additive ``audience`` payload field on ExperimentProposedPayload.
#
# The audience marker covers three autoresearch scopes:
#   * "person:<uuid>" — per-Person × per-position (existing scope)
#   * "team:<domain_uuid>" — per-Team-Domain (W5.A4 new)
#   * "company" — top-level KPI tree (W5.A4 new)
#
# Pre-W5.A4 rows wrote no ``audience`` field; those must still deserialise
# byte-identically (no backfill migration). The loop interprets ``None`` as
# ``f"person:{for_person_id}"`` at read time.
# ----------------------------------------------------------------------


TEAM_ID = UUID("0190a0a0-0000-7000-8000-0000000000d1")


def test_experiment_proposed_audience_defaults_to_none() -> None:
    """Backward compat: rows without ``audience`` deserialise with None."""
    p = E.ExperimentProposedPayload(
        experiment_id=EXP_ID,
        for_person_id=PID,
        position="cfo",
        headline_metric="revenue",
        proposed_change={"kind": "kpi_definition", "target": "revenue_forecast"},
        expected_delta=0.04,
        proposed_at=TS,
    )
    assert p.audience is None


def test_experiment_proposed_audience_person_form() -> None:
    p = E.ExperimentProposedPayload(
        experiment_id=EXP_ID,
        for_person_id=PID,
        position="cfo",
        headline_metric="revenue",
        proposed_change={"kind": "kpi_definition", "target": "revenue_forecast"},
        expected_delta=0.04,
        proposed_at=TS,
        audience=f"person:{PID}",
    )
    assert p.audience == f"person:{PID}"


def test_experiment_proposed_audience_team_form() -> None:
    p = E.ExperimentProposedPayload(
        experiment_id=EXP_ID,
        for_person_id=PID,
        position="cfo",
        headline_metric="revenue",
        proposed_change={"kind": "kpi_definition", "target": "revenue_forecast"},
        expected_delta=0.04,
        proposed_at=TS,
        audience=f"team:{TEAM_ID}",
    )
    assert p.audience == f"team:{TEAM_ID}"


def test_experiment_proposed_audience_company_form() -> None:
    p = E.ExperimentProposedPayload(
        experiment_id=EXP_ID,
        for_person_id=PID,
        position="cfo",
        headline_metric="revenue",
        proposed_change={"kind": "kpi_definition", "target": "revenue_forecast"},
        expected_delta=0.04,
        proposed_at=TS,
        audience="company",
    )
    assert p.audience == "company"


def test_experiment_proposed_audience_rejects_bad_uuid() -> None:
    with pytest.raises(ValidationError):
        E.ExperimentProposedPayload(
            experiment_id=EXP_ID,
            for_person_id=PID,
            position="cfo",
            headline_metric="revenue",
            proposed_change={"kind": "kpi_definition", "target": "x"},
            expected_delta=0.04,
            proposed_at=TS,
            audience="person:not-a-uuid",
        )


def test_experiment_proposed_audience_rejects_unknown_prefix() -> None:
    with pytest.raises(ValidationError):
        E.ExperimentProposedPayload(
            experiment_id=EXP_ID,
            for_person_id=PID,
            position="cfo",
            headline_metric="revenue",
            proposed_change={"kind": "kpi_definition", "target": "x"},
            expected_delta=0.04,
            proposed_at=TS,
            audience=f"squad:{TEAM_ID}",
        )


def test_experiment_proposed_audience_roundtrip_team() -> None:
    """Roundtrip preserves the audience string byte-equivalently."""
    p = E.ExperimentProposedPayload(
        experiment_id=EXP_ID,
        for_person_id=PID,
        position="cfo",
        headline_metric="retention_m3",
        proposed_change={"kind": "process_change", "target": "renewal_workflow"},
        expected_delta=0.03,
        proposed_at=TS,
        audience=f"team:{TEAM_ID}",
    )
    again = E.ExperimentProposedPayload.model_validate(p.model_dump())
    assert again == p
    assert again.audience == f"team:{TEAM_ID}"


def test_experiment_proposed_audience_roundtrip_company() -> None:
    p = E.ExperimentProposedPayload(
        experiment_id=EXP_ID,
        for_person_id=PID,
        position="cfo",
        headline_metric="nps",
        proposed_change={"kind": "policy_change", "target": "support_sla"},
        expected_delta=0.02,
        proposed_at=TS,
        audience="company",
    )
    again = E.ExperimentProposedPayload.model_validate(p.model_dump())
    assert again == p
    assert again.audience == "company"


def test_experiment_proposed_audience_legacy_row_replays() -> None:
    """A pre-W5.A4 wire form (no audience key) must validate cleanly."""
    legacy_payload = {
        "experiment_id": str(EXP_ID),
        "for_person_id": str(PID),
        "position": "cfo",
        "headline_metric": "revenue",
        "proposed_change": {"kind": "kpi_definition", "target": "revenue_forecast"},
        "expected_delta": 0.04,
        "proposed_at": TS.isoformat(),
    }
    p = E.ExperimentProposedPayload.model_validate(legacy_payload)
    assert p.audience is None
