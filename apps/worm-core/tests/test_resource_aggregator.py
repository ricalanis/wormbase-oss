"""W5.A2 — resource_aggregator unit tests.

Bundle shape, domain-filter semantics, max_per_kind cap.
"""

from __future__ import annotations

from uuid import UUID

from wormbase_core.resource_aggregator import (
    KpiSummary,
    ResourceBundle,
    SourceSummary,
    gather_related_resources,
)
from wormbase_core.topic_extractor import Topic


DOMAIN_RETENTION = UUID("dddddddd-0000-0000-0000-000000000001")
DOMAIN_FINANCE = UUID("dddddddd-0000-0000-0000-000000000002")

KPI_CHURN = UUID("aaaaaaaa-0000-0000-0000-000000000001")
KPI_ARR = UUID("aaaaaaaa-0000-0000-0000-000000000002")

SOURCE_STRIPE = UUID("bbbbbbbb-0000-0000-0000-000000000001")
SOURCE_AMP = UUID("bbbbbbbb-0000-0000-0000-000000000002")

DECISION_1 = UUID("cccc1111-0000-0000-0000-000000000001")
PROCESS_RECOVERY = UUID("cccc2222-0000-0000-0000-000000000001")
DP_REPORT = UUID("dddd3333-0000-0000-0000-000000000001")


