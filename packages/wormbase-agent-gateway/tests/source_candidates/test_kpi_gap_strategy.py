"""L1 Sub-wave B — KpiGapAcquisitionStrategy tests.

Covers:

  * Empty KPI tree → no proposals (honest stub posture).
  * Revenue / sales / ARR patterns → stripe/salesforce at the matched
    confidence.
  * Signups / users / DAU patterns → postgres/notion at the matched
    confidence.
  * Pipeline / leads patterns → hubspot/salesforce.
  * Fallback to csv_local at 0.40 for unmatched KPIs.
  * Domain id is threaded through to ``domain_id_hint``.
  * Replay stability — same KPI tree → same candidate_ids.
  * Multiple unbacked KPIs → one proposal per gap.
  * Evidence carries the kpi_node_id + matched pattern.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_agent_gateway.source_candidates import (
    KpiGapAcquisitionStrategy,
    KpiNodeRecord,
)


_COMPANY = UUID("00000000-0000-0000-0000-000000000a01")


class _FakeKpiNodeReader:
    def __init__(self, nodes=None):
        self.nodes = nodes or []

    async def list_kpi_nodes_without_source(self, *, company_id):
        return list(self.nodes)


# ---------------------------------------------------------------------------
# Honest-stub posture (empty KPI tree)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kpi_gap_empty_reader_returns_no_proposals() -> None:
    """When the reader returns no unbacked nodes, the strategy emits nothing.

    Honest stub posture per spec §4.3 — "configured ·
    awaiting-kpi-tree-population" state.
    """
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=_FakeKpiNodeReader())
    proposals = await strat.propose(company_id=_COMPANY)
    assert proposals == []


# ---------------------------------------------------------------------------
# Pattern bank matches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kpi_gap_revenue_pattern_proposes_stripe() -> None:
    """KPI name like ``q3_net_revenue`` → propose ``stripe`` at 0.80."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-1", name="q3_net_revenue", domain_id="dom-fin"),
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.proposed_kind == "stripe"
    assert p.proposed_identifier == "kpi:q3_net_revenue"
    assert p.strategy == "kpi_gap"
    assert p.domain_id_hint == "dom-fin"
    assert p.confidence == pytest.approx(0.80, abs=1e-4)
    assert "revenue" in p.reasoning.lower()
    assert p.evidence["kpi_node_id"] == "k-1"
    assert p.evidence["alternative_kind"] == "salesforce"


@pytest.mark.asyncio
async def test_kpi_gap_signups_pattern_proposes_postgres() -> None:
    """KPI name like ``new_signups`` → propose ``postgres`` at 0.65."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-2", name="new_signups", domain_id="dom-prod"),
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    p = proposals[0]
    assert p.proposed_kind == "postgres"
    assert p.evidence["alternative_kind"] == "mcp:notion"
    assert p.confidence == pytest.approx(0.65, abs=1e-4)


@pytest.mark.asyncio
async def test_kpi_gap_dau_pattern_proposes_postgres() -> None:
    """KPI name like ``daily_dau`` → propose ``postgres`` at 0.65."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-3", name="daily_dau", domain_id=None),
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    p = proposals[0]
    assert p.proposed_kind == "postgres"
    assert p.confidence == pytest.approx(0.65, abs=1e-4)


@pytest.mark.asyncio
async def test_kpi_gap_pipeline_pattern_proposes_hubspot() -> None:
    """KPI name like ``open_pipeline`` → propose ``hubspot`` at 0.70."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-4", name="open_pipeline", domain_id="dom-rev"),
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    p = proposals[0]
    assert p.proposed_kind == "hubspot"
    assert p.evidence["alternative_kind"] == "salesforce"
    assert p.confidence == pytest.approx(0.70, abs=1e-4)


@pytest.mark.asyncio
async def test_kpi_gap_leads_pattern_proposes_hubspot() -> None:
    """KPI name like ``qualified_leads`` → propose ``hubspot`` at 0.65."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-5", name="qualified_leads", domain_id=None),
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    p = proposals[0]
    assert p.proposed_kind == "hubspot"
    assert p.confidence == pytest.approx(0.65, abs=1e-4)


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kpi_gap_unmatched_kpi_falls_back_to_csv_local() -> None:
    """KPI name with no pattern hit → ``csv_local`` at 0.40."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-7", name="custom_metric_xyz", domain_id=None),
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    p = proposals[0]
    assert p.proposed_kind == "csv_local"
    assert p.confidence == pytest.approx(0.40, abs=1e-4)
    assert p.evidence["matched_pattern"] == "fallback"
    assert "manual file drop" in p.reasoning.lower()


# ---------------------------------------------------------------------------
# Domain threading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kpi_gap_threads_domain_id_through() -> None:
    """``domain_id_hint`` on the proposal carries the KPI node's domain_id."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-8", name="net_revenue", domain_id="dom-99"),
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    assert proposals[0].domain_id_hint == "dom-99"


@pytest.mark.asyncio
async def test_kpi_gap_handles_missing_domain_id() -> None:
    """``domain_id`` of ``None`` flows through to a ``None`` hint."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-9", name="net_revenue", domain_id=None),
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    assert proposals[0].domain_id_hint is None


# ---------------------------------------------------------------------------
# Multiple unbacked KPIs / replay stability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kpi_gap_multiple_unbacked_kpis_one_proposal_each() -> None:
    """Two unbacked KPIs → two proposals (one per gap)."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-a", name="q3_revenue", domain_id="dom-fin"),
        KpiNodeRecord(kpi_node_id="k-b", name="new_signups", domain_id="dom-prod"),
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    assert len(proposals) == 2
    ids = {p.candidate_id for p in proposals}
    assert len(ids) == 2  # distinct
    kinds = {p.proposed_kind for p in proposals}
    assert kinds == {"stripe", "postgres"}


@pytest.mark.asyncio
async def test_kpi_gap_replay_stability_same_input_same_candidate_id() -> None:
    """Same KPI input → same candidate_id across runs."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-r", name="q3_revenue", domain_id="dom-fin"),
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    first = await strat.propose(company_id=_COMPANY)
    second = await strat.propose(company_id=_COMPANY)
    assert first[0].candidate_id == second[0].candidate_id


@pytest.mark.asyncio
async def test_kpi_gap_skips_empty_kpi_name() -> None:
    """KPI node with blank name → skip (defensive)."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-empty", name="   ", domain_id=None),
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    assert proposals == []


@pytest.mark.asyncio
async def test_kpi_gap_confidence_in_unit_range() -> None:
    """Every proposal carries a confidence in [0.0, 1.0]."""
    reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id=f"k-{i}", name=name, domain_id=None)
        for i, name in enumerate(
            ["revenue_q1", "new_users", "open_pipeline", "weird_metric"]
        )
    ])
    strat = KpiGapAcquisitionStrategy(kpi_node_reader=reader)
    proposals = await strat.propose(company_id=_COMPANY)
    for p in proposals:
        assert 0.0 <= p.confidence <= 1.0
