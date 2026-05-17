"""Semantic Layer Wave 2 Task 1 — agent-gateway entry kinds.

Pins four new payload classes (per doctrine Addendum 3 — single-kind
PEVR for ``agent_query``; status-field consolidation for
``agent_grant`` and ``credential``):

* ``AgentRegisteredPayload`` (kind ``agent_registered``)
* ``AgentGrantPayload``      (kind ``agent_grant``)
* ``AgentQueryPayload``      (kind ``agent_query``)
* ``CredentialPayload``      (kind ``credential``)

These tests pin:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Round-trip via ``model_dump`` → ``model_validate`` byte-equivalently.
* Status-field consolidation (``active`` vs ``revoked`` on a single
  kind) for ``agent_grant`` and ``credential``.
* Phase-field discriminator (propose/execute/verify/resolve) for
  ``agent_query``, including population of verify/resolve fields
  (row_count, cost_usd, latency_ms).
"""
from __future__ import annotations

import pytest

from wormbase_ledger.entries import (
    KIND_REGISTRY,
    AgentGrantPayload,
    AgentQueryPayload,
    AgentRegisteredPayload,
    CredentialPayload,
)


@pytest.mark.parametrize(
    "kind",
    [
        "agent_registered",
        "agent_grant",
        "agent_query",
        "credential",
    ],
)
def test_kind_registered(kind: str) -> None:
    assert kind in KIND_REGISTRY


def test_kind_registry_size_after_task_1() -> None:
    """Wave 1 ended at 88; Task 1 adds 4 → 92. Task 3 will add 4 more → 96.
    v2.B Phase 2 (2026-05-12) adds 3 more compounding-loop kinds → 99.
    v2.B Phase 3 (2026-05-12) adds ``clock_tick`` for the periodic-tick
    emitter → 100. v2.A Batch A (2026-05-12) adds 3 subscription kinds
    (``agent_subscription_created`` / ``_revoked`` /
    ``agent_event_delivered``) → 103. Final wave item #5 (2026-05-13)
    adds ``agent_metadata_updated`` for the agent edit flow → 104.
    Final wave item #7 (2026-05-13) adds ``tenant_quota_consumed`` for
    the tenant-policy ledger emission opt-in → 105. Post-rest #1
    (2026-05-13) adds ``tenant_engine_registered`` for engine-per-tenant
    Phase 2 → 106. L3 Sub-wave A (2026-05-29) adds three lake-side
    lineage-discovery kinds (``lineage_edge_proposed`` /
    ``lineage_edge_confirmed`` / ``lineage_edge_rejected``) → 109.
    Onboarding Sub-wave C (2026-05-30) adds ``domain_pack_selected`` +
    ``person_invited`` → 111. L7 Sub-wave A (2026-05-30) adds three
    quality-checks kinds (``quality_check_proposed`` /
    ``quality_check_confirmed`` / ``quality_check_rejected``) → 114.
    L4 Sub-wave A (2026-06-02) adds three schema-impact kinds
    (``schema_impact_proposed`` / ``schema_impact_confirmed`` /
    ``schema_impact_rejected``) → 117. L5 Sub-wave A (2026-06-05)
    adds three semantic-type fingerprinting kinds
    (``semantic_type_proposed`` / ``semantic_type_confirmed`` /
    ``semantic_type_rejected``) → 120. L6 Sub-wave A (2026-06-06)
    adds three column-classification kinds
    (``column_classification_proposed`` /
    ``column_classification_confirmed`` /
    ``column_classification_rejected``) → 123. L8 Sub-wave A
    (2026-06-07) adds three cross-source entity-stitch kinds
    (``entity_stitch_proposed`` / ``entity_stitch_confirmed`` /
    ``entity_stitch_rejected``) → 126. L1 Sub-wave A (2026-06-08)
    adds three source-candidate triage kinds
    (``source_candidate_proposed`` / ``source_candidate_promoted`` /
    ``source_candidate_rejected``) → 129. L2 Sub-wave A (2026-06-09)
    adds three catalog-drift detection kinds
    (``catalog_drift_proposed`` / ``catalog_drift_acknowledged`` /
    ``catalog_drift_rejected``) → 132 (FINAL planned axis per
    spec §11). Catalog-mirror Wave 2 Sub-wave A (2026-06-09 follow-
    on) adds ``catalog_table_imported`` substrate → 133.

    Accept the range so this test stays green across parallel landings;
    the precise count is pinned in ``test_entry_kind_registration.py``.
    """
    assert 92 <= len(KIND_REGISTRY) <= 133


def test_agent_registered_payload_roundtrip() -> None:
    p = AgentRegisteredPayload(
        agent_id="agent-uuid-1",
        external_provider="claude",
        display_name="Claude Research Agent",
        registered_by="admin-person-uuid",
    )
    assert AgentRegisteredPayload.model_validate(p.model_dump()) == p
    assert p.kind == "agent_registered"


