"""Ledger payload tests for v2.A agent-as-teammate entry kinds.

Pins the three additive payload classes shipped 2026-05-12:

  - ``agent_subscription_created`` — agent declares an interest filter
  - ``agent_subscription_revoked`` — subscription lifecycle ending
  - ``agent_event_delivered`` — one dispatch decision (delivered /
    failed / no_target) by the ``SubscriptionDispatcher`` Reactivity

The compounding-loop family already had four axes after v2.B Phase 2
(``bad_pattern_proposed``, ``semantic_gap_escalated``,
``data_product_recommended``, plus ``clock_tick`` for the periodic
trigger). These v2.A additions close Seam #3 (agents stop being
read-only consumers of compounded learnings) by giving every agent a
ledger-resident subscription handle + per-delivery audit trail.

Net +3 → KIND_REGISTRY = 103, under the 120-kind Wave F Addendum 1
ceiling. The size-pin assertion at the bottom catches silent drift.
"""

from __future__ import annotations

import pytest

from wormbase_ledger.entries import (
    KIND_REGISTRY,
    AgentEventDeliveredPayload,
    AgentSubscriptionCreatedPayload,
    AgentSubscriptionRevokedPayload,
)


def test_agent_subscription_created_roundtrip() -> None:
    """Created payload survives ``model_dump → model_validate``.

    Canonical contract for any ledger-bound payload — the write
    primitive hands ``model_dump(mode="json")`` to the ledger writer,
    which round-trips it through ``model_validate`` on replay.
    """
    p = AgentSubscriptionCreatedPayload(
        subscription_id="sub_abc",
        agent_id="agent_xyz",
        filter={
            "kinds": ["bad_pattern_proposed"],
            "domains": [],
            "agent_id_ref": "agent_xyz",
            "payload_path_eq": [],
        },
        transport="mcp_stream",
        webhook_url=None,
        webhook_secret_ref=None,
        description="MY bad-pattern alerts",
    )
    raw = p.model_dump()
    p2 = AgentSubscriptionCreatedPayload.model_validate(raw)
    assert p == p2


def test_agent_subscription_revoked_roundtrip() -> None:
    """Revoked payload survives roundtrip; reason discriminator preserved."""
    p = AgentSubscriptionRevokedPayload(
        subscription_id="sub_abc",
        reason="agent_request",
    )
    raw = p.model_dump()
    assert AgentSubscriptionRevokedPayload.model_validate(raw) == p


def test_agent_event_delivered_roundtrip() -> None:
    """Delivery payload survives roundtrip; all status fields preserved."""
    p = AgentEventDeliveredPayload(
        subscription_id="sub_abc",
        triggering_entry_seq=42,
        triggering_entry_kind="bad_pattern_proposed",
        transport_used="mcp_stream",
        delivery_status="delivered",
        duration_ms=12,
        error=None,
    )
    raw = p.model_dump()
    assert AgentEventDeliveredPayload.model_validate(raw) == p


def test_three_kinds_registered() -> None:
    """All three v2.A kinds auto-register via ``EntryPayload.__init_subclass__``."""
    for k in (
        "agent_subscription_created",
        "agent_subscription_revoked",
        "agent_event_delivered",
    ):
        assert k in KIND_REGISTRY, f"{k} not auto-registered"


def test_revoked_reason_enum() -> None:
    """``reason`` is a closed Literal; arbitrary strings are rejected at validation."""
    with pytest.raises(Exception):
        AgentSubscriptionRevokedPayload(
            subscription_id="sub_abc",
            reason="not_a_real_reason",  # type: ignore[arg-type]
        )


def test_registry_size_after_v2A_kinds() -> None:
    """v2.A Batch A lands at 103 (100 post-Phase-3 + 3 subscription kinds).

    Net +3 over the v2.B Phase 3 baseline of 100. The final wave
    (2026-05-13) adds ``agent_metadata_updated`` (item #5) → 104, then
    ``tenant_quota_consumed`` (item #7) → 105. Post-rest #1
    (2026-05-13) adds ``tenant_engine_registered`` for engine-per-
    tenant Phase 2 → 106. L3 Sub-wave A (2026-05-29) lands the three
    lake-side lineage-discovery kinds (``lineage_edge_proposed`` /
    ``lineage_edge_confirmed`` / ``lineage_edge_rejected``), bumping
    the baseline to 109. Onboarding Sub-wave C (2026-05-30) adds
    ``domain_pack_selected`` + ``person_invited`` → 111. L7 Sub-wave A
    (2026-05-30) lands the three lake-side quality-checks kinds
    (``quality_check_proposed`` / ``quality_check_confirmed`` /
    ``quality_check_rejected``) → 114. L4 Sub-wave A (2026-06-02)
    lands the three lake-side schema-impact kinds
    (``schema_impact_proposed`` / ``schema_impact_confirmed`` /
    ``schema_impact_rejected``) → 117. L5 Sub-wave A (2026-06-05)
    lands the three lake-side semantic-type fingerprinting kinds
    (``semantic_type_proposed`` / ``semantic_type_confirmed`` /
    ``semantic_type_rejected``) → 120 — 30 kinds remaining under the
    150-kind Rule 5 ceiling per Wave F Addendum 4. L6 Sub-wave A
    (2026-06-06) lands the three lake-side column-classification kinds
    (``column_classification_proposed`` /
    ``column_classification_confirmed`` /
    ``column_classification_rejected``) → 123 — 27 kinds remaining
    under the 150-kind Rule 5 ceiling. L-axis family 12 → 15 of 30
    cap per Addendum 4 §E. L8 Sub-wave A (2026-06-07) lands the three
    lake-side cross-source entity-stitch kinds
    (``entity_stitch_proposed`` / ``entity_stitch_confirmed`` /
    ``entity_stitch_rejected``) → 126 — 24 kinds remaining under the
    150-kind Rule 5 ceiling. L-axis family 15 → 18 of 30 cap per
    Addendum 4 §E. L1 Sub-wave A (2026-06-08) lands the three
    lake-side source-candidate triage kinds
    (``source_candidate_proposed`` / ``source_candidate_promoted`` /
    ``source_candidate_rejected``) → 129 — 21 kinds remaining under
    the 150-kind Rule 5 ceiling. L-axis family 18 → 21 of 30 cap per
    Addendum 4 §E. L2 Sub-wave A (2026-06-09) lands the three
    lake-side catalog-drift detection kinds
    (``catalog_drift_proposed`` / ``catalog_drift_acknowledged`` /
    ``catalog_drift_rejected``) → 132 — 18 kinds remaining under the
    150-kind Rule 5 ceiling. L-axis family 21 → 24 of 30 cap per
    Addendum 4 §E (L2 is the FINAL planned axis in this generation
    per spec §11). Catalog-mirror Wave 2 Sub-wave A (2026-06-09
    follow-on) adds ``catalog_table_imported`` substrate — 132 → 133;
    L-axis family unchanged at 24 of 30 (substrate only). Size pinned
    here so future drift is caught at commit time.
    """
    assert len(KIND_REGISTRY) == 133
