from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from wormbase_ledger.entries import KIND_REGISTRY, LedgerEntry

UID = UUID("0190a0a0-0000-7000-8000-000000000001")
CID = UUID("0190a0a0-0000-7000-8000-000000000002")
TS = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)


def test_ledger_entry_accepts_valid_kind_and_payload() -> None:
    e = LedgerEntry(
        entry_id=UID,
        company_id=CID,
        seq=1,
        ts=TS,
        kind="propose",
        quadrant="active_deterministic",
        payload={"target_kind": "source_proposed", "ref": "x"},
        prev_hash=b"\x00" * 32,
        hash=b"\x11" * 32,
    )
    assert e.kind == "propose"
    assert e.quadrant == "active_deterministic"


def test_ledger_entry_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        LedgerEntry(
            entry_id=UID,
            company_id=CID,
            seq=1,
            ts=TS,
            kind="nonsense",
            quadrant="active_deterministic",
            payload={},
            prev_hash=b"\x00" * 32,
            hash=b"\x11" * 32,
        )


def test_ledger_entry_rejects_unknown_quadrant() -> None:
    with pytest.raises(ValidationError):
        LedgerEntry(
            entry_id=UID,
            company_id=CID,
            seq=1,
            ts=TS,
            kind="propose",
            quadrant="invalid_quadrant",
            payload={},
            prev_hash=b"\x00" * 32,
            hash=b"\x11" * 32,
        )


def test_ledger_entry_rejects_naive_ts() -> None:
    with pytest.raises(ValidationError):
        LedgerEntry(
            entry_id=UID,
            company_id=CID,
            seq=1,
            ts=datetime(2026, 4, 22, 12, 0),
            kind="propose",
            quadrant="active_deterministic",
            payload={},
            prev_hash=b"\x00" * 32,
            hash=b"\x11" * 32,
        )


