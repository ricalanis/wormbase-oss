"""B.2 — Verify loop writes route through the canonical emit-helper layer.

Sister-test to ``test_autoresearch_loop.py`` (which exercises ``run_once``
end-to-end). This file unit-tests the four ``_emit_*`` helper methods on
``AutoresearchLoop`` in isolation, asserting:

  * each helper invokes ``ledger.write`` exactly once with the canonical
    PEVR primitive (propose / execute_fn / verify_fn / resolve_fn / quadrant)
  * the ``execute_fn`` payload carries the correct ``tool=`` string
    (``emit_experiment_proposed`` / ``_run`` / ``_resolved`` /
    ``emit_metric_observed``)
  * the ``args`` block round-trips through the matching
    ``Experiment*Payload`` / ``MetricObservedPayload`` model (validating the
    on-the-wire shape against the ledger contract)

The invariant under test is the one named in the B.2 acceptance criterion:

    research-loop never bypasses the ledger emit layer. All ledger writes
    are routed through the ``tool="emit_..."`` PEVR primitive; no raw
    ``add_entry`` or hand-built envelopes.

If a future helper adds an inline ``add_entry`` call or builds a propose
envelope without a ``tool="emit_..."`` execute payload, these tests fail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_identity_tracker.positions import (
    ImprovementCandidate,
    get_position,
    headline_metric_for_position,
    position_candidates,
)
from wormbase_ledger.entries import (
    ExperimentProposedPayload,
    ExperimentResolvedPayload,
    ExperimentRunPayload,
    MetricObservedPayload,
)
from wormbase_research_loop.loop import (
    AutoresearchLoop,
    PersonPosition,
    _RecentActivity,
)


CAROL = UUID("00000000-0000-0000-0000-0000000000c1")
NOW = datetime(2026, 4, 24, 10, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Mock ledger that captures the canonical PEVR write call shape.
# ---------------------------------------------------------------------------


class _CapturingLedger:
    """Stand-in for ``Ledger`` that records every ``.write(...)`` call.

    Records the keyword args passed to ``ledger.write`` and immediately
    invokes ``execute_fn`` / ``verify_fn`` / ``resolve_fn`` so the captured
    payload reflects the realised PEVR shape (the ledger normally does this
    inside the write primitive). ``fetch`` returns ``[]`` so any helper that
    incidentally fetches (e.g. P9 lesson lookup) gets the empty case.
    """

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    async def write(
        self,
        *,
        company_id: UUID,
        propose: dict[str, Any],
        execute_fn: Any,
        verify_fn: Any,
        resolve_fn: Any,
        quadrant: str,
        timestamp: datetime | None = None,
    ) -> None:
        execute_payload = execute_fn()
        verify_payload = verify_fn(execute_payload)
        resolve_payload = resolve_fn(verify_payload)
        self.writes.append(
            {
                "company_id": company_id,
                "propose": propose,
                "execute": execute_payload,
                "verify": verify_payload,
                "resolve": resolve_payload,
                "quadrant": quadrant,
                "timestamp": timestamp,
            }
        )

    async def fetch(self, _company_id: UUID) -> list[dict[str, Any]]:
        return []


@pytest.fixture
def capturing_ledger() -> _CapturingLedger:
    return _CapturingLedger()


@pytest.fixture
def loop(capturing_ledger: _CapturingLedger, company_id: UUID) -> AutoresearchLoop:
    # Cast through Any: the capturing ledger satisfies the duck-typed surface
    # the loop needs (``write`` + ``fetch``) without implementing the full
    # ``Ledger`` protocol.
    return AutoresearchLoop(ledger=capturing_ledger, company_id=company_id)  # type: ignore[arg-type]


@pytest.fixture
def carol_pp() -> PersonPosition:
    return PersonPosition(person_id=CAROL, position_id="cfo", name="Carol")


@pytest.fixture
def cfo_candidate() -> ImprovementCandidate:
    candidates = position_candidates("cfo")
    assert candidates, "cfo position must have at least one candidate seeded"
    return candidates[0]


# ---------------------------------------------------------------------------
# _emit_proposed
# ---------------------------------------------------------------------------


async def test_emit_proposed_routes_through_ledger_write_with_correct_tool(
    loop: AutoresearchLoop,
    capturing_ledger: _CapturingLedger,
    carol_pp: PersonPosition,
    cfo_candidate: ImprovementCandidate,
) -> None:
    eid = uuid4()
    await loop._emit_proposed(carol_pp, cfo_candidate, eid, now=NOW)

    assert len(capturing_ledger.writes) == 1
    call = capturing_ledger.writes[0]
    assert call["execute"]["tool"] == "emit_experiment_proposed"
    assert call["propose"]["target_kind"] == "experiment_proposed"
    assert call["propose"]["proposed_by"] == "autoresearch_loop"
    assert call["quadrant"] == "active_probabilistic"
    assert call["timestamp"] == NOW


async def test_emit_proposed_args_validate_against_payload_model(
    loop: AutoresearchLoop,
    capturing_ledger: _CapturingLedger,
    carol_pp: PersonPosition,
    cfo_candidate: ImprovementCandidate,
) -> None:
    eid = uuid4()
    await loop._emit_proposed(carol_pp, cfo_candidate, eid, now=NOW)

    args = capturing_ledger.writes[0]["execute"]["args"]
    # Round-trip through the ledger contract: this fails if loop.py drifts
    # from ExperimentProposedPayload's required fields.
    payload = ExperimentProposedPayload.model_validate(args)
    assert payload.experiment_id == eid
    assert payload.for_person_id == CAROL
    assert payload.position == "cfo"
    assert payload.audience == f"person:{CAROL}"
    assert payload.proposed_at == NOW


async def test_emit_proposed_honours_audience_override(
    loop: AutoresearchLoop,
    capturing_ledger: _CapturingLedger,
    carol_pp: PersonPosition,
    cfo_candidate: ImprovementCandidate,
) -> None:
    eid = uuid4()
    await loop._emit_proposed(
        carol_pp, cfo_candidate, eid, now=NOW, audience="company"
    )
    args = capturing_ledger.writes[0]["execute"]["args"]
    assert args["audience"] == "company"


# ---------------------------------------------------------------------------
# _emit_run
# ---------------------------------------------------------------------------


async def test_emit_run_routes_through_ledger_write_with_correct_tool(
    loop: AutoresearchLoop,
    capturing_ledger: _CapturingLedger,
    carol_pp: PersonPosition,
    cfo_candidate: ImprovementCandidate,
) -> None:
    eid = uuid4()
    started = NOW
    finished = NOW + timedelta(seconds=42)

    await loop._emit_run(carol_pp, cfo_candidate, eid, started, finished)

    assert len(capturing_ledger.writes) == 1
    call = capturing_ledger.writes[0]
    assert call["execute"]["tool"] == "emit_experiment_run"
    assert call["propose"]["target_kind"] == "experiment_run"
    assert call["quadrant"] == "active_deterministic"
    assert call["timestamp"] == finished


async def test_emit_run_args_validate_against_payload_model(
    loop: AutoresearchLoop,
    capturing_ledger: _CapturingLedger,
    carol_pp: PersonPosition,
    cfo_candidate: ImprovementCandidate,
) -> None:
    eid = uuid4()
    started = NOW
    finished = NOW + timedelta(seconds=42)

    await loop._emit_run(carol_pp, cfo_candidate, eid, started, finished)
    args = capturing_ledger.writes[0]["execute"]["args"]
    payload = ExperimentRunPayload.model_validate(args)
    assert payload.experiment_id == eid
    assert payload.started_at == started
    assert payload.finished_at == finished
    assert payload.log["candidate_id"] == cfo_candidate.candidate_id
    assert payload.log["person_id"] == str(CAROL)


# ---------------------------------------------------------------------------
# _emit_resolved
# ---------------------------------------------------------------------------


async def test_emit_resolved_routes_through_ledger_write_with_correct_tool(
    loop: AutoresearchLoop, capturing_ledger: _CapturingLedger
) -> None:
    eid = uuid4()
    await loop._emit_resolved(
        eid,
        outcome="keep",
        observed_delta=1.5,
        rationale="kept: outcome over threshold",
        now=NOW,
    )

    assert len(capturing_ledger.writes) == 1
    call = capturing_ledger.writes[0]
    assert call["execute"]["tool"] == "emit_experiment_resolved"
    assert call["propose"]["target_kind"] == "experiment_resolved"
    assert call["quadrant"] == "active_deterministic"
    assert call["timestamp"] == NOW


async def test_emit_resolved_args_validate_against_payload_model(
    loop: AutoresearchLoop, capturing_ledger: _CapturingLedger
) -> None:
    eid = uuid4()
    await loop._emit_resolved(
        eid,
        outcome="discard",
        observed_delta=-0.3,
        rationale="discarded: regression observed",
        now=NOW,
    )
    args = capturing_ledger.writes[0]["execute"]["args"]
    payload = ExperimentResolvedPayload.model_validate(args)
    assert payload.experiment_id == eid
    assert payload.outcome == "discard"
    assert payload.observed_delta == pytest.approx(-0.3)
    assert payload.rationale == "discarded: regression observed"
    assert payload.resolved_at == NOW


# ---------------------------------------------------------------------------
# _emit_metric_observation
# ---------------------------------------------------------------------------


async def test_emit_metric_observation_routes_through_ledger_write_with_correct_tool(
    loop: AutoresearchLoop,
    capturing_ledger: _CapturingLedger,
    carol_pp: PersonPosition,
) -> None:
    position = get_position("cfo")
    assert position is not None
    activity = _RecentActivity(chat_count_24h=3, matched_pattern_count=1)

    await loop._emit_metric_observation(carol_pp, position, activity, now=NOW)

    # cfo has a headline metric, so a write must land.
    assert len(capturing_ledger.writes) == 1
    call = capturing_ledger.writes[0]
    assert call["execute"]["tool"] == "emit_metric_observed"
    assert call["propose"]["target_kind"] == "metric_observed"
    assert call["quadrant"] == "passive_deterministic"
    assert call["timestamp"] == NOW


async def test_emit_metric_observation_args_validate_against_payload_model(
    loop: AutoresearchLoop,
    capturing_ledger: _CapturingLedger,
    carol_pp: PersonPosition,
) -> None:
    position = get_position("cfo")
    assert position is not None
    activity = _RecentActivity(chat_count_24h=3, matched_pattern_count=1)

    await loop._emit_metric_observation(carol_pp, position, activity, now=NOW)
    args = capturing_ledger.writes[0]["execute"]["args"]
    payload = MetricObservedPayload.model_validate(args)

    metric = headline_metric_for_position("cfo")
    assert metric is not None
    assert payload.metric_id == metric.metric_id
    assert payload.position == "cfo"
    assert payload.observed_at == NOW


# ---------------------------------------------------------------------------
# Negative-space invariant: no helper bypasses the PEVR primitive.
# ---------------------------------------------------------------------------


async def test_no_loop_helper_writes_outside_pevr_primitive(
    loop: AutoresearchLoop,
    capturing_ledger: _CapturingLedger,
    carol_pp: PersonPosition,
    cfo_candidate: ImprovementCandidate,
) -> None:
    """All four helpers route through ``ledger.write`` with full PEVR shape.

    Catches the ``add_entry``-bypass regression directly: every recorded
    write must carry a ``propose`` block, an ``execute`` payload with a
    ``tool="emit_..."`` string, a verify result, a resolve result, and a
    quadrant tag.
    """
    eid = uuid4()
    started = NOW
    finished = NOW + timedelta(seconds=10)
    position = get_position("cfo")
    assert position is not None
    activity = _RecentActivity()

    await loop._emit_proposed(carol_pp, cfo_candidate, eid, now=NOW)
    await loop._emit_run(carol_pp, cfo_candidate, eid, started, finished)
    await loop._emit_resolved(
        eid, outcome="keep", observed_delta=1.0, rationale="kept", now=NOW
    )
    await loop._emit_metric_observation(carol_pp, position, activity, now=NOW)

    assert len(capturing_ledger.writes) == 4
    expected_tools = {
        "emit_experiment_proposed",
        "emit_experiment_run",
        "emit_experiment_resolved",
        "emit_metric_observed",
    }
    seen_tools = {w["execute"]["tool"] for w in capturing_ledger.writes}
    assert seen_tools == expected_tools

    for w in capturing_ledger.writes:
        assert w["propose"]["proposed_by"] == "autoresearch_loop"
        assert w["execute"]["tool"].startswith("emit_")
        assert isinstance(w["execute"]["args"], dict)
        assert w["verify"]["passed"] is True
        assert w["resolve"]["outcome"] == "keep"
        assert w["quadrant"] in {
            "active_probabilistic",
            "active_deterministic",
            "passive_deterministic",
        }
