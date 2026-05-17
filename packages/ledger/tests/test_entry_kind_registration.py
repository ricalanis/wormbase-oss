"""Contract tests pinning Wave B.5 (G.3) entry-kind registration.

Two new payload classes land per Doctrine Addendum 2 §E:

* `PositionProposedPayload` (kind ``position_proposed``) — payload for
  ``emit_position_proposed`` written by ``PositionInferenceReactivity``
  (G.4) when chat-signal scoring crosses threshold.
* `ResourceRoleProposedPayload` (kind ``resource_role_proposed``) —
  payload for ``emit_resource_role_proposed`` written by
  ``ResourceOwnershipReactivity`` (G.5) when chatter +
  data-product-consumption signals cross threshold for a
  (person, resource) pair.

These tests pin:

* Both classes are registered in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Construction with valid args and rejection of extras (Pydantic
  ``extra='forbid'``).
* Round-trip via ``model_dump`` → ``model_validate`` byte-equivalently.
* The post-Wave-B.5 registry size is 76 — verifying we are still well
  under the Rule 5 threshold (raised to 100 in Doctrine Addendum 2 §A).
"""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E

PERSON_ID = UUID("0190a0a0-0000-7000-8000-0000000000c1")
RESOURCE_ID = UUID("0190a0a0-0000-7000-8000-0000000000c2")
WORM_PERSON_ID = UUID("0190a0a0-0000-7000-8000-0000000000c3")


def test_position_proposed_kind_registered() -> None:
    assert "position_proposed" in E.KIND_REGISTRY
    assert E.KIND_REGISTRY["position_proposed"] is E.PositionProposedPayload


def test_resource_role_proposed_kind_registered() -> None:
    assert "resource_role_proposed" in E.KIND_REGISTRY
    assert (
        E.KIND_REGISTRY["resource_role_proposed"]
        is E.ResourceRoleProposedPayload
    )


def test_position_proposed_constructs() -> None:
    p = E.PositionProposedPayload(
        person_id=PERSON_ID,
        position="senior_engineer",
        confidence=0.7,
        signals=("commit_msg", "design_doc"),
    )
    assert p.person_id == PERSON_ID
    assert p.position == "senior_engineer"
    assert p.confidence == 0.7
    assert p.signals == ("commit_msg", "design_doc")
    assert p.kind == "position_proposed"


def test_position_proposed_signals_default_empty() -> None:
    p = E.PositionProposedPayload(
        person_id=PERSON_ID,
        position="data_analyst",
        confidence=0.55,
    )
    assert p.signals == ()


def test_position_proposed_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        E.PositionProposedPayload(
            person_id=PERSON_ID,
            position="senior_engineer",
            confidence=0.6,
            signals=(),
            not_allowed=True,  # type: ignore[call-arg]
        )


def test_position_proposed_rejects_out_of_range_confidence() -> None:
    # confidence is a probability — bounded [0.0, 1.0].
    with pytest.raises(ValidationError):
        E.PositionProposedPayload(
            person_id=PERSON_ID,
            position="senior_engineer",
            confidence=1.5,
        )
    with pytest.raises(ValidationError):
        E.PositionProposedPayload(
            person_id=PERSON_ID,
            position="senior_engineer",
            confidence=-0.1,
        )


def test_position_proposed_roundtrips() -> None:
    p = E.PositionProposedPayload(
        person_id=PERSON_ID,
        position="senior_engineer",
        confidence=0.72,
        signals=("commit_msg",),
    )
    again = E.PositionProposedPayload.model_validate(p.model_dump())
    assert again == p


def test_resource_role_proposed_constructs() -> None:
    rr = E.ResourceRoleProposedPayload(
        person_id=PERSON_ID,
        resource_id=RESOURCE_ID,
        role="maintainer",
        confidence=0.8,
        signals=("chat_mention", "data_product_consumed"),
        proposed_by=WORM_PERSON_ID,
    )
    assert rr.person_id == PERSON_ID
    assert rr.resource_id == RESOURCE_ID
    assert rr.role == "maintainer"
    assert rr.confidence == 0.8
    assert rr.signals == ("chat_mention", "data_product_consumed")
    assert rr.proposed_by == WORM_PERSON_ID
    assert rr.kind == "resource_role_proposed"


