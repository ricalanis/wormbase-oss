"""F3 (Sub-wave A) — kpi_gap_triggered dispatcher hook.

Pins the kpi_gap_triggered_poller wiring added 2026-05-30.
``KpiGapTriggeredFlow`` was factory-only until this wave; the
poller below watches for ``emit_semantic_gap_proposed`` ledger entries
(canonical agent-reported "no metric for this question" signal,
written by the ``lake.semantic.gap`` MCP tool) and dispatches each
one through ``propose_for_gap``.

Most tests target the extracted ``dispatch_kpi_gap_row`` helper so we
can exercise the row-handling logic without standing up a Postgres
fixture. The end-to-end Postgres loop is covered by ASML smoke tests
under ``tests/integration``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from wormbase_chat_presence.chat_flows import KpiGap, KpiGapTriggeredFlow
from wormbase_core.service import dispatch_kpi_gap_row
from wormbase_core.source_builder import SourceBuilder


class _AllowGate:
    def __init__(self, allow: bool = True) -> None:
        self._allow = allow
        self.calls: list[tuple[str, str]] = []

    async def allow(self, channel_id: str, qtype: str) -> bool:
        self.calls.append((channel_id, qtype))
        return self._allow


class _StubChat:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(
        self, channel_id: str, text: str, *, speech_act: str = "proposal",
    ) -> None:
        self.sent.append((channel_id, text, speech_act))


def _payload(
    *,
    nl_question: str | None = "what is our churn rate",
    proposed_metric_name: str | None = None,
    reason: str = "no_match",
    agent_id: str = "agent-1",
) -> dict[str, Any]:
    """Shape a `emit_semantic_gap_proposed` execute-row payload."""
    args: dict[str, Any] = {
        "agent_id": agent_id,
        "reason": reason,
    }
    if nl_question is not None:
        args["nl_question"] = nl_question
    if proposed_metric_name is not None:
        args["proposed_metric_name"] = proposed_metric_name
    return {"tool": "emit_semantic_gap_proposed", "args": args}


# --------------------------------------------------------------------- helpers


@pytest.mark.asyncio
async def test_dispatch_row_uses_nl_question_as_kpi_id_when_no_metric_name(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """When proposed_metric_name is absent, kpi_id is derived from nl_question."""
    builder = SourceBuilder(ledger, clock)
    gate = _AllowGate(allow=True)
    chat = _StubChat()
    flow = KpiGapTriggeredFlow(builder, ledger, gate, chat)
    payload = _payload(nl_question="what is our churn rate")

    dispatched = await dispatch_kpi_gap_row(
        flow, company_id, payload,
        default_channel_id="C-finance",
    )
    assert dispatched is True
    rows = await ledger.fetch(company_id)
    proposals = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_proposed"
    ]
    assert len(proposals) == 1
    response_tag = proposals[0]["payload"]["args"]["added_in_response_to"]
    assert "what is our churn rate" in response_tag


@pytest.mark.asyncio
async def test_dispatch_row_prefers_metric_name_over_nl_question(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """When both are set, the canonical metric name wins as kpi_id."""
    builder = SourceBuilder(ledger, clock)
    gate = _AllowGate(allow=True)
    chat = _StubChat()
    flow = KpiGapTriggeredFlow(builder, ledger, gate, chat)
    payload = _payload(
        nl_question="what is our churn rate",
        proposed_metric_name="churn_rate",
    )

    dispatched = await dispatch_kpi_gap_row(
        flow, company_id, payload,
        default_channel_id="C-finance",
    )
    assert dispatched is True
    rows = await ledger.fetch(company_id)
    proposals = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_proposed"
    ]
    assert len(proposals) == 1
    assert (
        proposals[0]["payload"]["args"]["added_in_response_to"]
        == "kpi:churn_rate"
    )


@pytest.mark.asyncio
async def test_dispatch_row_skips_when_no_kpi_id_extractable(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """A degenerate payload (no nl_question + no proposed_metric_name)
    is skipped — returns False, no flow call lands."""
    builder = SourceBuilder(ledger, clock)
    gate = _AllowGate(allow=True)
    chat = _StubChat()
    flow = KpiGapTriggeredFlow(builder, ledger, gate, chat)
    payload = _payload(nl_question=None, proposed_metric_name=None)
    payload["args"].pop("nl_question", None)
    payload["args"].pop("proposed_metric_name", None)

    dispatched = await dispatch_kpi_gap_row(
        flow, company_id, payload,
        default_channel_id="C-finance",
    )
    assert dispatched is False
    rows = await ledger.fetch(company_id)
    assert not any(
        r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_proposed"
        for r in rows
    )


@pytest.mark.asyncio
async def test_dispatch_row_threads_default_channel_to_interjection_gate(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """The owner_channel_id passed into KpiGap is the dispatch helper's
    default_channel_id kwarg — it's the channel the worm asks
    permission against."""
    builder = SourceBuilder(ledger, clock)
    gate = _AllowGate(allow=True)
    chat = _StubChat()
    flow = KpiGapTriggeredFlow(builder, ledger, gate, chat)
    payload = _payload(proposed_metric_name="net_revenue")

    await dispatch_kpi_gap_row(
        flow, company_id, payload,
        default_channel_id="C-finance",
    )
    assert gate.calls and gate.calls[0][0] == "C-finance"


@pytest.mark.asyncio
async def test_dispatch_row_when_default_channel_absent_does_not_propose(
    ledger: Any, company_id: UUID, clock: Any,
) -> None:
    """KpiGapTriggeredFlow.propose_for_gap returns None when
    owner_channel_id is unset (no channel = no question to ask)."""
    builder = SourceBuilder(ledger, clock)
    gate = _AllowGate(allow=True)
    chat = _StubChat()
    flow = KpiGapTriggeredFlow(builder, ledger, gate, chat)
    payload = _payload(proposed_metric_name="churn_rate")

    dispatched = await dispatch_kpi_gap_row(
        flow, company_id, payload,
        default_channel_id=None,
    )
    # The helper still returns True (it dispatched), but the flow
    # internally returned None because no channel was set.
    assert dispatched is True
    rows = await ledger.fetch(company_id)
    proposals = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_proposed"
    ]
    assert proposals == []


@pytest.mark.asyncio
async def test_dispatch_row_propagates_flow_exceptions(
    company_id: UUID,
) -> None:
    """If the flow itself raises, the helper does NOT swallow — the
    poller loop is the level that decides swallow-vs-propagate.
    Documents the contract for callers."""

    class _Boom:
        async def propose_for_gap(
            self, _cid: UUID, _gap: KpiGap, now: Any = None,
        ) -> None:
            raise RuntimeError("simulated downstream failure")

    payload = _payload(proposed_metric_name="oops")
    with pytest.raises(RuntimeError, match="simulated"):
        await dispatch_kpi_gap_row(
            _Boom(), company_id, payload,
            default_channel_id="C-finance",
        )


@pytest.mark.asyncio
async def test_dispatch_row_handles_empty_payload_gracefully(
    company_id: UUID,
) -> None:
    """A payload missing the args dict entirely is treated as no kpi_id;
    the flow is never invoked (defensive shape-check)."""
    called = False

    class _Tracker:
        async def propose_for_gap(self, *_a, **_k) -> None:  # noqa: ANN002
            nonlocal called
            called = True

    dispatched = await dispatch_kpi_gap_row(
        _Tracker(), company_id, {"tool": "emit_semantic_gap_proposed"},
        default_channel_id="C-finance",
    )
    assert dispatched is False
    assert called is False
