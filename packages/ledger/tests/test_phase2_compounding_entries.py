"""v2.B Phase 2 — three new compounding-loop entry kinds.

Additive per schema-evolution doctrine Rule 2; net +3 → KIND_REGISTRY=99.

Pins three new payload classes (per doctrine Addendum 3 §B — same
compounding-loop family as the Wave 2 Task 3 batch; budget has
headroom under the raised 100-kind ceiling per Wave F Addendum 1):

* ``BadPatternProposedPayload`` (kind ``bad_pattern_proposed``) —
  clusters of failed-or-unhelpful outcomes on the same canonical NL
  intent. Promoted by the ``QueryFailureToBadPattern`` Reactivity.
* ``SemanticGapEscalatedPayload`` (kind ``semantic_gap_escalated``) —
  long-unresolved ``semantic_gap_proposed`` entries. Promoted by the
  ``SemanticGapToEscalation`` Reactivity (default 7-day window).
* ``DataProductRecommendedPayload`` (kind ``data_product_recommended``)
  — multi-agent consumption clusters. Promoted by the
  ``DataProductConsumptionToRecommendation`` Reactivity.

These tests pin:

* Registration in ``KIND_REGISTRY`` (auto-registration via
  ``EntryPayload.__init_subclass__``).
* Round-trip via ``model_dump`` → ``model_validate`` byte-equivalently.
* KIND_REGISTRY size pinned at 99 (96 pre-Phase-2 + 3 here).
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from wormbase_ledger.entries import (
    ALL_KINDS,
    KIND_REGISTRY,
    BadPatternProposedPayload,
    DataProductRecommendedPayload,
    SemanticGapEscalatedPayload,
)


@pytest.mark.parametrize(
    "kind",
    [
        "bad_pattern_proposed",
        "semantic_gap_escalated",
        "data_product_recommended",
    ],
)
def test_kind_registered(kind: str) -> None:
    """Each new v2.B Phase 2 kind auto-registers in KIND_REGISTRY."""
    assert kind in KIND_REGISTRY
    assert kind in ALL_KINDS


def test_kind_registry_size_at_99_after_phase_2() -> None:
    """Phase 2 lands at 99 (96 Wave 2 + 3 v2.B Phase 2 axes); Phase 3
    (2026-05-12) adds ``clock_tick`` for the periodic-tick emitter,
    bringing the baseline to 100. v2.A Batch A (2026-05-12) adds three
    subscription kinds (``agent_subscription_created``,
    ``agent_subscription_revoked``, ``agent_event_delivered``) closing
    Seam #3 (agent-as-teammate), so the size moved to 103. The final
    wave (2026-05-13) adds ``agent_metadata_updated`` for the agent
    edit flow (item #5), then ``tenant_quota_consumed`` for the
    tenant-policy ledger emission opt-in (item #7), so the size went
    to 105. Post-rest #1 (2026-05-13) adds
    ``tenant_engine_registered`` for engine-per-tenant Phase 2, so
    the size moved to 106. L3 Sub-wave A (2026-05-29) lands the
    three lake-side lineage-discovery kinds
    (``lineage_edge_proposed`` / ``lineage_edge_confirmed`` /
    ``lineage_edge_rejected``), bumping the baseline to 109.

    Onboarding Sub-wave C (2026-05-30) adds ``domain_pack_selected`` +
    ``person_invited``, bumping the baseline to 111.

    L7 Sub-wave A (2026-05-30) adds ``quality_check_proposed`` /
    ``quality_check_confirmed`` / ``quality_check_rejected``, bumping
    the baseline to 114.

    L4 Sub-wave A (2026-06-02) adds ``schema_impact_proposed`` /
    ``schema_impact_confirmed`` / ``schema_impact_rejected``, bumping
    the baseline to 117.

    L5 Sub-wave A (2026-06-05) adds ``semantic_type_proposed`` /
    ``semantic_type_confirmed`` / ``semantic_type_rejected``, bumping
    the baseline to 120. 30 kinds remaining under the 150-kind Rule-5
    ceiling per Wave F Addendum 4.

    L6 Sub-wave A (2026-06-06) adds ``column_classification_proposed`` /
    ``column_classification_confirmed`` /
    ``column_classification_rejected``, bumping the baseline to 123.
    27 kinds remaining under the 150-kind Rule-5 ceiling. L-axis
    family count 12 → 15 of 30 cap per Addendum 4 §E.

    L8 Sub-wave A (2026-06-07) adds ``entity_stitch_proposed`` /
    ``entity_stitch_confirmed`` / ``entity_stitch_rejected``, bumping
    the baseline to 126. 24 kinds remaining under the 150-kind Rule-5
    ceiling. L-axis family count 15 → 18 of 30 cap per Addendum 4 §E.

    L1 Sub-wave A (2026-06-08) adds ``source_candidate_proposed`` /
    ``source_candidate_promoted`` / ``source_candidate_rejected``,
    bumping the baseline to 129. 21 kinds remaining under the 150-
    kind Rule-5 ceiling. L-axis family count 18 → 21 of 30 cap per
    Addendum 4 §E (9 headroom remaining).

    L2 Sub-wave A (2026-06-09) adds ``catalog_drift_proposed`` /
    ``catalog_drift_acknowledged`` / ``catalog_drift_rejected``,
    bumping the baseline to 132. 18 kinds remaining under the 150-
    kind Rule-5 ceiling. L-axis family count 21 → 24 of 30 cap per
    Addendum 4 §E. **L2 is the FINAL planned axis in this
    generation per spec §11.**

    Catalog-mirror Wave 2 Sub-wave A (2026-06-09 follow-on) adds
    ``catalog_table_imported`` substrate — 132 → 133; L-axis family
    unchanged at 24 of 30 (substrate only, not a lake-axis kind).

    Headroom under the raised 150-kind Rule-5 ceiling per Wave F
    Addendum 4; precise count pinned here so future drift is caught
    at commit time. Test name retains the Phase-2 baseline; the
    assertion tracks current size.
    """
    assert len(KIND_REGISTRY) == 133


def test_bad_pattern_proposed_roundtrip() -> None:
    """``bad_pattern_proposed`` carries canonicalised intent + failure
    metadata + suggested avoidance prose."""
    p = BadPatternProposedPayload(
        canonical_intent="what was q3 emea revenue",
        failed_outcome_ids=(
            "outcome-1",
            "outcome-2",
            "outcome-3",
        ),
        failed_query_specs=[
            {"metric": "revenue_q3", "filter": {"region": "EMEA"}},
            {"metric": "revenue_q3", "filter": {"region": "emea"}},
        ],
        failure_count=2,
        suggested_avoidance=(
            "Use `revenue_total_q3` instead — region filter has "
            "case-sensitive joins on the source dim."
        ),
        domain_id="dom-finance",
    )
    assert BadPatternProposedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "bad_pattern_proposed"


def test_bad_pattern_proposed_optional_domain_id() -> None:
    """``domain_id`` is optional (None when cluster spans no resolved
    domain or only the ``_no_domain`` sentinel)."""
    p = BadPatternProposedPayload(
        canonical_intent="some intent",
        failed_outcome_ids=("o-1", "o-2"),
        failed_query_specs=[],
        failure_count=2,
        suggested_avoidance="Try a different metric.",
    )
    assert p.domain_id is None
    assert BadPatternProposedPayload.model_validate(p.model_dump()) == p


def test_semantic_gap_escalated_roundtrip() -> None:
    """``semantic_gap_escalated`` chains via ``original_gap_id`` and
    carries the frozen ``days_unresolved`` snapshot the Reactivity saw
    at promotion time."""
    p = SemanticGapEscalatedPayload(
        original_gap_id="gap-uuid-1",
        nl_question="What was net retention rate for Q3?",
        reason="no_match",
        days_unresolved=8,
        proposed_metric_name="net_retention_rate_q3",
    )
    assert SemanticGapEscalatedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "semantic_gap_escalated"


def test_semantic_gap_escalated_reason_literal_enforced() -> None:
    """Pydantic rejects ``reason`` outside {no_match, low_confidence,
    ambiguous} — mirrors the parent ``semantic_gap_proposed`` enum."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SemanticGapEscalatedPayload(
            original_gap_id="gap-uuid-1",
            nl_question="x",
            reason="unknown",  # type: ignore[arg-type]
            days_unresolved=8,
        )


def test_semantic_gap_escalated_optional_metric_name() -> None:
    """``proposed_metric_name`` defaults to None (carried through from
    the parent gap when the agent couldn't suggest a name)."""
    p = SemanticGapEscalatedPayload(
        original_gap_id="gap-uuid-2",
        nl_question="What about that thing from before?",
        reason="ambiguous",
        days_unresolved=12,
    )
    assert p.proposed_metric_name is None
    assert SemanticGapEscalatedPayload.model_validate(p.model_dump()) == p


def test_data_product_recommended_roundtrip() -> None:
    """``data_product_recommended`` carries the UUID data_product_id +
    integer score + tuple of consumer AgentIDs + look-back window."""
    dp_id = uuid4()
    p = DataProductRecommendedPayload(
        data_product_id=dp_id,
        recommendation_score=3,
        consumer_agent_ids=("agent-a", "agent-b", "agent-c"),
        consumed_within_days=7,
    )
    assert DataProductRecommendedPayload.model_validate(p.model_dump()) == p
    assert p.kind == "data_product_recommended"
    assert p.data_product_id == dp_id


def test_data_product_recommended_consumer_ids_tuple_immutable() -> None:
    """``consumer_agent_ids`` is a tuple (frozen-shape contract) so
    consumers can't mutate the recommendation post-write."""
    p = DataProductRecommendedPayload(
        data_product_id=UUID("00000000-0000-0000-0000-000000000999"),
        recommendation_score=4,
        consumer_agent_ids=("a", "b", "c", "d"),
        consumed_within_days=7,
    )
    assert isinstance(p.consumer_agent_ids, tuple)
    # round-trip preserves tuple-shape
    p2 = DataProductRecommendedPayload.model_validate(p.model_dump())
    assert isinstance(p2.consumer_agent_ids, tuple)
    assert p2.consumer_agent_ids == ("a", "b", "c", "d")