def test_resource_role_proposed_signals_default_empty() -> None:
    rr = E.ResourceRoleProposedPayload(
        person_id=PERSON_ID,
        resource_id=RESOURCE_ID,
        role="contributor",
        confidence=0.55,
        proposed_by=WORM_PERSON_ID,
    )
    assert rr.signals == ()


def test_resource_role_proposed_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        E.ResourceRoleProposedPayload(
            person_id=PERSON_ID,
            resource_id=RESOURCE_ID,
            role="maintainer",
            confidence=0.7,
            proposed_by=WORM_PERSON_ID,
            not_allowed=True,  # type: ignore[call-arg]
        )


def test_resource_role_proposed_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        E.ResourceRoleProposedPayload(
            person_id=PERSON_ID,
            resource_id=RESOURCE_ID,
            role="maintainer",
            confidence=1.5,
            proposed_by=WORM_PERSON_ID,
        )
    with pytest.raises(ValidationError):
        E.ResourceRoleProposedPayload(
            person_id=PERSON_ID,
            resource_id=RESOURCE_ID,
            role="maintainer",
            confidence=-0.1,
            proposed_by=WORM_PERSON_ID,
        )


def test_resource_role_proposed_rejects_invalid_role() -> None:
    """Resource-facet roles must be one of {maintainer, contributor}."""
    with pytest.raises(ValidationError):
        E.ResourceRoleProposedPayload(
            person_id=PERSON_ID,
            resource_id=RESOURCE_ID,
            role="dictator",  # not a valid resource role
            confidence=0.7,
            proposed_by=WORM_PERSON_ID,
        )


def test_resource_role_proposed_requires_proposed_by() -> None:
    """proposed_by is required (no default)."""
    with pytest.raises(ValidationError):
        E.ResourceRoleProposedPayload(
            person_id=PERSON_ID,
            resource_id=RESOURCE_ID,
            role="maintainer",
            confidence=0.7,
        )


def test_resource_role_proposed_roundtrips() -> None:
    rr = E.ResourceRoleProposedPayload(
        person_id=PERSON_ID,
        resource_id=RESOURCE_ID,
        role="maintainer",
        confidence=0.81,
        signals=("chat_mention",),
        proposed_by=WORM_PERSON_ID,
    )
    again = E.ResourceRoleProposedPayload.model_validate(rr.model_dump())
    assert again == rr


# ---------------------------------------------------------------------------
# Wave H Phase 2 Task 2C — admin confirm/reject for position proposals
# ---------------------------------------------------------------------------


CONFIRMED_BY = UUID("0190a0a0-0000-7000-8000-0000000000c4")
REJECTED_BY = UUID("0190a0a0-0000-7000-8000-0000000000c5")


def test_position_confirmed_kind_registered() -> None:
    assert "position_confirmed" in E.KIND_REGISTRY
    assert E.KIND_REGISTRY["position_confirmed"] is E.PositionConfirmedPayload


def test_position_rejected_kind_registered() -> None:
    assert "position_rejected" in E.KIND_REGISTRY
    assert E.KIND_REGISTRY["position_rejected"] is E.PositionRejectedPayload


def test_position_confirmed_constructs() -> None:
    p = E.PositionConfirmedPayload(
        person_id=PERSON_ID,
        position="senior_engineer",
        confirmed_by=CONFIRMED_BY,
    )
    assert p.person_id == PERSON_ID
    assert p.position == "senior_engineer"
    assert p.confirmed_by == CONFIRMED_BY
    assert p.kind == "position_confirmed"


def test_position_confirmed_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        E.PositionConfirmedPayload(
            person_id=PERSON_ID,
            position="senior_engineer",
            confirmed_by=CONFIRMED_BY,
            not_allowed=True,  # type: ignore[call-arg]
        )