def test_agent_registered_external_provider_enum() -> None:
    """All five literal providers accepted."""
    for provider in ("claude", "openai", "kimi", "internal_worm", "other"):
        p = AgentRegisteredPayload(
            agent_id="agent-uuid-1",
            external_provider=provider,  # type: ignore[arg-type]
            display_name="X",
            registered_by="admin",
        )
        assert p.external_provider == provider


def test_agent_grant_payload_with_status_field_for_assign_and_revoke() -> None:
    """Per Addendum 3 — single kind with status field, not separate _revoked kind."""
    g_assign = AgentGrantPayload(
        agent_id="agent-uuid-1",
        grant_kind="domain.read",
        grant_target="domain-finance-uuid",
        status="active",
        granted_by="admin-person-uuid",
        budget_remaining_usd=None,
    )
    g_revoke = AgentGrantPayload(
        agent_id="agent-uuid-1",
        grant_kind="domain.read",
        grant_target="domain-finance-uuid",
        status="revoked",
        granted_by="admin-person-uuid",
        budget_remaining_usd=None,
    )
    assert AgentGrantPayload.model_validate(g_assign.model_dump()) == g_assign
    assert AgentGrantPayload.model_validate(g_revoke.model_dump()) == g_revoke
    assert g_assign.status != g_revoke.status


def test_agent_grant_payload_with_model_grant_includes_budget() -> None:
    """Model grants carry ``budget_remaining_usd``; data grants typically don't."""
    g = AgentGrantPayload(
        agent_id="agent-uuid-1",
        grant_kind="model.access",
        grant_target="kimi",
        status="active",
        granted_by="admin-person-uuid",
        budget_remaining_usd="5.00",
    )
    assert g.budget_remaining_usd == "5.00"
    assert g.grant_kind == "model.access"


def test_agent_query_payload_carries_pevr_phase() -> None:
    """Per Addendum 3 — single kind with phase field; written via Ledger.write PEVR."""
    p_propose = AgentQueryPayload(
        agent_id="agent-uuid-1",
        mcp_tool="lake.semantic.metric",
        args={"name": "revenue_q3", "filter": {"region": "EMEA"}},
        route_mode="broker",
        phase="propose",
    )
    p_resolve = AgentQueryPayload(
        agent_id="agent-uuid-1",
        mcp_tool="lake.semantic.metric",
        args={"name": "revenue_q3", "filter": {"region": "EMEA"}},
        route_mode="broker",
        phase="resolve",
        row_count=2,
        cost_usd="0.013",
        latency_ms=420,
    )
    assert p_propose.phase == "propose"
    assert p_resolve.phase == "resolve"
    assert p_resolve.row_count == 2
    assert p_resolve.cost_usd == "0.013"
    assert p_resolve.latency_ms == 420


def test_agent_query_payload_all_phases_accepted() -> None:
    """All four PEVR phases construct cleanly."""
    for phase in ("propose", "execute", "verify", "resolve"):
        p = AgentQueryPayload(
            agent_id="a",
            mcp_tool="t",
            args={},
            route_mode="broker",
            phase=phase,  # type: ignore[arg-type]
        )
        assert p.phase == phase


def test_agent_query_payload_caused_by_chains() -> None:
    """``caused_by`` references a parent audit_trail_id for chained queries."""
    p = AgentQueryPayload(
        agent_id="a",
        mcp_tool="t",
        args={},
        route_mode="federate",
        phase="propose",
        caused_by="parent-audit-trail-uuid",
    )
    assert p.caused_by == "parent-audit-trail-uuid"


def test_credential_payload_with_status_field_for_issue_and_revoke() -> None:
    """Per Addendum 3 — single kind with status field."""
    c_issue = CredentialPayload(
        agent_id="agent-uuid-1",
        credential_kind="data",
        target="snowflake://WORMBASE_SPIKE.PUBLIC.REVENUE_BY_REGION",
        status="active",
        ttl_expires_at="2026-05-11T18:00:00Z",
        issued_by="agent-gateway",
    )
    c_revoke = CredentialPayload(
        agent_id="agent-uuid-1",
        credential_kind="data",
        target="snowflake://WORMBASE_SPIKE.PUBLIC.REVENUE_BY_REGION",
        status="revoked",
        ttl_expires_at="2026-05-11T18:00:00Z",
        issued_by="agent-gateway",
    )
    assert CredentialPayload.model_validate(c_issue.model_dump()) == c_issue
    assert CredentialPayload.model_validate(c_revoke.model_dump()) == c_revoke
    assert c_issue.status == "active"
    assert c_revoke.status == "revoked"


def test_credential_payload_kind_data_vs_model() -> None:
    """Both data and model credential_kinds construct cleanly."""
    c_data = CredentialPayload(
        agent_id="a",
        credential_kind="data",
        target="resource-uuid",
        status="active",
        ttl_expires_at="2026-05-11T18:00:00Z",
        issued_by="agent-gateway",
    )
    c_model = CredentialPayload(
        agent_id="a",
        credential_kind="model",
        target="kimi",
        status="active",
        ttl_expires_at="2026-05-11T18:00:00Z",
        issued_by="agent-gateway",
    )
    assert c_data.credential_kind == "data"
    assert c_model.credential_kind == "model"
