"""L3 contract: every entry-kind Pydantic model round-trips cleanly.

This test guards the boundary between the Python ledger and any
downstream consumer (dashboard TS, replay tool, governance projections).
The contract: build → model_dump(mode="json") → re-parse must be an
identity for every of the registered ``EntryPayload`` subclasses.

Why we test this: Pydantic v2 silently drops fields that don't match
the model when ``extra="forbid"`` is on the consumer side. Every wire
shape needs to round-trip OR we lose data on the boundary.

Special focus: ``ChatReceivedPayload`` — the very first event in the
PEVR chain that the channel-adapter writes; if its schema drifts, the
whole replay determinism gate breaks.

E3 update: the registry has grown well past the original 20 kinds
(Block A added Person/Identity/Install + 4 Role kinds; Block B added
medallion lake; Block F added data products + notebooks). The test
now asserts ``len(ALL_KINDS) >= 20`` (a non-shrinking floor) and
forces a sample for every kind in the registry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    AgentEventDeliveredPayload,
    AgentGrantPayload,
    AgentMetadataUpdatedPayload,
    AgentQueryPayload,
    AgentRegisteredPayload,
    AgentSubscriptionCreatedPayload,
    AgentSubscriptionRevokedPayload,
    BadPatternProposedPayload,
    CatalogDriftAcknowledgedPayload,
    CatalogDriftProposedPayload,
    CatalogDriftRejectedPayload,
    ChatReceivedPayload,
    ChatReplyExecutedPayload,
    ChatReplyProposedPayload,
    ChatReplyResolvedPayload,
    ChatReplyVerifiedPayload,
    ChatSentPayload,
    ClockTickPayload,
    ColumnClassificationConfirmedPayload,
    ColumnClassificationProposedPayload,
    ColumnClassificationRejectedPayload,
    CredentialPayload,
    DomainPackSelectedPayload,
    EntityStitchConfirmedPayload,
    EntityStitchProposedPayload,
    EntityStitchRejectedPayload,
    LineageEdgeConfirmedPayload,
    LineageEdgeProposedPayload,
    LineageEdgeRejectedPayload,
    PersonInvitedPayload,
    PhenomenonGapDetectedPayload,
    QualityCheckConfirmedPayload,
    QualityCheckProposedPayload,
    QualityCheckRejectedPayload,
    SchemaImpactConfirmedPayload,
    SchemaImpactProposedPayload,
    SchemaImpactRejectedPayload,
    SemanticTypeConfirmedPayload,
    SemanticTypeProposedPayload,
    SemanticTypeRejectedPayload,
    SourceCandidatePromotedPayload,
    SourceCandidateProposedPayload,
    SourceCandidateRejectedPayload,
    TenantEngineRegisteredPayload,
    ReactivityConfirmedPayload,
    ReactivityDisabledPayload,
    ReactivityFiredPayload,
    ReactivityProposedPayload,
    ResourceConversationProposedPayload,
    ResourceConversationRepliedPayload,
    ResourceConversationResolvedPayload,
    ConceptConfirmedPayload,
    ConceptProposedPayload,
    ConversationSyncPayload,
    DataProductArchivedPayload,
    DataProductConsumedPayload,
    DataProductGeneratedPayload,
    DataProductProposedPayload,
    DataProductRecommendedPayload,
    DecisionRecordedPayload,
    DomainRoleAssignedPayload,
    EntryPayload,
    ExecutePayload,
    ExperimentLessonPayload,
    ExperimentProposedPayload,
    ExperimentResolvedPayload,
    ExperimentRunPayload,
    ExternalCatalogDriftDetectedPayload,
    ExternalCatalogImportedPayload,
    ExternalLineageImportedPayload,
    ExternalMetricImportedPayload,
    ExternalPolicyImportedPayload,
    GateFiredPayload,
    HeuristicExperimentPayload,
    IdentityLinkedPayload,
    IdentityUnlinkedPayload,
    InferenceCacheRefreshedPayload,
    InferenceServedPayload,
    IngestLandedPayload,
    IngestProfiledPayload,
    InstallCompletedPayload,
    InstallRevokedPayload,
    KpiAnsweredPayload,
    KpiProposedPayload,
    LakeDiscoveryPayload,
    MCPCallReceivedPayload,
    MemoryWrittenPayload,
    MetricsKeepRatePublishedPayload,
    QueryCorrectionSuggestedPayload,
    QueryOutcomeRecordedPayload,
    QueryTemplatePromotedPayload,
    SemanticGapEscalatedPayload,
    SemanticGapProposedPayload,
    TenantQuotaConsumedPayload,
    SetupCompletedPayload,
    SetupModeChosenPayload,
    SetupStepAdvancedPayload,
    MetricObservedPayload,
    NotebookArchivedPayload,
    NotebookProposedPayload,
    NotebookPublishedPayload,
    NotebookRunPayload,
    PersonArchivedPayload,
    PersonConfirmedPayload,
    PersonProposedPayload,
    PersonRegisteredPayload,
    PolicyAppliedPayload,
    PositionAssignedPayload,
    PositionConfirmedPayload,
    PositionMetricAddedPayload,
    PositionProposedPayload,
    PositionQuestionPatternPayload,
    PositionRejectedPayload,
    ProcessMapProposedPayload,
    ProposePayload,
    RecurringQuestionPayload,
    ResolvePayload,
    ResourceRoleAssignedPayload,
    ResourceRoleProposedPayload,
    RoleAssignedPayload,
    RoleRevokedPayload,
    SourceBronzedPayload,
    SourceConfirmedPayload,
    SourceConnectedPayload,
    SourceGoldedPayload,
    SourceProfiledPayload,
    SourceProposedPayload,
    SourceSilveredPayload,
    SystemMapNodePayload,
    TenantSignupCompletedPayload,
    TenantSignupInitiatedPayload,
    TopicProposedPayload,
    VerifyPayload,
)


# ---------------------------------------------------------------------------
# Sample-payload factory — one canonical example per kind. Tests below
# round-trip each one through model_dump(mode="json") and re-parse.
# ---------------------------------------------------------------------------


def _samples() -> dict[str, EntryPayload]:
    src_id = uuid4()
    person_id = uuid4()
    domain_id = uuid4()
    install_id = uuid4()
    experiment_id = uuid4()
    data_product_id = uuid4()
    notebook_id = uuid4()
    run_id = uuid4()
    process_id = uuid4()
    decision_id = uuid4()
    question_id = uuid4()
    kpi_id = uuid4()
    gold_artifact_id = uuid4()
    tenant_id = uuid4()
    now = datetime.now(UTC)

    return {
        # --- Canonical (4) ----------------------------------------------
        "propose": ProposePayload(
            target_kind="source_proposed",
            ref_id=uuid4(),
            reason="contract test",
            proposed_by="contract-suite",
        ),
        "execute": ExecutePayload(
            propose_entry_id=uuid4(),
            tool="emit_source_proposed",
            args={"k": "v"},
            result_ref="r1",
        ),
        "verify": VerifyPayload(
            execute_entry_id=uuid4(),
            checks=[{"name": "shape_ok", "ok": True}],
            passed=True,
        ),
        "resolve": ResolvePayload(
            verify_entry_id=uuid4(),
            outcome="keep",
            rationale="ok",
        ),
        # --- Source lifecycle (4) ---------------------------------------
        "source_proposed": SourceProposedPayload(
            source_id=src_id,
            source_kind="file",
            uri="s3://x/y.csv",
            added_via_flow="drop_and_profile",
            suggested_domain="finance",
            suggested_classification="internal",
        ),
        "source_confirmed": SourceConfirmedPayload(
            source_id=src_id,
            confirmed_by_person=uuid4(),
            domain_id=domain_id,
            classification="internal",
        ),
        "source_connected": SourceConnectedPayload(
            source_id=src_id,
            connection_ref="conn-1",
            connected_at=now,
        ),
        "source_profiled": SourceProfiledPayload(
            source_id=src_id,
            row_count=100,
            column_count=8,
            schema_hash="deadbeef",
            profile_ref="prof-1",
        ),
        # --- Ingest (2) -------------------------------------------------
        "ingest_landed": IngestLandedPayload(
            source_id=src_id,
            object_uri="s3://x/y.csv",
            bytes=12345,
            row_count=100,
        ),
        "ingest_profiled": IngestProfiledPayload(
            source_id=src_id,
            profile_ref="prof-1",
            columns=[{"name": "id", "dtype": "int"}],
        ),
        # --- Memory + concept (3) ---------------------------------------
        "memory_written": MemoryWrittenPayload(
            memory_id=uuid4(),
            content="annual=12mo",
            tags=["concept"],
        ),
        "concept_proposed": ConceptProposedPayload(
            concept_id=uuid4(),
            name="MRR",
            definition="monthly recurring revenue",
            proposed_by="kpi-loop",
        ),
        "concept_confirmed": ConceptConfirmedPayload(
            concept_id=uuid4(),
            confirmed_by_person=uuid4(),
        ),
        # --- Chat (2) ---------------------------------------------------
        "chat_received": ChatReceivedPayload(
            channel_id="C0B06MCSLQ1",
            message_id="1777152782.692639",
            sender_person=uuid4(),
            text="@worm what's churn?",
            classification="internal",
        ),
        "chat_sent": ChatSentPayload(
            channel_id="C0B06MCSLQ1",
            message_id="1777152800.000001",
            text="Churn last month was 3.2%",
            in_reply_to="1777152782.692639",
            attribution={"sources": []},
            speech_act="answer",
        ),
        # --- Conversation lineage (1) -----------------------------------
        # Lineage entry for a bulk historical-message import (WhatsApp
        # reconnect, Slack initial connect, channel join). Per-message
        # chat_received entries from the same session reference this
        # via history_sync_id. Added 2026-05-05 (KIND_REGISTRY 82 → 83;
        # see Doctrine Addendum 3).
        "conversation_sync": ConversationSyncPayload(
            sync_id=uuid4(),
            platform="whatsapp",
            install_id="baseworm-test",
            channels=["5511999999999@s.whatsapp.net"],
            trigger="reconnect",
            started_at=now,
            completed_at=now,
            message_count=42,
            earliest_ts=now,
            latest_ts=now,
            status="completed",
        ),
        # --- Gate / KPI / heuristic / policy / inference (5) -------------
        "gate_fired": GateFiredPayload(
            gate="interjection",
            outcome="blocked",
            subject_ref="C0B06MCSLQ1",
            reason="budget 3 exhausted",
        ),
        "kpi_answered": KpiAnsweredPayload(
            question="what's churn?",
            answer="3.2%",
            sql_ref="kpi-1",
            answer_hash="abc123",
            sources=[uuid4()],
        ),
        "heuristic_experiment": HeuristicExperimentPayload(
            experiment_id=uuid4(),
            metric="reply_helpfulness",
            before="0.62",
            after="0.71",
            kept=True,
        ),
        "policy_applied": PolicyAppliedPayload(
            policy_id=uuid4(),
            applied_to_ref="resource:abc",
            outcome="masked",
        ),
        "inference_served": InferenceServedPayload(
            request_id=uuid4(),
            served_by="kimi",
            is_fallback=False,
            cache_key="cache-1",
            latency_ms=250,
        ),
        # --- Medallion lake (5) -----------------------------------------
        "source_bronzed": SourceBronzedPayload(
            source_id=src_id,
            byte_count=4096,
            row_count=20,
            col_count=6,
            schema_hash="a8989ece",
            mime="text/csv",
            raw_uri="file:///tmp/sales-q3.csv",
            profiled_at=now,
        ),
        "source_silvered": SourceSilveredPayload(
            source_id=src_id,
            inferred_columns=[
                {"name": "region", "dtype": "string", "nullable": False}
            ],
            join_candidates=[],
            silvered_at=now,
        ),
        "source_golded": SourceGoldedPayload(
            source_id=src_id,
            gold_artifact_id=gold_artifact_id,
            artifact_kind="kpi",
            value={"q3_net": 549963},
            computed_at=now,
        ),
        "kpi_proposed": KpiProposedPayload(
            kpi_id=kpi_id,
            label="Q3 net revenue",
            formula="SUM(net)",
            source_ids=[src_id],
            unit="USD",
            owner_position="cfo",
            proposed_at=now,
        ),
        "lake_discovered": LakeDiscoveryPayload(
            lake_kind="snowflake",
            root_uri="snowflake://prod/warehouse",
            tables_seen=42,
            sources_proposed=3,
            classified_at=now,
        ),
        # --- Process retrieval (4) --------------------------------------
        "decision_recorded": DecisionRecordedPayload(
            decision_id=decision_id,
            decision_text="Push the Q3 close to Friday",
            decision_at=now,
            channel_id="C_FINANCE",
            decided_by_persons=[person_id],
            evidence_message_ids=["1777152782.692639"],
            confidence=0.85,
        ),
        "process_map_proposed": ProcessMapProposedPayload(
            process_id=process_id,
            process_name="Q3 close",
            steps=[
                {
                    "order": 1,
                    "actor": "bob",
                    "action": "export rollup",
                    "source_message_id": "m1",
                }
            ],
            domain="finance",
            confidence=0.9,
        ),
        "system_map_node": SystemMapNodePayload(
            node_kind="person",
            node_id=str(person_id),
            edges=[
                {"kind": "asks", "target_id": "C_FINANCE", "weight": 0.7}
            ],
        ),
        "recurring_question": RecurringQuestionPayload(
            question_id=question_id,
            normalized_question="what's q3 net revenue",
            asked_by_persons=[person_id],
            occurrences=4,
            first_seen_at=now,
            last_seen_at=now,
            suggested_automation=None,
        ),
        # --- Step 5 user/position/autoresearch (8) -----------------------
        "person_registered": PersonRegisteredPayload(
            person_id=person_id,
            name="Carol Reyes",
            email="carol@baseworm.test",
            role="admin",
            registered_at=now,
        ),
        "position_assigned": PositionAssignedPayload(
            person_id=person_id,
            position="cfo",
            assigned_by_person_id=None,
            at=now,
        ),
        "position_metric_added": PositionMetricAddedPayload(
            position="cfo",
            metric_id="forecast_accuracy_q3",
            weight=0.8,
            by_person_id=None,
        ),
        "position_question_pattern": PositionQuestionPatternPayload(
            position="cfo",
            pattern="what's our.*revenue",
            frequency_observed=5,
            last_seen_at=now,
        ),
        "experiment_proposed": ExperimentProposedPayload(
            experiment_id=experiment_id,
            for_person_id=person_id,
            position="cfo",
            headline_metric="forecast_accuracy_q3",
            proposed_change={"cache_ttl_s": 300},
            expected_delta=-0.4,
            proposed_at=now,
        ),
        "experiment_run": ExperimentRunPayload(
            experiment_id=experiment_id,
            started_at=now,
            finished_at=now,
            log={"observations": []},
        ),
        "experiment_resolved": ExperimentResolvedPayload(
            experiment_id=experiment_id,
            outcome="keep",
            observed_delta=-0.38,
            rationale="cache hit ratio 41% on Q3 net query",
            resolved_at=now,
        ),
        "metric_observed": MetricObservedPayload(
            metric_id="forecast_accuracy_q3",
            position="cfo",
            value=0.96,
            observed_at=now,
            source_id=None,
        ),
        # --- Identity (5) -----------------------------------------------
        "person_proposed": PersonProposedPayload(
            person_id=person_id,
            tenant_id=uuid4(),
            name="Bob Martin",
            email="bob@baseworm.test",
            platform="slack",
            platform_user_id="U0BOB",
            proposed_by="worm",
            position=None,
        ),
        "person_confirmed": PersonConfirmedPayload(
            person_id=person_id,
            confirmed_by=uuid4(),
        ),
        "person_archived": PersonArchivedPayload(
            person_id=person_id,
            archived_by=uuid4(),
            reason="merged into another Person",
        ),
        "identity_linked": IdentityLinkedPayload(
            person_id=person_id,
            platform="discord",
            platform_user_id="bob#1234",
            linked_by=uuid4(),
        ),
        "identity_unlinked": IdentityUnlinkedPayload(
            person_id=person_id,
            platform="discord",
            platform_user_id="bob#1234",
            unlinked_by=uuid4(),
        ),
        # --- Install (2) ------------------------------------------------
        "install_completed": InstallCompletedPayload(
            install_id=install_id,
            tenant_id=uuid4(),
            platform="slack",
            installer_person_id=person_id,
            oauth_grant_ref="kms://wormbase/install/abc123",
            scopes=["chat:write", "files:read"],
            bot_user_id="U0WORM",
        ),
        "install_revoked": InstallRevokedPayload(
            install_id=install_id,
            revoked_by=uuid4(),
        ),
        # --- Roles — three facets (4) -----------------------------------
        "role_assigned": RoleAssignedPayload(
            person_id=person_id,
            role="admin",
            granted_by=uuid4(),
        ),
        "role_revoked": RoleRevokedPayload(
            person_id=person_id,
            role="admin",
            revoked_by=uuid4(),
        ),
        "domain_role_assigned": DomainRoleAssignedPayload(
            person_id=person_id,
            domain_id=domain_id,
            role="owner",
            granted_by=uuid4(),
        ),
        "resource_role_assigned": ResourceRoleAssignedPayload(
            person_id=person_id,
            resource_id=src_id,
            resource_type="source",
            role="maintainer",
            granted_by=uuid4(),
        ),
        # --- Data products + notebooks (Block F) (8) --------------------
        # P10 — process_map data products are emitted by
        # RecurringQuestionProcessMapperReactivity, carrying the
        # nodes/edges/window payload in ``parameters``. The contract
        # is the same DataProductProposedPayload schema; the only new
        # bit is that ``kind="process_map"`` is now valid.
        "data_product_proposed": DataProductProposedPayload(
            data_product_id=data_product_id,
            name="Process map · trailing 14d · 2 edge(s)",
            kind="process_map",
            requested_by_person_id=person_id,
            sources_required=[],
            domain_id=domain_id,
            parameters={
                "nodes": [
                    {
                        "actor_person_id": str(person_id),
                        "role_in_map": "asker",
                    },
                ],
                "edges": [
                    {
                        "from": str(person_id),
                        "to": str(uuid4()),
                        "topic": "churn_rate",
                        "frequency": 3,
                        "first_seen": now.isoformat(),
                        "last_seen": now.isoformat(),
                    },
                ],
                "window_start": now.isoformat(),
                "window_end": now.isoformat(),
                "confidence": 0.5,
            },
            prompted_by_message_id=None,
        ),
        "data_product_generated": DataProductGeneratedPayload(
            data_product_id=data_product_id,
            contents_uri="s3://wormbase/dp/abc/run-1.html",
            content_hash="7d4e8b",
            kind="report",
            source_hashes=["a8989ece"],
            generated_by="worm",
            duration_ms=1234,
        ),
        "data_product_consumed": DataProductConsumedPayload(
            data_product_id=data_product_id,
            consumed_by_person_id=person_id,
            surface="dashboard",
            channel=None,
        ),
        "data_product_archived": DataProductArchivedPayload(
            data_product_id=data_product_id,
            archived_by=uuid4(),
            reason="superseded by Q4 board breakdown",
        ),
        "notebook_proposed": NotebookProposedPayload(
            notebook_id=notebook_id,
            name="Q3 net revenue notebook",
            cells=[{"kind": "code", "source": "df.head()"}],
            kernel="python_pandas",
            proposed_by_person_id=person_id,
            domain_id=domain_id,
        ),
        "notebook_run": NotebookRunPayload(
            notebook_id=notebook_id,
            run_id=run_id,
            cell_outputs=[{"stdout": "ok"}],
            cell_hashes=["c0ffee"],
            duration_ms=2000,
            kernel_state_hash="state1",
            status="ok",
            run_by="worm",
        ),
        "notebook_published": NotebookPublishedPayload(
            notebook_id=notebook_id,
            run_id=run_id,
            owner_person_id=person_id,
            domain_id=domain_id,
            version="v1",
            published_by=uuid4(),
        ),
        "notebook_archived": NotebookArchivedPayload(
            notebook_id=notebook_id,
            archived_by=uuid4(),
            reason="duplicate of Q4 notebook",
        ),
        # Block G — setup mode + progress (PRD §17).
        "setup_mode_chosen": SetupModeChosenPayload(
            tenant_id=tenant_id,
            mode="wizard",
            chosen_by_person_id=person_id,
        ),
        "setup_completed": SetupCompletedPayload(
            tenant_id=tenant_id,
            completed_at=datetime(2026, 4, 26, 14, 30, 0, tzinfo=UTC),
        ),
        "setup_step_advanced": SetupStepAdvancedPayload(
            tenant_id=tenant_id,
            step_id="domain_pack",
            advanced_by_person_id=person_id,
        ),
        # Block J — MCP call audit (full feature surface).
        "mcp_call_received": MCPCallReceivedPayload(
            mcp_call_id=uuid4(),
            tenant_id=tenant_id,
            caller_person_id=person_id,
            tool_name="query_ledger",
            args_hash="a8989ece",
            client_ua="python-httpx/0.28.1",
            started_at=now,
            outcome="ok",
            latency_ms=4,
        ),
        # Wave 5 — reactivity lifecycle + statement-to-owner +
        # phenomenon-gap detectors. The Reactivity Protocol turns
        # hand-coded reactivity loops into proposable, confirmable,
        # audited artifacts; the resource-conversation lifecycle is
        # the first concrete Reactivity (Statement-to-Owner); the
        # phenomenon_gap_detected entry is a single polymorphic kind
        # for the four gap detectors (kpi/domain/process/reactivity).
        "reactivity_proposed": ReactivityProposedPayload(
            reactivity_id="statement_to_owner",
            name="Statement to Owner",
            description="DM the resource owner when a chat statement matches a topic they own.",
            scope="domain",
            predicate_spec={"kind": "And", "children": [
                {"kind": "EntryKind", "value": "chat_received"},
                {"kind": "HasTopic"},
                {"kind": "HasOwner"},
                {"kind": "SpeakerNotOwner"},
            ]},
            condition_spec={"kind": "And", "children": [
                {"kind": "DailyBudget", "per_owner": 3, "per_domain": 10, "per_tenant": 50},
                {"kind": "NotRecentlyFired", "novelty_key": "topic:owner", "hours": 4.0},
                {"kind": "DomainEnabled"},
            ]},
            action_spec={"kind": "send_resource_conversation_dm"},
            proposed_by="worm",
        ),
        "reactivity_confirmed": ReactivityConfirmedPayload(
            reactivity_id="statement_to_owner",
            confirmed_by=str(person_id),
        ),
        "reactivity_disabled": ReactivityDisabledPayload(
            reactivity_id="statement_to_owner",
            disabled_by=str(person_id),
            reason="too noisy on the #revenue channel; revisit after Q3",
        ),
        "reactivity_fired": ReactivityFiredPayload(
            reactivity_id="statement_to_owner",
            source_seq=42,
            novelty_key=f"retention:{person_id}",
            action_seqs=[43, 44, 45, 46],
            budget_used={"per_owner": 1, "per_domain": 1, "per_tenant": 1},
        ),
        "resource_conversation_proposed": ResourceConversationProposedPayload(
            conversation_id=uuid4(),
            topic={
                "kind": "domain",
                "id": str(domain_id),
                "label": "retention",
                "confidence": 0.82,
            },
            owner_id=person_id,
            resources={
                "kpis": [{"id": str(uuid4()), "label": "churn_rate"}],
                "sources": [{"id": str(src_id), "kind": "stripe"}],
                "decisions": [],
                "processes": [],
                "data_products": [],
            },
            statement_seq=41,
            channel="slack:D012345",
        ),
        "resource_conversation_replied": ResourceConversationRepliedPayload(
            conversation_id=uuid4(),
            replier_id=person_id,
            content="good catch — let's pull cohort data and ping product. promoting to a decision.",
            seq=47,
        ),
        "resource_conversation_resolved": ResourceConversationResolvedPayload(
            conversation_id=uuid4(),
            outcome="decision",
            resolved_by=person_id,
            decision_seq=48,
        ),
        # Demo-day P1 — composite_score / per-scope keep-rate publication.
        "metrics_keep_rate_published": MetricsKeepRatePublishedPayload(
            scope="company",
            day="2026-04-28",
            kept=7,
            total=10,
            ratio=0.7,
            published_by="worm",
            published_at=now,
        ),
        # Demo-day P9 — autoresearch learn step lesson.
        "experiment_lesson": ExperimentLessonPayload(
            prior_keep_id=experiment_id,
            scope="person",
            lesson_text=(
                "For position 'cfo' moving 'revenue', a kpi_definition on "
                "'revenue_forecast' with predicate "
                "'exclude_promo_signups_from_cohort' was kept: observed "
                "+0.0360 hit ≥85% of expected +0.0400. The predicate was "
                "novel vs 1 adjacent discards. Reweight future proposals on "
                "this scope toward (kpi_definition, revenue_forecast) when "
                "targeting 'revenue'."
            ),
            lesson_features={
                "metric": "revenue",
                "position": "cfo",
                "change_kind": "kpi_definition",
                "change_target": "revenue_forecast",
                "change_predicate": "exclude_promo_signups_from_cohort",
                "delta_label": "hit_expectation",
                "observed_delta": "+0.0360",
                "expected_delta": "+0.0400",
                "adjacent_discard_count": "1",
                "predicate_was_novel_vs_discards": "true",
            },
            applied_to_proposer="autoresearch_loop",
            applied_at=42,
            proposed_by="autoresearch_loop",
            extracted_at=now,
        ),
        "phenomenon_gap_detected": PhenomenonGapDetectedPayload(
            kind="kpi",
            referenced_in_seq=49,
            suggested_proposal={
                "label": "nps",
                "domain_id": str(domain_id),
                "source_statement": "we should track NPS",
            },
            confidence=0.9,
            novelty_key="kpi:nps",
        ),
        # --- Wave B chat-reply PEVR cycle (4) ---------------------------
        # The worm-side outbound reply lifecycle: propose intent → execute
        # ChannelAdapter.send → verify outcome → resolve keep/discard.
        "chat_reply_proposed": ChatReplyProposedPayload(
            chat_reply_id=uuid4(),
            channel_id="C0B06MCSLQ1",
            speech_act="answer",
            text="Churn last month was 3.2%",
            in_reply_to="1777152782.692639",
            domain_id=domain_id,
        ),
        "chat_reply_executed": ChatReplyExecutedPayload(
            chat_reply_id=uuid4(),
            channel_id="C0B06MCSLQ1",
            platform="slack",
            adapter_call_started_at=now,
            adapter_call_ended_at=now,
        ),
        "chat_reply_verified": ChatReplyVerifiedPayload(
            chat_reply_id=uuid4(),
            passed=True,
            message_ref="1777152800.000001",
            error=None,
        ),
        "chat_reply_resolved": ChatReplyResolvedPayload(
            chat_reply_id=uuid4(),
            outcome="keep",
            rationale="reply landed and observed in channel",
        ),
        # --- Wave B.5 + 2C position propose / confirm / reject (3) ------
        # PositionInferenceReactivity propose-step + admin confirm/reject
        # surface at /people/proposals.
        "position_proposed": PositionProposedPayload(
            person_id=person_id,
            position="senior_engineer",
            confidence=0.72,
            signals=("commit_msg", "design_doc"),
        ),
        "position_confirmed": PositionConfirmedPayload(
            person_id=person_id,
            position="senior_engineer",
            confirmed_by=uuid4(),
        ),
        "position_rejected": PositionRejectedPayload(
            person_id=person_id,
            position="senior_engineer",
            rejected_by=uuid4(),
            reason="joined as analyst, not engineer",
        ),
        # --- Wave B.5 G.5 resource-role propose-step (1) ---------------
        "resource_role_proposed": ResourceRoleProposedPayload(
            person_id=person_id,
            resource_id=src_id,
            role="maintainer",
            confidence=0.68,
            signals=("chat_mention", "data_product_consumed"),
            proposed_by=uuid4(),
        ),
        # --- Wave 1B tenant signup (2) ----------------------------------
        # Slack OAuth + email magic-link signup lifecycle entries.
        "tenant_signup_initiated": TenantSignupInitiatedPayload(
            tenant_id=tenant_id,
            slug="acme-co",
            display_name="Acme Co",
            signup_source="slack_oauth",
            signup_email="installer@acme.test",
            pending_token_hash="a" * 64,
        ),
        "tenant_signup_completed": TenantSignupCompletedPayload(
            tenant_id=tenant_id,
            signup_source="slack_oauth",
            assigned_tenant_slug="acme-co",
            signup_email="installer@acme.test",
        ),
        # --- Wave 1A inference cache provenance (1) ---------------------
        "inference_cache_refreshed": InferenceCacheRefreshedPayload(
            cache_path="/var/wormbase/inference_cache.sqlite",
            entries_invalidated=128,
            reason="rotated cache for fresh demo run after model upgrade",
            refreshed_by="ops",
        ),
        # --- Wave 2B silver-tier topic synthesis (1) --------------------
        "topic_proposed": TopicProposedPayload(
            topic_id=uuid4(),
            label="churn discussion",
            cluster_signature="how is churn trending this quarter",
            cluster_size=4,
            member_message_ids=[
                "1777152782.692639",
                "1777152800.000001",
                "1777152801.000002",
                "1777152802.000003",
            ],
            first_seen_at=now,
            last_seen_at=now,
            confidence=0.68,
            served_by="gemma",
        ),
        # --- W2 agent-gateway (7) ---------------------------------------
        # Agent identity, grant, query, subscription + delivery lifecycle.
        # Backfilled 2026-05-13 as part of the Post-final-wave debt sweep.
        "agent_registered": AgentRegisteredPayload(
            agent_id="agent-claude-cli",
            external_provider="claude",
            display_name="Claude CLI",
            registered_by="installer-person",
        ),
        "agent_grant": AgentGrantPayload(
            agent_id="agent-claude-cli",
            grant_kind="domain.read",
            grant_target="finance",
            status="active",
            granted_by="installer-person",
            budget_remaining_usd="25.00",
        ),
        "credential": CredentialPayload(
            agent_id="agent-claude-cli",
            credential_kind="data",
            target="postgres://finance",
            status="active",
            ttl_expires_at="2026-05-20T00:00:00+00:00",
            issued_by="broker",
        ),
        "agent_query": AgentQueryPayload(
            agent_id="agent-claude-cli",
            mcp_tool="query_kpi",
            args={"kpi_id": "q3_net_revenue"},
            route_mode="broker",
            phase="execute",
            row_count=1,
            cost_usd="0.0004",
            latency_ms=42,
            caused_by=None,
        ),
        "agent_subscription_created": AgentSubscriptionCreatedPayload(
            subscription_id="sub-001",
            agent_id="agent-claude-cli",
            filter={"entry_kind": "kpi_answered"},
            transport="webhook",
            webhook_url="https://example.test/hook",
            webhook_secret_ref="kms://wormbase/hook/sub-001",
            description="claude listens for kpi answers",
        ),
        "agent_subscription_revoked": AgentSubscriptionRevokedPayload(
            subscription_id="sub-001",
            reason="agent_request",
        ),
        "agent_event_delivered": AgentEventDeliveredPayload(
            subscription_id="sub-001",
            triggering_entry_seq=137,
            triggering_entry_kind="kpi_answered",
            transport_used="webhook",
            delivery_status="delivered",
            duration_ms=180,
            error=None,
        ),
        # --- W2 agent-gateway metadata edit (Final Wave 3) --------------
        "agent_metadata_updated": AgentMetadataUpdatedPayload(
            agent_id="agent-claude-cli",
            display_name="Claude CLI (renamed)",
            description="Updated display name for clarity",
            updated_by_person_id="00000000-0000-0000-0000-000000000001",
            reason="rename per admin request",
        ),
        # --- W3 lake catalog / lineage / metric / policy import (5) -----
        "external_catalog_imported": ExternalCatalogImportedPayload(
            source_kind="snowflake",
            source_id="snowflake-prod",
            domain_id=str(domain_id),
            snapshot_hash="cafebabe",
            table_count=128,
            edge_count=412,
            metric_count=24,
            import_mode="initial",
        ),
        "external_catalog_drift_detected": ExternalCatalogDriftDetectedPayload(
            source_id="snowflake-prod",
            old_hash="cafebabe",
            new_hash="deadbeef",
            added_table_ids=("table-101",),
            removed_table_ids=(),
            changed_table_ids=("table-44",),
        ),
        "external_lineage_imported": ExternalLineageImportedPayload(
            source_id="snowflake-prod",
            edges=(
                ("table-a", "table-b"),
                ("table-b", "table-c"),
            ),
        ),
        "external_metric_imported": ExternalMetricImportedPayload(
            source_id="snowflake-prod",
            name="q3_net_revenue",
            expression="SUM(net)",
            time_grain="quarter",
            dimensions=("region", "product"),
            description="Q3 net revenue rollup",
            domain_id=str(domain_id),
            promoted_from_gap_id=None,
            promoted_by=None,
        ),
        "external_policy_imported": ExternalPolicyImportedPayload(
            source_id="snowflake-prod",
            policy_fqn="finance.pii.email_mask",
            policy_kind="masking",
            body="MASK(email) WHEN role NOT IN ('admin')",
            applied_to=("table-customers",),
        ),
        # --- W3 query-improvement compounding loop (4) ------------------
        # query_outcome → bad_pattern OR query_template; query_correction
        # is the refinement step.
        "query_outcome_recorded": QueryOutcomeRecordedPayload(
            agent_query_id="agent-query-001",
            nl_question="what's our q3 net revenue?",
            final_query_spec={
                "kind": "select",
                "metric": "q3_net_revenue",
            },
            result_summary={"row_count": 1, "value": 549963},
            used=True,
            useful=True,
            user_correction=None,
            quality_score="0.91",
            embedding=None,
        ),
        "query_template_promoted": QueryTemplatePromotedPayload(
            domain_id=str(domain_id),
            nl_intent="ask for q3 net revenue",
            query_spec={
                "kind": "select",
                "metric": "q3_net_revenue",
            },
            promoted_from_outcome_ids=("outcome-001", "outcome-002"),
            quality_score="0.93",
        ),
        "query_correction_suggested": QueryCorrectionSuggestedPayload(
            original_query_id="agent-query-001",
            failure_kind="schema_mismatch",
            failure_detail="column 'net_revenue' not found; did you mean 'net'?",
            refined_query_spec={
                "kind": "select",
                "metric": "q3_net",
            },
        ),
        "bad_pattern_proposed": BadPatternProposedPayload(
            canonical_intent="ask for q3 net revenue via wrong column",
            failed_outcome_ids=("outcome-101", "outcome-102", "outcome-103"),
            failed_query_specs=[
                {"kind": "select", "metric": "net_revenue"},
            ],
            failure_count=3,
            suggested_avoidance="use 'net' not 'net_revenue' on finance.snowflake",
            domain_id=str(domain_id),
        ),
        # --- W3 semantic gap loop (2) -----------------------------------
        "semantic_gap_proposed": SemanticGapProposedPayload(
            agent_id="agent-claude-cli",
            nl_question="what's our NPS?",
            reason="no_match",
            proposed_metric_name="nps",
        ),
        "semantic_gap_escalated": SemanticGapEscalatedPayload(
            original_gap_id="gap-001",
            nl_question="what's our NPS?",
            reason="no_match",
            days_unresolved=14,
            proposed_metric_name="nps",
        ),
        # --- W3 data-product recommendation (1) -------------------------
        "data_product_recommended": DataProductRecommendedPayload(
            data_product_id=data_product_id,
            recommendation_score=87,
            consumer_agent_ids=("agent-claude-cli", "agent-openai-cli"),
            consumed_within_days=7,
        ),
        # --- v2.B periodic predicate clock tick (1) ---------------------
        "clock_tick": ClockTickPayload(
            tick_interval_s=300,
            sequence_number=42,
        ),
        # --- Final Wave 4 tenant quota consumption (1) ------------------
        "tenant_quota_consumed": TenantQuotaConsumedPayload(
            tenant_slug="acme-co",
            consumption_count=850,
            quota_limit=1000,
            quota_remaining=150,
            window_start_ts=now,
            window_end_ts=now,
            triggered_by="count_threshold",
        ),
        # --- Engine-per-tenant routing (1) ------------------------------
        "tenant_engine_registered": TenantEngineRegisteredPayload(
            tenant_slug="acme-co",
            engine_kind="isolated",
            engine_dsn_secret_ref="vault://wormbase/tenants/acme-co/engine_dsn",
            provisioned_at=now,
            migrated_from_shared_at=None,
            provisioned_by_person_id=str(person_id),
            region="us-west-2",
            hnsw_m=16,
            hnsw_ef_construction=64,
        ),
        # --- Onboarding Sub-wave C (2) ----------------------------------
        "person_invited": PersonInvitedPayload(
            invitee_email="alice@example.com",
            invitee_platform_id=None,
            invited_by_person_id=person_id,
            role_intent="member",
            notes="Co-admin invite from Tier 2",
        ),
        "domain_pack_selected": DomainPackSelectedPayload(
            pack_id="saas",
            pack_version="v1.0",
            selected_by_person_id=person_id,
            notes="Tier 2 pack pick",
        ),
        # --- L3 lake-side lineage-edge discovery loop (3) ---------------
        "lineage_edge_proposed": LineageEdgeProposedPayload(
            edge_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            src_table_id="snowflake.raw.orders",
            src_column="customer_id",
            tgt_table_id="snowflake.marts.customer_revenue",
            tgt_column="customer_id",
            confidence=0.87,
            strategy="sample_overlap",
            reasoning="Sample overlap 87% on customer_id between orders and customer_revenue",
            evidence={"sample_overlap_ratio": 0.87, "sampled_n": 1000},
        ),
        "lineage_edge_confirmed": LineageEdgeConfirmedPayload(
            edge_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            confirmed_by_person_id=str(person_id),
            notes="Confirmed via /lake/lineage",
        ),
        "lineage_edge_rejected": LineageEdgeRejectedPayload(
            edge_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            rejected_by_person_id=str(person_id),
            reason="false_positive",
            notes="Edges share name but unrelated entities",
        ),
        # --- L7 lake-side quality-check discovery loop (3) --------------
        "quality_check_proposed": QualityCheckProposedPayload(
            check_id="b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7",
            table_id="snowflake.raw.orders",
            column="order_id",
            check_kind="not_null",
            config={"min_non_null_ratio": 0.99},
            confidence=0.95,
            strategy="historical_stats",
            reasoning="order_id is 99.8% non-null over 90-day window",
            evidence={"non_null_ratio": 0.998, "sampled_n": 10000},
        ),
        "quality_check_confirmed": QualityCheckConfirmedPayload(
            check_id="b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7",
            confirmed_by_person_id=str(person_id),
            notes="Promoted via /lake/quality",
        ),
        "quality_check_rejected": QualityCheckRejectedPayload(
            check_id="b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7",
            rejected_by_person_id=str(person_id),
            reason="low_value",
            notes="Check duplicates dbt-side constraint",
        ),
        # --- L4 lake-side schema-impact discovery loop (3) --------------
        "schema_impact_proposed": SchemaImpactProposedPayload(
            impact_id="c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8",
            source_id="snowflake-prod",
            src_table="snowflake.raw.orders",
            src_column="legacy_id",
            change_kind="column_dropped",
            impact_kind="tgt_column_orphaned",
            tgt_table_id="snowflake.marts.legacy_orders",
            tgt_column="legacy_id",
            upstream_lineage_edge_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            confidence=0.92,
            strategy="lineage_edge",
            reasoning="Upstream column dropped; downstream mart still references it",
            evidence={"upstream_change_seq": 1234, "downstream_dbt_test": "not_null"},
        ),
        "schema_impact_confirmed": SchemaImpactConfirmedPayload(
            impact_id="c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8",
            confirmed_by_person_id=str(person_id),
            notes="Confirmed; downstream pipeline patched",
        ),
        "schema_impact_rejected": SchemaImpactRejectedPayload(
            impact_id="c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8",
            rejected_by_person_id=str(person_id),
            reason="already_handled",
            notes="Patched in last migration",
        ),
        # --- L5 lake-side semantic-type discovery loop (3) --------------
        "semantic_type_proposed": SemanticTypeProposedPayload(
            type_id="d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9",
            table_id="stripe.customers",
            column="email",
            semantic_type="email",
            confidence=0.99,
            strategy="value_pattern",
            reasoning="Regex match 99% of sampled values to RFC-5322 email shape",
            evidence={"match_count": 198, "sample_n": 200, "regex": "^[^@]+@[^@]+$"},
        ),
        "semantic_type_confirmed": SemanticTypeConfirmedPayload(
            type_id="d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9",
            confirmed_by_person_id=str(person_id),
            notes="Confirmed via /lake/semantic-types",
        ),
        "semantic_type_rejected": SemanticTypeRejectedPayload(
            type_id="d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9",
            rejected_by_person_id=str(person_id),
            reason="wrong_type",
            notes="Column is actually a user_name, not an email",
        ),
        # --- L6 lake-side column-classification discovery loop (3) ------
        "column_classification_proposed": ColumnClassificationProposedPayload(
            classification_id="e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            table_id="stripe.customers",
            column="ssn",
            classification_level="regulated",
            upstream_semantic_type_id="d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9",
            confidence=0.97,
            strategy="semantic_type",
            reasoning="L5 semantic_type=pii_ssn → regulated classification",
            evidence={"semantic_type": "pii_ssn", "regex_hit": True},
        ),
        "column_classification_confirmed": ColumnClassificationConfirmedPayload(
            classification_id="e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            confirmed_by_person_id=str(person_id),
            notes="Confirmed via /lake/column-classification",
        ),
        "column_classification_rejected": ColumnClassificationRejectedPayload(
            classification_id="e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            rejected_by_person_id=str(person_id),
            reason="wrong_level",
            notes="Public reference column, not regulated",
        ),
        # --- L8 lake-side entity-stitch discovery loop (3) --------------
        "entity_stitch_proposed": EntityStitchProposedPayload(
            stitch_id="f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1",
            src_source_id_a="stripe-prod",
            src_table_a="stripe.customers",
            src_column_a="email",
            src_source_id_b="salesforce-prod",
            src_table_b="salesforce.contacts",
            src_column_b="email",
            upstream_semantic_type_id="d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9",
            entity_kind="person",
            confidence=0.88,
            strategy="sample_overlap",
            reasoning="87% sample overlap on email between stripe.customers and salesforce.contacts",
            evidence={"sample_overlap_pct": 0.87, "endpoints_sampled": 200},
        ),
        "entity_stitch_confirmed": EntityStitchConfirmedPayload(
            stitch_id="f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1",
            confirmed_by_person_id=str(person_id),
            notes="Confirmed via /lake/entity-stitches",
        ),
        "entity_stitch_rejected": EntityStitchRejectedPayload(
            stitch_id="f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1",
            rejected_by_person_id=str(person_id),
            reason="wrong_pairing",
            notes="Two distinct entities, not a stitch candidate",
        ),
        # --- L1 lake-side source-candidate triage loop (3) --------------
        # Uses ``csv_local`` from the connector registry (default) so the
        # ``proposed_kind`` runtime-validator passes when the registry is
        # populated. If the registry hasn't been imported by the time the
        # contract test runs, the non-empty guard is the only check.
        "source_candidate_proposed": SourceCandidateProposedPayload(
            candidate_id="a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2",
            proposed_kind="csv_local",
            proposed_identifier="/data/incoming/customer_signups.csv",
            domain_id_hint=str(domain_id),
            strategy="kpi_gap",
            reasoning="Q3 KPI 'new_signups' missing source data — local CSV detected",
            confidence=0.78,
            evidence={"kpi_node_id": "kpi-new-signups-q3"},
        ),
        "source_candidate_promoted": SourceCandidatePromotedPayload(
            candidate_id="a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2",
            promoted_by_person_id=str(person_id),
            downstream_source_proposed_id="entry-7281",
            notes="Promoted via /lake/source-candidates",
        ),
        "source_candidate_rejected": SourceCandidateRejectedPayload(
            candidate_id="a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2",
            rejected_by_person_id=str(person_id),
            reason="duplicate",
            notes="Already connected via Stripe source",
        ),
        # --- L2 lake-side catalog-drift triage loop (3) -----------------
        # ``column_type_changed`` drift requires both ``before`` AND
        # ``after`` per model_post_init invariant; ``column`` REQUIRED for
        # column_* drift_kinds. See CatalogDriftProposedPayload docstring.
        "catalog_drift_proposed": CatalogDriftProposedPayload(
            drift_id="b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3",
            source_id="snowflake-prod",
            table_id="snowflake.raw.orders",
            column="amount",
            drift_kind="column_type_changed",
            before={"type": "DECIMAL(10,2)"},
            after={"type": "DECIMAL(18,4)"},
            strategy="column_type",
            reasoning="Column type widened to support fintech precision migration",
            confidence=0.95,
            evidence={"before_type": "DECIMAL(10,2)", "after_type": "DECIMAL(18,4)"},
        ),
        "catalog_drift_acknowledged": CatalogDriftAcknowledgedPayload(
            drift_id="b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3",
            acknowledged_by_person_id=str(person_id),
            notes="Acknowledged; planned migration",
        ),
        "catalog_drift_rejected": CatalogDriftRejectedPayload(
            drift_id="b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3",
            rejected_by_person_id=str(person_id),
            reason="expected_change",
            notes="Planned schema migration; ignore",
        ),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_kind_registry_floor_holds() -> None:
    """The registry must not shrink below the original 20-kind contract.

    Adding kinds is fine (and frequent — Block A added Person/Identity/
    Install + Role; Block B added medallion lake; Block F added data
    products + notebooks). Removing kinds breaks every downstream
    consumer (TS dashboard, replay tool) and is forbidden.
    """
    assert len(ALL_KINDS) >= 20, sorted(ALL_KINDS)
    assert len(KIND_REGISTRY) == len(ALL_KINDS)


def test_every_kind_has_a_sample_in_this_test() -> None:
    """Force ourselves to add a sample any time a new kind lands."""
    samples = _samples()
    missing = ALL_KINDS - set(samples)
    extra = set(samples) - ALL_KINDS
    assert not missing, f"new kinds without round-trip coverage: {sorted(missing)}"
    assert not extra, f"sample for unregistered kind: {sorted(extra)}"


@pytest.mark.parametrize("kind", sorted(ALL_KINDS))
def test_payload_roundtrips_through_json(kind: str) -> None:
    """Build → model_dump(mode='json') → re-parse must be field-stable."""
    sample = _samples()[kind]
    serialized = sample.model_dump(mode="json")
    cls = KIND_REGISTRY[kind]
    rebuilt = cls.model_validate(serialized)
    assert rebuilt == sample, f"{kind}: round-trip diverged"
    # All fields present (no silent drops).
    assert set(rebuilt.model_dump().keys()) == set(sample.model_dump().keys())


def test_chat_received_field_set_is_locked() -> None:
    """The TS dashboard relies on this exact field set — pin it down.

    Conversation provenance fields (``delivery_mode``, ``platform_ts``,
    ``history_sync_id``) landed 2026-05-05 alongside the WhatsApp first-
    level support and the ``conversation_sync`` lineage entry kind. The
    additions are back-compat: defaults preserve the pre-provenance
    parse path (legacy entries lacking the fields parse cleanly with
    defaults). See:
        docs/superpowers/specs/2026-05-05-conversation-provenance-architecture.md
    """
    expected = {
        "channel_id",
        "message_id",
        "sender_person",
        "text",
        "classification",
        # Conversation-provenance fields (additive; back-compat defaults)
        "delivery_mode",
        "platform_ts",
        "history_sync_id",
        # WhatsApp mention-fanout (Phase B1.1, 2026-05-06): the raw
        # `mentionedJid` list from Baileys is mirrored onto the
        # ChatReceivedPayload so MentionsWorm can resolve fanouts
        # symmetrically to Slack mentions. Additive; back-compat default.
        "mentioned_jids",
        # Platform-native sender id (raw, pre-hash). Slack U… or WhatsApp
        # jid; distinct from sender_person (UUIDv5 hash). Read by
        # WhatsAppOrganicDiscoveryReactivity to fire person_proposed on
        # previously-unseen jids — without this field the discovery
        # never fires. Added 2026-05-07 morning post-wire-fix when the
        # B2 schema mismatch surfaced live. Additive; back-compat default.
        "platform_user_id",
    }
    actual = set(ChatReceivedPayload.model_fields.keys())
    assert actual == expected, (
        f"ChatReceivedPayload field set drifted: "
        f"missing={expected - actual} added={actual - expected}"
    )