def test_position_confirmed_roundtrips() -> None:
    p = E.PositionConfirmedPayload(
        person_id=PERSON_ID,
        position="data_analyst",
        confirmed_by=CONFIRMED_BY,
    )
    again = E.PositionConfirmedPayload.model_validate(p.model_dump())
    assert again == p


def test_position_rejected_constructs() -> None:
    p = E.PositionRejectedPayload(
        person_id=PERSON_ID,
        position="senior_engineer",
        rejected_by=REJECTED_BY,
        reason="signal density too low",
    )
    assert p.person_id == PERSON_ID
    assert p.position == "senior_engineer"
    assert p.rejected_by == REJECTED_BY
    assert p.reason == "signal density too low"
    assert p.kind == "position_rejected"


def test_position_rejected_reason_optional() -> None:
    p = E.PositionRejectedPayload(
        person_id=PERSON_ID,
        position="senior_engineer",
        rejected_by=REJECTED_BY,
    )
    assert p.reason is None


def test_position_rejected_rejects_extras() -> None:
    with pytest.raises(ValidationError):
        E.PositionRejectedPayload(
            person_id=PERSON_ID,
            position="senior_engineer",
            rejected_by=REJECTED_BY,
            not_allowed=True,  # type: ignore[call-arg]
        )


def test_position_rejected_roundtrips() -> None:
    p = E.PositionRejectedPayload(
        person_id=PERSON_ID,
        position="data_analyst",
        rejected_by=REJECTED_BY,
        reason="wrong inference",
    )
    again = E.PositionRejectedPayload.model_validate(p.model_dump())
    assert again == p