def test_kind_registry_has_all_kinds() -> None:
    expected = {
        # 4 canonical
        "propose", "execute", "verify", "resolve",
        # 15 domain
        "source_proposed", "source_confirmed", "source_connected", "source_profiled",
        "ingest_landed", "ingest_profiled",
        "memory_written", "concept_proposed", "concept_confirmed",
        "chat_received", "chat_sent", "gate_fired", "kpi_answered",
        "heuristic_experiment", "policy_applied",
        # 1 inference (added by Wave-2 review for cache provenance)
        "inference_served",
        # 5 medallion lake (Step 2 of canonical product arc)
        "source_bronzed", "source_silvered", "source_golded",
        "kpi_proposed", "lake_discovered",
        # 4 process retrieval (Step 3c of canonical product arc)
        "decision_recorded", "process_map_proposed",
        "system_map_node", "recurring_question",
        # 8 user structure + per-user autoresearch (Step 5)
        "person_registered", "position_assigned",
        "position_metric_added", "position_question_pattern",
        "experiment_proposed", "experiment_run", "experiment_resolved",
        "metric_observed",
        # 7 identity (Block A1 of the production-dashboard PRD)
        "person_proposed", "person_confirmed", "person_archived",
        "identity_linked", "identity_unlinked",
        "install_completed", "install_revoked",
        # 4 roles (Block A2 of the production-dashboard PRD)
        "role_assigned", "role_revoked",
        "domain_role_assigned", "resource_role_assigned",
        # 8 data products + notebooks (Block F of the production-dashboard PRD)
        "data_product_proposed", "data_product_generated",
        "data_product_consumed", "data_product_archived",
        "notebook_proposed", "notebook_run",
        "notebook_published", "notebook_archived",
        # 3 setup mode + progress (Block G of the production-dashboard PRD §17)
        "setup_mode_chosen", "setup_completed", "setup_step_advanced",
        # 1 MCP integration (Phase 0 spike — 2026-04-27 mcp-integration spec)
        "mcp_call_received",
        # 4 reactivity lifecycle (W5.A1 — Reactivity Protocol + Registry)
        "reactivity_proposed", "reactivity_confirmed",
        "reactivity_disabled", "reactivity_fired",
        # 3 resource conversation lifecycle (W5.A2 — Statement-to-Owner)
        "resource_conversation_proposed",
        "resource_conversation_replied",
        "resource_conversation_resolved",
        # 1 phenomenon gap detector (W5.A3 — Phenomenon-Gap Reactivities)
        "phenomenon_gap_detected",
        # 2 demo-day metrics + lessons (W8 — P1 + P9)
        "metrics_keep_rate_published",
        "experiment_lesson",
        # 4 chat-reply PEVR (Wave B Task H1 — chat-worm extraction plan)
        "chat_reply_proposed", "chat_reply_executed",
        "chat_reply_verified", "chat_reply_resolved",
        # 2 inferred propose-step kinds (Wave B.5 G.3 — identity-tracker
        # PositionInferenceReactivity + ResourceOwnershipReactivity).
        # See doctrine §E sign-off in
        # docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md
        "position_proposed", "resource_role_proposed",
        # 1 inference cache audit (Wave H Phase 1 Task 1A — inference-router).
        # Doctrine §4 process: registry 76 → 77, well under the Rule-5
        # threshold (100 in Doctrine Addendum 2 §A).
        "inference_cache_refreshed",
        # 2 tenant signup chain (Wave H Phase 1 Task 1B — multi-tenancy v2).
        # Doctrine §4 process: registry 77 → 79, well under the Rule-5
        # threshold (100 in Doctrine Addendum 2 §A). Both Slack OAuth
        # and email magic-link flows write this same chain.
        "tenant_signup_initiated",
        "tenant_signup_completed",
        # 1 silver-tier topic synthesis (Wave H Phase 2 Task 2B — process-worm).
        # Doctrine §4 process: registry 79 → 80, well under the Rule-5
        # threshold (100 in Doctrine Addendum 2 §A). Emitted by
        # ``TopicSynthesisReactivity`` after promoting the F.1 stub.
        "topic_proposed",
        # 2 admin confirm/reject for position proposals (Wave H Phase 2
        # Task 2C — Position Auto-Confirm UX). Doctrine §4 process:
        # registry 80 → 82, well under the Rule-5 threshold (100 in
        # Doctrine Addendum 2 §A). The propose-step kind
        # ``position_proposed`` (Wave B.5 G.3) carries the worm's
        # inference; ``position_confirmed`` and ``position_rejected``
        # carry the admin's review outcome via the new
        # ``/people/proposals`` queue surface. ``position_assigned``
        # remains the canonical confirm-step for direct admin
        # assignment (no propose precursor); ``position_confirmed``
        # is distinct because it always references a prior
        # ``position_proposed`` row and unlocks the projection's
        # ``position_review_status`` flag — neither of which
        # ``position_assigned`` carries (Rule 1 verified).
        "position_confirmed",
        "position_rejected",
        # 1 conversation provenance lineage (2026-05-05 plan —
        # WhatsApp + conversation-provenance substrate). Doctrine §4
        # process: registry 82 → 83, well under the Rule-5 threshold
        # (100 in Doctrine Addendum 2 §A). One PEVR cycle per
        # reconnect / initial-connect / channel-join brings the
        # bulk-history-replay messages onto the ledger; per-message
        # ``chat_received`` entries carry ``history_sync_id`` pointing
        # at this lineage entry's ref_id.
        "conversation_sync",
        # 5 catalog-mirror — Semantic Layer Wave 1 / Task 4
        # (2026-05-11). Data-plane Protocol that imports upstream-lake
        # structure (schemas, lineage, policies, semantic-layer
        # metrics) into the ledger via ``packages/wormbase-catalog-
        # mirror/``. Doctrine §4 process: registry 83 → 88, well under
        # the Rule-5 threshold (100 in Doctrine Addendum 2 §A).
        # The Phase 0 spike at ``docs/superpowers/notes/
        # 2026-05-10-semantic-layer-phase-0-spike.md`` validated the
        # full set (S1 dbt manifest, S2 Snowflake catalog).
        "external_catalog_imported",
        "external_catalog_drift_detected",
        "external_lineage_imported",
        "external_policy_imported",
        "external_metric_imported",
        # 4 agent-gateway core — Semantic Layer Wave 2 / Task 1
        # (2026-05-11). Agent identity + grants + query PEVR + token
        # lifecycle, written by ``packages/wormbase-agent-gateway/``.
        # Per doctrine Addendum 3: single-kind PEVR for ``agent_query``
        # (one kind, four phases via a ``phase`` discriminator);
        # status-field consolidation for ``agent_grant`` and
        # ``credential`` (one kind each, ``active`` vs ``revoked`` on a
        # status field rather than separate ``_revoked`` kinds).
        # Registry 88 → 92; Task 3 adds 4 compounding-loop kinds
        # bringing it to 96, still under the 100-kind ceiling.
        "agent_registered",
        "agent_grant",
        "agent_query",
        "credential",
        # 4 §4.5 compounding-layer kinds — Semantic Layer Wave 2 /
        # Task 3 (2026-05-11). Outcome ledger + correction suggestions
        # + template promotion + semantic-gap reports for the
        # compounding query layer. Per doctrine Addendum 3 §B: kept
        # as separate kinds (NOT folded into ``agent_query.resolve``
        # or ``external_metric_imported``) because the temporality
        # differs (outcomes land minutes-to-days after PEVR closes)
        # and the provenance differs (templates are agent-derived,
        # not upstream-imported). Registry 92 → 96.
        "query_outcome_recorded",
        "query_correction_suggested",
        "query_template_promoted",
        "semantic_gap_proposed",
        # 3 v2.B Phase 2 compounding axes — 2026-05-12.
        # Additive per schema-evolution doctrine Rule 2; compounding-loop
        # family budget has headroom under the raised 100-kind ceiling
        # per Wave F Addendum 1. Registry 96 → 99.
        "bad_pattern_proposed",
        "semantic_gap_escalated",
        "data_product_recommended",
        # 1 v2.B Phase 3 periodic clock-tick — 2026-05-12.
        # Ledger-resident tick written by ``ClockTickEmitter`` to drive
        # time-based Reactivities via the ``Periodic(every_seconds=N)``
        # predicate. Replaces the gap-escalation axis's previous
        # "fire on new gap write" trigger with a real cadence-driven
        # tick, so a freshly-installed worm can escalate prior gaps
        # without waiting for a second gap to land. Quadrant is
        # ``passive_deterministic`` — emitter output is fully a
        # function of (company_id, tick_interval_s, prior_count).
        # Registry 99 → 100, under the 120-kind ceiling per Wave F
        # Addendum 1.
        "clock_tick",
        # 3 v2.A Batch A agent-as-teammate kinds — 2026-05-12.
        # Closes journey Seam #3: agents stop being read-only consumers
        # of compounded learnings. Subscriptions are ledger-resident
        # for wire-replay determinism + SOC-2 audit; status-field
        # consolidation per doctrine Addendum 3 keeps revocation as a
        # single kind with a ``reason`` discriminator (rather than per-
        # reason kinds). Delivery is recorded as a PEVR ledger entry
        # so wire-replay reproduces deliveries; the network side-effect
        # is no-op'd in replay mode while the entry still writes.
        # Registry 100 → 103, under the 120-kind ceiling per Wave F
        # Addendum 1.
        "agent_subscription_created",
        "agent_subscription_revoked",
        "agent_event_delivered",
        # 1 agent edit flow — final wave item #5 (2026-05-13).
        # Wires the agent detail page's Edit modal. Mutable agent
        # metadata (display_name, description) — additive per
        # schema-evolution doctrine Rule 2; preserves agent_id
        # continuity so the audit trail does not fork on a rebrand.
        # Status-consolidation observed: emit a new
        # ``agent_metadata_updated`` to undo a prior update (no
        # separate ``_reverted`` kind). Registry 103 to 104, under
        # the 120-kind ceiling per Wave F Addendum 1.
        "agent_metadata_updated",
        # 1 tenant-policy ledger emission — final wave item #7
        # (2026-05-13). Periodic ledger entry summarizing per-tenant
        # MCP quota consumption, emitted by the opt-in
        # ``LedgerQuotaTracker`` Protocol impl. Default-OFF preserves
        # byte-identical Path 4 InMemoryQuotaTracker behavior; opt-in
        # delivers SOC-2 audit visibility into per-tenant quota
        # consumption. Registry 104 to 105, under the 120-kind
        # ceiling per Wave F Addendum 1.
        "tenant_quota_consumed",
        # 1 engine-per-tenant routing — post-rest item #1
        # (2026-05-13). Durable registration of a per-tenant database
        # engine, written when an operator provisions (or migrates
        # to) an isolated engine for a tenant. ``engine_kind ∈
        # {shared, isolated}`` with ``engine_dsn_secret_ref``
        # required only for ``isolated``; the most-recent entry per
        # tenant is the canonical state. Default-OFF preserves
        # byte-identical Path 4 TenantContext Shape A behavior;
        # Shape B activation is gated behind operator-driven Phase 3
        # tooling (not yet shipped). Registry 105 to 106, under the
        # 120-kind ceiling per Wave F Addendum 1.
        "tenant_engine_registered",
        # 3 L3 lake-side lineage-discovery kinds — L3 Sub-wave A
        # (2026-05-29). Back the lake-side L3 compounding loop's
        # projection_lineage_edges fold: proposed (by the inference
        # strategies' Compounding axis) → confirmed / rejected (by
        # admin operators). State transitions are forward-only —
        # every state change is a new ledger entry; no mutation of
        # prior entries. Additive per schema-evolution doctrine Rule
        # 2; net +3 (106 → 109), 11 kinds remaining under the
        # 120-kind ceiling per Wave F Addendum 1.
        "lineage_edge_proposed",
        "lineage_edge_confirmed",
        "lineage_edge_rejected",
        # 2 institutional onboarding kinds — Onboarding Sub-wave C
        # (2026-05-30). Back the Tier 2 domain pack picker and the
        # real co-admin invite emit. ``domain_pack_selected`` is the
        # parent PEVR cycle audit anchor for a pack pick; the
        # downstream fan-out (per-domain ``emit_domain_registered``
        # + per-policy ``emit_policy_applied`` execute entries)
        # reuses the existing kinds for additivity. ``person_invited``
        # records the invite intent before the invitee accepts; the
        # eventual ``person_proposed`` → ``person_confirmed`` cycle
        # closes the loop. Additive per schema-evolution doctrine
        # Rule 2; net +2 (109 → 111), 9 kinds remaining under the
        # 120-kind ceiling per Wave F Addendum 1.
        "domain_pack_selected",
        "person_invited",
        # L7 Sub-wave A (2026-05-30). Three lake-side quality-checks
        # kinds back the projection_quality_checks fold: proposed (by
        # the inference strategies' Compounding axis) → confirmed /
        # rejected (by admin operators). Structurally identical to
        # the L3 lineage-edge triple — same forward-only semantics,
        # same composite-PK collapse. Additive per Rule 2; net +3
        # (111 → 114), 6 kinds remaining under the 120-kind ceiling
        # per Wave F Addendum 1.
        "quality_check_proposed",
        "quality_check_confirmed",
        "quality_check_rejected",
        # L4 Sub-wave A (2026-06-02). Three lake-side schema-impact
        # kinds back the projection_schema_impacts fold: proposed (by
        # the L4 cross-axis lake loop that consumes L3 confirmed
        # edges + dbt-test signals + sample-stat type observations) →
        # confirmed / rejected (by admin operators). Structurally
        # identical to the L3 / L7 triples — same forward-only
        # semantics, same composite-PK collapse. Additive per Rule
        # 2; net +3 (114 → 117).
        "schema_impact_proposed",
        "schema_impact_confirmed",
        "schema_impact_rejected",
        # L5 Sub-wave A (2026-06-05). Three lake-side semantic-type
        # fingerprinting kinds back the projection_semantic_types
        # fold: proposed (by the L5 lake loop that runs three
        # fingerprinting strategies — column_name / value_pattern /
        # distribution — to infer column semantic types like
        # email / iso_date / uuid_v4 / pii_ssn) → confirmed /
        # rejected (by admin operators). Structurally identical to
        # the L3 / L7 / L4 triples — same forward-only semantics,
        # same composite-PK collapse. Additive per Rule 2; net +3
        # (117 → 120), 30 kinds remaining under the 150-kind
        # ceiling per Wave F Addendum 4. L-axis family count = 12
        # of 30 cap (Addendum 4 §E).
        "semantic_type_proposed",
        "semantic_type_confirmed",
        "semantic_type_rejected",
        # L6 Sub-wave A (2026-06-06). Three lake-side column-level
        # governance classification kinds back the
        # projection_column_classifications fold: proposed (by the L6
        # lake loop that runs three classification strategies —
        # semantic_type / naming_pattern / domain_default — to infer
        # column governance classifications among the 5 canonical
        # levels {public, internal, confidential, pii, regulated}) →
        # confirmed / rejected (by admin operators). 2nd cross-axis
        # chain after L4→L3: the ``semantic_type`` strategy reads
        # L5's confirmed semantic types via the new
        # ConfirmedSemanticTypeReader Protocol and threads the
        # ``upstream_semantic_type_id`` field back for the L5→L6
        # cross-axis link. Structurally identical to the L3 / L7 /
        # L4 / L5 triples — same forward-only semantics, same
        # composite-PK collapse. Additive per Rule 2; net +3
        # (120 → 123), 27 kinds remaining under the 150-kind ceiling
        # per Wave F Addendum 4. L-axis family count = 15 of 30 cap
        # (Addendum 4 §E).
        "column_classification_proposed",
        "column_classification_confirmed",
        "column_classification_rejected",
        # L8 Sub-wave A (2026-06-07). Three lake-side cross-source
        # entity-stitch kinds back the projection_entity_stitches
        # fold: proposed (by the L8 lake loop that runs three
        # stitching strategies — name_match / sample_overlap /
        # schema_shape — to infer cross-source bridges between two
        # ``(source, table, column)`` triples sharing a probable
        # entity identity, tagged with one of the 8 canonical
        # ``EntityKind`` values {person, organization, transaction,
        # product, event, location, session, other}) → confirmed /
        # rejected (by admin operators). 3rd cross-axis chain after
        # L4→L3 and L6→L5: the strategies read L5's confirmed
        # semantic types via the same ConfirmedSemanticTypeReader
        # Protocol L6 introduced and thread the
        # ``upstream_semantic_type_id`` field back for the L8→L5
        # cross-axis link. Structurally identical to the L3 / L7 /
        # L4 / L5 / L6 triples — same forward-only semantics, same
        # composite-PK collapse. Additive per Rule 2; net +3
        # (123 → 126), 24 kinds remaining under the 150-kind ceiling
        # per Wave F Addendum 4. L-axis family count = 18 of 30 cap
        # (Addendum 4 §E).
        "entity_stitch_proposed",
        "entity_stitch_confirmed",
        "entity_stitch_rejected",
        # L1 Sub-wave A (2026-06-08). Three lake-side source-candidate
        # triage kinds back the projection_source_candidates fold:
        # proposed (by the L1 lake loop that runs three acquisition
        # strategies — kpi_gap / channel_mention / complementarity —
        # to surface candidate data sources for admin triage) →
        # promoted / rejected (by admin operators; "promoted" replaces
        # the L3/L7/L4/L5/L6/L8 "confirmed" because L1 prequels the
        # existing source pipeline — see spec §1). ZERO cross-axis
        # chains in the L4→L3 / L6→L5 / L8→L5 sense — L1's inference
        # reads existing first-class platform projections
        # (projection_sources / projection_kpi_nodes /
        # projection_silver_conversations) via lightweight Reader
        # Protocols rather than peer lake-axis projections; cross-axis
        # chain count stays at 3. Structurally identical to the L3 /
        # L7 / L4 / L5 / L6 / L8 triples — same forward-only
        # semantics, same composite-PK collapse. Additive per Rule 2;
        # net +3 (126 → 129), 21 kinds remaining under the 150-kind
        # ceiling per Wave F Addendum 4. L-axis family count = 21 of
        # 30 cap (Addendum 4 §E).
        "source_candidate_proposed",
        "source_candidate_promoted",
        "source_candidate_rejected",
        # L2 Sub-wave A (2026-06-09). Three lake-side catalog-drift
        # detection kinds back the projection_catalog_drifts fold:
        # proposed (by the L2 lake loop that runs three strategies —
        # table_set / column_set / column_type — to detect structural
        # changes in external-catalog snapshots) → acknowledged /
        # rejected (by admin operators; "acknowledged" replaces
        # L3/L7/L4/L5/L6/L8 "confirmed" and L1 "promoted" because L2
        # is a no-op disposition record — no downstream pipeline
        # trigger, no cross-axis effect — see spec §1). ZERO new
        # cross-axis chains today (L2 reads catalog-mirror substrate
        # via a CatalogSnapshotReader Protocol in Sub-wave B);
        # cross-axis chain count stays at 3. Structurally identical
        # to the L3 / L7 / L4 / L5 / L6 / L8 / L1 triples — same
        # forward-only semantics, same composite-PK collapse.
        # Additive per Rule 2; net +3 (129 → 132), 18 kinds remaining
        # under the 150-kind ceiling per Wave F Addendum 4. L-axis
        # family count = 24 of 30 cap (Addendum 4 §E). **L2 is the
        # FINAL planned axis in this generation per spec §11.**
        "catalog_drift_proposed",
        "catalog_drift_acknowledged",
        "catalog_drift_rejected",
        # Catalog-mirror Wave 2 Sub-wave A (2026-06-10). Per-table
        # column-metadata substrate: one PEVR per discovered table per
        # snapshot, carrying tuple[CatalogColumnSpec, ...]. Folded into
        # projection_catalog_tables (v029) keyed by (company_id,
        # source_id, table_id, snapshot_hash). Unblocks L2 TableSet /
        # ColumnSet / ColumnType strategies + L8 SchemaShape — they
        # were honest-empty-upstream until per-table catalog richness
        # landed. Substrate kind, NOT a lake-axis triple — L-axis
        # family count stays at 24 of 30 cap. Additive per Rule 2;
        # net +1 (132 → 133), 17 kinds remaining under the 150 ceiling.
        "catalog_table_imported",
    }
    assert set(KIND_REGISTRY.keys()) == expected, (
        f"missing: {expected - set(KIND_REGISTRY.keys())}, "
        f"extra: {set(KIND_REGISTRY.keys()) - expected}"
    )