async def _write_kpi_node(ledger, company_id, kpi_id: UUID, label: str,
                          domain_id: UUID | None = None) -> None:
    args = {
        "id": str(kpi_id),
        "label": label,
        "domain_id": str(domain_id) if domain_id else None,
        "formula": "delta(active)/active_prev",
        "unit": "pct",
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "kpi_node", "ref_id": str(kpi_id),
                 "reason": "t", "proposed_by": "t"},
        execute_fn=lambda a=args: {
            "tool": "emit_kpi_node", "args": a, "result_ref": str(kpi_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _write_source(ledger, company_id, source_id: UUID, name: str,
                       domain_id: UUID | None = None) -> None:
    args = {
        "source_id": str(source_id),
        "source_kind": "database",
        "uri": f"postgres://example/{name}",
        "added_via_flow": "dashboard_form",
        "suggested_domain": "ops",
        "suggested_classification": "internal",
        "name": name,
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "source_proposed", "ref_id": str(source_id),
                 "reason": "t", "proposed_by": "t"},
        execute_fn=lambda a=args: {
            "tool": "emit_source_proposed", "args": a,
            "result_ref": str(source_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )
    if domain_id is not None:
        confirm_args = {
            "source_id": str(source_id),
            "domain_id": str(domain_id),
            "classification": "internal",
            "confirmed_by_person": "00000000-0000-0000-0000-000000000099",
        }
        await ledger.write(
            company_id=company_id,
            propose={"target_kind": "source_confirmed",
                     "ref_id": str(source_id),
                     "reason": "t", "proposed_by": "t"},
            execute_fn=lambda a=confirm_args: {
                "tool": "emit_source_confirmed", "args": a,
                "result_ref": str(source_id),
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        )


async def _write_decision(ledger, company_id, decision_id: UUID, text: str,
                          channel: str = "C-rev") -> None:
    args = {
        "decision_id": str(decision_id),
        "decision_text": text,
        "decision_at": "2026-04-15T12:00:00+00:00",
        "channel_id": channel,
        "decided_by_persons": [],
        "evidence_message_ids": [],
        "confidence": 0.8,
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "decision_recorded",
                 "ref_id": str(decision_id),
                 "reason": "t", "proposed_by": "t"},
        execute_fn=lambda a=args: {
            "tool": "emit_decision_recorded", "args": a,
            "result_ref": str(decision_id),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _write_process(ledger, company_id, pid: UUID, name: str,
                         domain: str = "retention") -> None:
    args = {
        "process_id": str(pid),
        "process_name": name,
        "steps": [
            {"order": 1, "actor": "Alice", "action": "x"},
            {"order": 2, "actor": "Bob", "action": "y"},
            {"order": 3, "actor": "Carol", "action": "z"},
        ],
        "domain": domain,
        "confidence": 0.9,
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "process_map_proposed",
                 "ref_id": str(pid),
                 "reason": "t", "proposed_by": "t"},
        execute_fn=lambda a=args: {
            "tool": "emit_process_map_proposed", "args": a,
            "result_ref": str(pid),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


async def _write_data_product(ledger, company_id, dpid: UUID, name: str,
                              domain_id: UUID | None = None) -> None:
    args = {
        "data_product_id": str(dpid),
        "name": name,
        "kind": "report",
        "requested_by_person_id": "00000000-0000-0000-0000-000000000099",
        "sources_required": [],
        "domain_id": str(domain_id) if domain_id else None,
        "parameters": {},
    }
    await ledger.write(
        company_id=company_id,
        propose={"target_kind": "data_product_proposed",
                 "ref_id": str(dpid),
                 "reason": "t", "proposed_by": "t"},
        execute_fn=lambda a=args: {
            "tool": "emit_data_product_proposed", "args": a,
            "result_ref": str(dpid),
        },
        verify_fn=lambda _r: {"checks": [], "passed": True},
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
    )


def _retention_topic() -> Topic:
    return Topic(kind="kpi", id=KPI_CHURN, label="churn",
                  confidence=0.95, domain_id=DOMAIN_RETENTION)


# ---------------------------------------------------------------------------
# ResourceBundle structure
# ---------------------------------------------------------------------------


def test_resource_bundle_is_empty_on_default():
    b = ResourceBundle()
    assert b.is_empty()


def test_resource_bundle_to_payload_round_trip():
    b = ResourceBundle(
        kpis=[KpiSummary(kpi_id=KPI_CHURN, label="churn", unit="pct")],
        sources=[SourceSummary(source_id=SOURCE_STRIPE, label="stripe",
                                status="connected")],
    )
    payload = b.to_payload()
    assert payload["kpis"][0]["label"] == "churn"
    assert payload["sources"][0]["status"] == "connected"
    assert payload["decisions"] == []


# ---------------------------------------------------------------------------
# gather_related_resources
# ---------------------------------------------------------------------------


async def test_gather_kpis_filtered_by_domain(ledger, company_id):
    await _write_kpi_node(ledger, company_id, KPI_CHURN, "churn",
                          DOMAIN_RETENTION)
    await _write_kpi_node(ledger, company_id, KPI_ARR, "ARR",
                          DOMAIN_FINANCE)
    bundle = await gather_related_resources(
        _retention_topic(), ledger=ledger, company_id=company_id,
    )
    assert len(bundle.kpis) == 1
    assert bundle.kpis[0].kpi_id == KPI_CHURN


async def test_gather_sources_filtered_by_domain(ledger, company_id):
    await _write_source(ledger, company_id, SOURCE_STRIPE, "stripe",
                        DOMAIN_RETENTION)
    await _write_source(ledger, company_id, SOURCE_AMP, "amplitude",
                        DOMAIN_FINANCE)
    bundle = await gather_related_resources(
        _retention_topic(), ledger=ledger, company_id=company_id,
    )
    assert len(bundle.sources) == 1
    assert bundle.sources[0].label == "stripe"
    assert bundle.sources[0].status == "confirmed"


async def test_gather_decisions_returns_recent(ledger, company_id):
    await _write_decision(ledger, company_id, DECISION_1,
                          "moved Europe activation experiment to control")
    bundle = await gather_related_resources(
        _retention_topic(), ledger=ledger, company_id=company_id,
    )
    assert len(bundle.decisions) == 1
    assert bundle.decisions[0].decision_text.startswith("moved Europe")


async def test_gather_processes_returns_recent(ledger, company_id):
    await _write_process(ledger, company_id, PROCESS_RECOVERY,
                         "customer recovery flow", "retention")
    bundle = await gather_related_resources(
        _retention_topic(), ledger=ledger, company_id=company_id,
    )
    assert len(bundle.processes) == 1
    assert bundle.processes[0].process_name == "customer recovery flow"
    assert bundle.processes[0].step_count == 3


async def test_gather_data_products_filtered_by_domain(ledger, company_id):
    await _write_data_product(ledger, company_id, DP_REPORT,
                              "Retention deep-dive", DOMAIN_RETENTION)
    bundle = await gather_related_resources(
        _retention_topic(), ledger=ledger, company_id=company_id,
    )
    assert len(bundle.data_products) == 1
    assert bundle.data_products[0].name == "Retention deep-dive"


async def test_gather_max_per_kind_caps_lists(ledger, company_id):
    """Ten KPIs in the domain → only top 3 surface."""
    for i in range(10):
        kid = UUID(f"aaaaaaaa-0000-0000-0000-{i:012x}")
        await _write_kpi_node(ledger, company_id, kid, f"metric_{i}",
                              DOMAIN_RETENTION)
    bundle = await gather_related_resources(
        _retention_topic(), ledger=ledger, company_id=company_id,
        max_per_kind=3,
    )
    assert len(bundle.kpis) == 3


async def test_gather_empty_tenant_returns_empty_bundle(ledger, company_id):
    bundle = await gather_related_resources(
        _retention_topic(), ledger=ledger, company_id=company_id,
    )
    assert bundle.is_empty()