def test_post_b5_registry_size_is_76() -> None:
    """Doctrine Addendum 2 §E: post-Wave-B.5 baseline was 76 concrete kinds.

    Wave-H additions:
      - Phase 1 Task 1A: ``inference_cache_refreshed`` (76 → 77).
      - Phase 1 Task 1B: ``tenant_signup_initiated`` +
        ``tenant_signup_completed`` for multi-tenancy v2 (77 → 79).
      - Phase 2 Task 2B: ``topic_proposed`` for the silver-conversations
        topic-cluster surface (79 → 80).
      - Phase 2 Task 2C: ``position_confirmed`` + ``position_rejected``
        for the admin auto-confirm UX queue (80 → 82).

    2026-05-05 plan additions:
      - Phase 1 (substrate): ``conversation_sync`` for WhatsApp +
        conversation-provenance lineage (82 → 83).

    2026-05-11 Semantic Layer Wave 1:
      - Task 4: ``external_catalog_imported``,
        ``external_catalog_drift_detected``,
        ``external_lineage_imported``, ``external_policy_imported``,
        ``external_metric_imported`` — catalog-mirror data plane
        for importing upstream-lake structure (83 → 88).

    2026-05-11 Semantic Layer Wave 2:
      - Task 1: ``agent_registered`` + ``agent_grant`` + ``agent_query``
        + ``credential`` — agent-gateway core. Per doctrine Addendum 3:
        single-kind PEVR for ``agent_query`` (one kind, four phases via
        a ``phase`` discriminator); status-field consolidation for
        ``agent_grant`` and ``credential`` (one kind each, ``active`` vs
        ``revoked`` on a status field rather than separate ``_revoked``
        kinds). Net +4 (88 → 92).
      - Task 3: ``query_outcome_recorded`` +
        ``query_correction_suggested`` + ``query_template_promoted`` +
        ``semantic_gap_proposed`` — §4.5 compounding-loop kinds. Per
        doctrine Addendum 3 §B: kept as separate kinds (NOT folded into
        ``agent_query.resolve`` or ``external_metric_imported``)
        because the temporality differs (outcomes land minutes-to-days
        after the PEVR cycle) and the provenance differs (templates
        are agent-derived, not upstream-imported). Net +4 (92 → 96).

    2026-05-12 v2.B Phase 2 (3 new compounding axes):
      - ``bad_pattern_proposed`` — clusters of failed-or-unhelpful
        outcomes on the same canonical NL intent. Distinct from
        ``query_template_promoted`` because the polarity is opposite
        (avoid vs reuse) — the next agent's semantic search
        deprioritizes matching candidates.
      - ``semantic_gap_escalated`` — long-unresolved
        ``semantic_gap_proposed`` entries promoted to admin
        escalations. Distinct from ``semantic_gap_proposed`` because
        the temporality differs (escalation lands N days later); the
        admin queue surfaces escalated gaps with priority.
      - ``data_product_recommended`` — multi-agent consumption
        clusters surfaced on ``/data-products`` as "trending". Distinct
        from ``data_product_proposed`` (which is the original
        promotion) — recommendation tracks downstream usage, not
        initial promotion. Net +3 (96 → 99).

    2026-05-12 v2.B Phase 3 (periodic clock-tick):
      - ``clock_tick`` — ledger-resident periodic tick written by
        ``ClockTickEmitter`` to drive time-based Reactivities (the
        ``Periodic(every_seconds=N)`` predicate). Replaces the
        gap-escalation axis's previous "fire on new gap write" trigger
        with a real cadence-driven tick, so a freshly-installed worm
        can escalate prior gaps without waiting for a second gap to
        land. Net +1 (99 → 100).

    2026-05-12 v2.A Batch A (agent-as-teammate, Seam #3 closure):
      - ``agent_subscription_created`` — agent declares an interest
        filter (kinds / domains / agent_id_ref / payload_path_eq)
        with a transport choice (mcp_stream / webhook). Stored as a
        dict on the ledger so wire-replay stays boundary-free.
      - ``agent_subscription_revoked`` — single revocation kind with
        a ``reason`` discriminator (agent_request / admin_revoked /
        expired / rotated) per status-consolidation doctrine.
      - ``agent_event_delivered`` — one dispatch decision per
        (subscription, triggering_entry) pair. Records
        delivery_status ∈ {delivered, failed, no_target} so
        wire-replay reproduces deliveries and SOC-2 audits answer
        "what did agent X learn at time T". Net +3 (100 → 103).
      - ``agent_metadata_updated`` — mutable agent metadata
        (display_name / description) update written by the agent
        detail page's Edit modal (final-wave item #5,
        2026-05-13). Preserves agent_id continuity so the audit
        trail does not fork on a rebrand. Net +1 (103 → 104).
      - ``tenant_quota_consumed`` — periodic ledger entry summarizing
        per-tenant MCP quota consumption, emitted by the opt-in
        ``LedgerQuotaTracker`` (final-wave item #7, 2026-05-13).
        Default-OFF preserves byte-identical Path 4 in-memory
        behavior; opt-in delivers SOC-2 audit visibility. Net +1
        (104 → 105).
      - ``tenant_engine_registered`` — durable registration of a
        per-tenant database engine (Shape A shared → Shape B isolated
        transitions). Phases 1+2 of engine-per-tenant routing
        (post-rest #1, 2026-05-13). Default-OFF preserves byte-
        identical TenantContext Shape A behavior; opt-in Shape B
        activation is gated behind operator-driven Phase 3 tooling
        (not yet shipped). Net +1 (105 → 106).

      * L3 Sub-wave A (2026-05-29). ``lineage_edge_proposed`` /
        ``lineage_edge_confirmed`` / ``lineage_edge_rejected`` back the
        lake-side L3 compounding loop's projection_lineage_edges fold.
        Additive per Rule 2; net +3 (106 → 109).

      * Onboarding Sub-wave C (2026-05-30). ``domain_pack_selected`` +
        ``person_invited`` back the Tier 2 domain pack picker and the
        real co-admin invite emit. Additive per Rule 2; net +2
        (109 → 111).

      * L7 Sub-wave A (2026-05-30). ``quality_check_proposed`` /
        ``quality_check_confirmed`` / ``quality_check_rejected`` back
        the lake-side L7 compounding loop's projection_quality_checks
        fold. Structurally identical to L3's lineage-edge triple.
        Additive per Rule 2; net +3 (111 → 114).

      * L4 Sub-wave A (2026-06-02). ``schema_impact_proposed`` /
        ``schema_impact_confirmed`` / ``schema_impact_rejected`` back
        the lake-side L4 compounding loop's projection_schema_impacts
        fold. Structurally identical to the L3 / L7 triples.
        Additive per Rule 2; net +3 (114 → 117).

      * L5 Sub-wave A (2026-06-05). ``semantic_type_proposed`` /
        ``semantic_type_confirmed`` / ``semantic_type_rejected`` back
        the lake-side L5 compounding loop's projection_semantic_types
        fold. Structurally identical to the L3 / L7 / L4 triples.
        Additive per Rule 2; net +3 (117 → 120). 30 headroom under
        the 150-kind Rule-5 ceiling per Wave F Addendum 4.

      * L6 Sub-wave A (2026-06-06). ``column_classification_proposed``
        / ``column_classification_confirmed`` /
        ``column_classification_rejected`` back the lake-side L6
        compounding loop's projection_column_classifications fold.
        Structurally identical to the L3 / L7 / L4 / L5 triples.
        Additive per Rule 2; net +3 (120 → 123). 27 headroom under
        the 150-kind Rule-5 ceiling per Wave F Addendum 4. L-axis
        family count 12 → 15 of 30 cap per Addendum 4 §E.

      * L8 Sub-wave A (2026-06-07). ``entity_stitch_proposed`` /
        ``entity_stitch_confirmed`` / ``entity_stitch_rejected`` back
        the lake-side L8 compounding loop's projection_entity_stitches
        fold. Structurally identical to the L3 / L7 / L4 / L5 / L6
        triples. Additive per Rule 2; net +3 (123 → 126). 24 headroom
        under the 150-kind Rule-5 ceiling per Wave F Addendum 4.
        L-axis family count 15 → 18 of 30 cap per Addendum 4 §E.

      * L1 Sub-wave A (2026-06-08). ``source_candidate_proposed`` /
        ``source_candidate_promoted`` / ``source_candidate_rejected``
        back the lake-side L1 compounding loop's
        projection_source_candidates fold (the source-acquisition
        triage layer that prequels the existing source pipeline).
        Structurally identical to the L3 / L7 / L4 / L5 / L6 / L8
        triples; uses ``promoted`` instead of ``confirmed`` per spec
        §1. Additive per Rule 2; net +3 (126 → 129). 21 headroom
        under the 150-kind Rule-5 ceiling per Wave F Addendum 4.
        L-axis family count 18 → 21 of 30 cap per Addendum 4 §E.

      * L2 Sub-wave A (2026-06-09). ``catalog_drift_proposed`` /
        ``catalog_drift_acknowledged`` / ``catalog_drift_rejected``
        back the lake-side L2 compounding loop's
        projection_catalog_drifts fold (catalog-drift detection over
        external_catalog_imported snapshots). Structurally identical
        to the L3 / L7 / L4 / L5 / L6 / L8 / L1 triples; uses
        ``acknowledged`` (a no-op disposition record) instead of
        ``confirmed`` / ``promoted`` per spec §1. Additive per Rule
        2; net +3 (129 → 132). 18 headroom under the 150-kind Rule-5
        ceiling per Wave F Addendum 4. L-axis family count 21 → 24
        of 30 cap per Addendum 4 §E. **L2 is the FINAL planned axis
        in this generation per spec §11.**

    Catalog-mirror Wave 2 Sub-wave A (2026-06-09 follow-on) adds
    one substrate kind:
        - ``catalog_table_imported`` — per-table column metadata
          that L2 TableSet + L8 SchemaShape consume. Substrate
          only; L-axis family count unchanged at 24 of 30.

    Net: 132 → 133.

    Under the Rule 5 threshold (raised to 150 in Wave F Addendum 4;
    L-axis family count = 24 of 30 cap per Addendum 4 §E). The test
    name retains the historic Wave-B.5 baseline; the assertion tracks
    current size.
    """
    assert len(E.KIND_REGISTRY) == 133
