"""§4.5 compounding-layer entry kinds — registration + payload round-trip.

Semantic Layer Wave 2 Task 3 (2026-05-11). Four entry kinds carry the
compounding query layer — outcomes, corrections, template promotions,
and semantic gaps — per doctrine Addendum 3 §B:

- ``query_outcome_recorded`` — lands AFTER user feedback (minutes-to-
  days post ``agent_query.resolve``). Distinct temporality from the
  PEVR cycle so it is NOT folded into ``agent_query.resolve``.
- ``query_correction_suggested`` — backend's reflective suggestion for
  a failed agent_query. Chains via ``original_query_id`` to the
  failing agent_query.
- ``query_template_promoted`` — cluster of high-quality outcomes
  promoted to a durable query template. Distinct provenance from
  ``external_metric_imported`` (templates are agent-derived, not
  upstream-imported).
- ``semantic_gap_proposed`` — agent-reported gap when no matching
  metric exists; observed without an enclosing agent_query.
"""
from __future__ import annotations

import pytest

from wormbase_ledger.entries import (
    KIND_REGISTRY,
    QueryCorrectionSuggestedPayload,
    QueryOutcomeRecordedPayload,
    QueryTemplatePromotedPayload,
    SemanticGapProposedPayload,
)


@pytest.mark.parametrize(
    "kind",
    [
        "query_correction_suggested",
        "query_outcome_recorded",
        "query_template_promoted",
        "semantic_gap_proposed",
    ],
)
def test_kind_registered(kind: str) -> None:
    """Each compounding-loop kind auto-registers in KIND_REGISTRY."""
    assert kind in KIND_REGISTRY


def test_kind_registry_size_at_96_after_wave_2_lands() -> None:
    """Wave 2 ended at 96 (88 Wave 1 + 4 Task 1 + 4 Task 3); v2.B Phase 2
    (2026-05-12) added 3 more compounding-loop kinds → 99. v2.B Phase 3
    (2026-05-12) adds ``clock_tick`` for the periodic-tick emitter →
    100. v2.A Batch A (2026-05-12) adds 3 subscription kinds → 103.
    Final wave item #5 (2026-05-13) adds ``agent_metadata_updated``
    → 104. Final wave item #7 (2026-05-13) adds
    ``tenant_quota_consumed`` → 105. Post-rest #1 (2026-05-13) adds
    ``tenant_engine_registered`` → 106. L3 Sub-wave A (2026-05-29)
    adds three lake-side lineage-discovery kinds → 109. Onboarding
    Sub-wave C (2026-05-30) adds ``domain_pack_selected`` +
    ``person_invited`` → 111.

    During parallel landing this test may see 92 (Task 1 only), 96
    (both Task 1 + 3), 99 (Phase 2 lands), 100 (Phase 3 lands),
    103 (v2.A Batch A lands), 104 (final wave item #5 lands), 105
    (final wave item #7 lands), 106 (post-rest #1 lands), 109
    (L3 Sub-wave A lands), 111 (Onboarding Sub-wave C lands), 114
    (L7 Sub-wave A lands), 117 (L4 Sub-wave A lands), 120
    (L5 Sub-wave A lands), 123 (L6 Sub-wave A lands), 126
    (L8 Sub-wave A lands), 129 (L1 Sub-wave A lands), 132
    (L2 Sub-wave A lands — FINAL planned axis per spec §11), or
    133 (catalog-mirror Wave 2 Sub-wave A substrate
    ``catalog_table_imported`` lands). The precise count is pinned
    in ``test_entry_kind_registration.py`` and ``test_entries_base.py``.
    """
    assert 92 <= len(KIND_REGISTRY) <= 133


def test_query_outcome_recorded_roundtrip() -> None:
    """``query_outcome_recorded`` carries used/useful/correction +
    Decimal-as-string quality_score, all bool / dict / str fields."""
    p = QueryOutcomeRecordedPayload(
        agent_query_id="audit-trail-uuid-1",
        nl_question="What was Q3 EMEA revenue?",
        final_query_spec={"metric": "revenue_q3", "filter": {"region": "EMEA"}},
        result_summary={"row_count": 1, "top_n_hash": "abc"},
        used=True,
        useful=True,
        user_correction=None,
        quality_score="0.95",
    )
    assert QueryOutcomeRecordedPayload.model_validate(p.model_dump()) == p


def test_query_correction_suggested_roundtrip_with_caused_by() -> None:
    """``query_correction_suggested`` chains to a failing ``agent_query``
    via ``original_query_id``; ``failure_kind`` enum matches Literal."""
    p = QueryCorrectionSuggestedPayload(
        original_query_id="audit-trail-uuid-1",
        failure_kind="error",
        failure_detail="SQL compilation error",
        refined_query_spec={
            "metric": "revenue_q3",
            "filter": {"region": "EMEA", "year": 2026},
        },
    )
    assert QueryCorrectionSuggestedPayload.model_validate(p.model_dump()) == p


def test_query_correction_failure_kind_literal_enforced() -> None:
    """Pydantic rejects ``failure_kind`` outside {error, empty,
    schema_mismatch}."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        QueryCorrectionSuggestedPayload(
            original_query_id="x",
            failure_kind="unknown_failure",  # type: ignore[arg-type]
            failure_detail="boom",
            refined_query_spec={},
        )


def test_semantic_gap_proposed_roundtrip() -> None:
    """``semantic_gap_proposed`` carries the agent's NL question + the
    proposed metric name (optional). Observed when no matching metric
    exists — no enclosing agent_query."""
    p = SemanticGapProposedPayload(
        agent_id="agent-uuid-1",
        nl_question="What was net retention rate for Q3?",
        reason="no_match",
        proposed_metric_name="net_retention_rate_q3",
    )
    assert SemanticGapProposedPayload.model_validate(p.model_dump()) == p


def test_semantic_gap_proposed_optional_metric_name() -> None:
    """``proposed_metric_name`` defaults to None when the agent can't
    suggest a name (e.g. for ambiguous questions)."""
    p = SemanticGapProposedPayload(
        agent_id="agent-uuid-1",
        nl_question="What about that thing from before?",
        reason="ambiguous",
    )
    assert p.proposed_metric_name is None
    assert SemanticGapProposedPayload.model_validate(p.model_dump()) == p


def test_query_template_promoted_roundtrip() -> None:
    """``query_template_promoted`` carries the canonical NL intent +
    query_spec + the outcome ids that drove the promotion (tuple)."""
    p = QueryTemplatePromotedPayload(
        domain_id="domain-finance-uuid",
        nl_intent="quarterly revenue by region",
        query_spec={"metric": "revenue_q3", "filter": {"region": ":region"}},
        promoted_from_outcome_ids=(
            "outcome-uuid-1",
            "outcome-uuid-2",
            "outcome-uuid-3",
        ),
        quality_score="0.92",
    )
    assert QueryTemplatePromotedPayload.model_validate(p.model_dump()) == p
