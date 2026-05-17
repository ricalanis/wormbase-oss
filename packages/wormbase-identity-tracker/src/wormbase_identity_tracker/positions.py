"""Step 5 — canonical position registry.

Lifted from ``wormbase_core.positions`` as part of Wave A (identity-worm
extraction). No behavioural changes; the ledger payloads
(``emit_position_assigned``, ``emit_position_metric_added``,
``emit_position_question_pattern``) still target ``wormbase_ledger.entries``
(untouched) so customer-extension via the ledger continues to work
identically.

A static registry of canonical positions (CFO, CMO, data engineer, etc.) plus
each position's:

  * **metric set**           — what they care about. Drives the per-user
                               headline metric in the autoresearch loop.
  * **question patterns**    — how they tend to phrase questions (used by the
                               classifier and by the autoresearch loop's
                               recent-activity slice).
  * **improvement candidates** — the archetype experiments the worm should
                               propose for them. Each candidate carries a
                               descriptive proposed_change dict and a
                               default expected_delta the autoresearch loop
                               consumes when no per-user data exists yet.

The registry is **extensible**: the ledger payloads for ``position_assigned``,
``position_metric_added``, ``position_question_pattern`` accept any string
position id, so customers can add positions at runtime without a schema
migration. The seed registry below is the day-one set the demo + onboarding
wizard exercise.

See ``docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`` Step 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Metric:
    """A headline metric for a position.

    ``unit`` is a free-form label for the dashboard ("USD", "ms", "ratio").
    ``higher_is_better`` is used by the autoresearch loop to decide whether a
    positive observed_delta is a "win" or a "loss".
    """

    metric_id: str
    label: str
    unit: str
    weight: float = 0.5
    higher_is_better: bool = True


@dataclass(frozen=True)
class ImprovementCandidate:
    """An archetype experiment the worm can propose for a position.

    ``proposed_change`` is a dict shape that lands in
    ``ExperimentProposedPayload.proposed_change`` — the autoresearch loop
    materialises it into a deterministic per-user proposal at runtime.
    """

    candidate_id: str
    headline_metric_id: str
    summary: str
    proposed_change: dict[str, Any]
    expected_delta: float


@dataclass(frozen=True)
class Position:
    position_id: str
    label: str
    metrics: tuple[Metric, ...]
    patterns: tuple[str, ...]
    candidates: tuple[ImprovementCandidate, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Canonical seed registry
# ---------------------------------------------------------------------------


_CFO = Position(
    position_id="cfo",
    label="CFO",
    metrics=(
        Metric("revenue", "Net revenue", "USD", weight=1.0, higher_is_better=True),
        Metric("runway", "Cash runway", "months", weight=0.9, higher_is_better=True),
        Metric("cac_payback", "CAC payback", "months", weight=0.7, higher_is_better=False),
        Metric("net_burn", "Net burn", "USD", weight=0.6, higher_is_better=False),
    ),
    patterns=(
        "what's our",
        "how much",
        "vs forecast",
        "this quarter",
        "burn rate",
    ),
    candidates=(
        ImprovementCandidate(
            candidate_id="cfo_forecast_accuracy",
            headline_metric_id="revenue",
            summary="Tighten Q3 revenue forecast accuracy by re-cutting cohorts",
            proposed_change={
                "kind": "kpi_definition",
                "target": "revenue_forecast",
                "change": "exclude_promo_signups_from_cohort",
            },
            expected_delta=0.04,  # +4% accuracy
        ),
        ImprovementCandidate(
            candidate_id="cfo_billing_automation",
            headline_metric_id="cac_payback",
            summary="Automate billing edge cases to drop CAC payback by 0.3 mo",
            proposed_change={
                "kind": "process_automation",
                "target": "billing_close",
                "change": "auto_post_subscription_renewals",
            },
            expected_delta=-0.30,  # CAC payback drops, lower is better
        ),
        ImprovementCandidate(
            candidate_id="cfo_cost_categorization",
            headline_metric_id="net_burn",
            summary="Recategorize SaaS spend so net burn signal stops drifting",
            proposed_change={
                "kind": "classifier_rule",
                "target": "expense_classifier",
                "change": "saas_spend_v2_taxonomy",
            },
            expected_delta=-2200.0,
        ),
    ),
)

_CMO = Position(
    position_id="cmo",
    label="CMO",
    metrics=(
        Metric("retention_m3", "M3 retention", "ratio", weight=1.0, higher_is_better=True),
        Metric("channel_mix_entropy", "Channel-mix entropy", "bits", weight=0.6),
        Metric("viral_coefficient", "Viral coefficient", "ratio", weight=0.7),
        Metric("ad_spend_efficiency", "Ad-spend efficiency", "USD/conv", weight=0.6, higher_is_better=False),
    ),
    patterns=(
        "how is the campaign",
        "what's the lift",
        "channel performance",
        "cohort",
    ),
    candidates=(
        ImprovementCandidate(
            candidate_id="cmo_cohort_definition",
            headline_metric_id="retention_m3",
            summary="Include promo signups in M3 retention cohort to surface true mix",
            proposed_change={
                "kind": "kpi_definition",
                "target": "retention_cohort",
                "change": "include_promo_signups",
            },
            expected_delta=0.08,
        ),
        ImprovementCandidate(
            candidate_id="cmo_channel_attribution",
            headline_metric_id="channel_mix_entropy",
            summary="Multi-touch attribution on top of last-touch baseline",
            proposed_change={
                "kind": "model",
                "target": "attribution_model",
                "change": "multi_touch_v1",
            },
            expected_delta=0.12,
        ),
    ),
)

_DATA_ENGINEER = Position(
    position_id="data_engineer",
    label="Data engineer",
    metrics=(
        Metric("pipeline_p95_latency_ms", "Pipeline P95 latency", "ms",
               weight=1.0, higher_is_better=False),
        Metric("schema_drift_count", "Schema drifts (24h)", "count",
               weight=0.7, higher_is_better=False),
        Metric("query_cost_usd", "Query cost (24h)", "USD",
               weight=0.6, higher_is_better=False),
    ),
    patterns=(
        "why is",
        "when did this break",
        "what changed",
        "schema",
        "query cost",
    ),
    candidates=(
        ImprovementCandidate(
            candidate_id="de_query_cache",
            headline_metric_id="pipeline_p95_latency_ms",
            summary="Cache the Q3 net-revenue rollup for 5 min",
            proposed_change={
                "kind": "cache_layer",
                "target": "q3_net_revenue_query",
                "ttl_seconds": 300,
            },
            expected_delta=-180.0,  # latency drops 180ms
        ),
        ImprovementCandidate(
            candidate_id="de_pipeline_parallelism",
            headline_metric_id="pipeline_p95_latency_ms",
            summary="Parallelize bronze→silver fan-out across 3 workers",
            proposed_change={
                "kind": "pipeline_parameter",
                "target": "bronze_to_silver",
                "workers": 3,
            },
            expected_delta=-95.0,
        ),
        ImprovementCandidate(
            candidate_id="de_schema_versioning",
            headline_metric_id="schema_drift_count",
            summary="Version the silver schema to detect drift before it breaks gold",
            proposed_change={
                "kind": "schema_policy",
                "target": "silver_schema_v2",
                "change": "version_lock",
            },
            expected_delta=-3.0,
        ),
    ),
)

_MARKETING_LEAD = Position(
    position_id="marketing_lead",
    label="Marketing lead",
    metrics=(
        Metric("mql_to_sql_ratio", "MQL→SQL ratio", "ratio", weight=0.9),
        Metric("campaign_lift", "Campaign lift", "ratio", weight=0.8),
        Metric("creative_ctr", "Creative CTR", "ratio", weight=0.6),
    ),
    patterns=(
        "how is the campaign",
        "did the test win",
        "lift",
        "creative",
    ),
    candidates=(
        ImprovementCandidate(
            candidate_id="ml_test_window",
            headline_metric_id="campaign_lift",
            summary="Hold campaign A/B for 14 days instead of 7 to detect lift",
            proposed_change={
                "kind": "experiment_window",
                "target": "campaign_ab_test",
                "days": 14,
            },
            expected_delta=0.06,
        ),
        ImprovementCandidate(
            candidate_id="ml_creative_rotation",
            headline_metric_id="creative_ctr",
            summary="Rotate creatives every 72h to fight ad fatigue",
            proposed_change={
                "kind": "campaign_policy",
                "target": "creative_rotation",
                "hours": 72,
            },
            expected_delta=0.02,
        ),
    ),
)

_OPS_MANAGER = Position(
    position_id="ops_manager",
    label="Ops manager",
    metrics=(
        Metric("ticket_p95_resolution_h", "Ticket P95 resolution", "hours",
               weight=0.9, higher_is_better=False),
        Metric("on_call_paging_count", "On-call pages (24h)", "count",
               weight=0.7, higher_is_better=False),
        Metric("incident_count_7d", "Incidents (7d)", "count",
               weight=0.8, higher_is_better=False),
    ),
    patterns=(
        "ticket",
        "on-call",
        "oncall",
        "sev",
        "incident",
    ),
    candidates=(
        ImprovementCandidate(
            candidate_id="ops_ticket_routing",
            headline_metric_id="ticket_p95_resolution_h",
            summary="Auto-route billing tickets to finance ops queue",
            proposed_change={
                "kind": "routing_rule",
                "target": "ticket_router",
                "change": "billing_to_finance_ops",
            },
            expected_delta=-3.5,
        ),
        ImprovementCandidate(
            candidate_id="ops_runbook_automation",
            headline_metric_id="on_call_paging_count",
            summary="Auto-resolve sev-3 disk-full alerts via runbook",
            proposed_change={
                "kind": "runbook",
                "target": "disk_full_sev3",
                "change": "auto_truncate_logs",
            },
            expected_delta=-2.0,
        ),
    ),
)

_CUSTOMER_SUCCESS = Position(
    position_id="customer_success",
    label="Customer success",
    metrics=(
        Metric("nps", "NPS", "score", weight=1.0),
        Metric("renewal_rate", "Renewal rate", "ratio", weight=0.9),
        Metric("at_risk_account_count", "At-risk accounts", "count",
               weight=0.7, higher_is_better=False),
    ),
    patterns=(
        "renewal",
        "at risk",
        "churn",
        "expansion",
        "csm",
    ),
    candidates=(
        ImprovementCandidate(
            candidate_id="cs_health_score",
            headline_metric_id="at_risk_account_count",
            summary="Health-score weighting: triple usage-decline signal",
            proposed_change={
                "kind": "kpi_definition",
                "target": "health_score",
                "change": "usage_decline_weight_3x",
            },
            expected_delta=-4.0,
        ),
        ImprovementCandidate(
            candidate_id="cs_qbr_cadence",
            headline_metric_id="renewal_rate",
            summary="QBR every 60 days for accounts >$50k ARR",
            proposed_change={
                "kind": "process_policy",
                "target": "qbr_cadence",
                "change": "60d_for_high_arr",
            },
            expected_delta=0.03,
        ),
    ),
)

_FOUNDER = Position(
    position_id="founder",
    label="Founder",
    metrics=(
        Metric("revenue", "Net revenue", "USD", weight=1.0),
        Metric("runway", "Cash runway", "months", weight=1.0),
        Metric("hiring_velocity", "Hiring velocity", "hires/mo", weight=0.6),
        Metric("strategy_review_cadence_d", "Strategy review cadence", "days",
               weight=0.4, higher_is_better=False),
    ),
    patterns=(
        "where are we",
        "biggest risk",
        "north star",
        "weekly update",
    ),
    candidates=(
        ImprovementCandidate(
            candidate_id="founder_weekly_digest",
            headline_metric_id="strategy_review_cadence_d",
            summary="Auto-compile a Monday-morning digest from the gold layer",
            proposed_change={
                "kind": "data_product",
                "target": "weekly_digest",
                "change": "auto_compile_monday_0700",
            },
            expected_delta=-2.0,
        ),
        ImprovementCandidate(
            candidate_id="founder_runway_tracker",
            headline_metric_id="runway",
            summary="Surface 4-week rolling runway projection on /dashboard",
            proposed_change={
                "kind": "dashboard_widget",
                "target": "runway_widget",
                "change": "4w_rolling",
            },
            expected_delta=0.5,
        ),
    ),
)

_ADMIN = Position(
    position_id="admin",
    label="Admin",
    metrics=(
        Metric("policy_violation_count_7d", "Policy violations (7d)", "count",
               weight=1.0, higher_is_better=False),
        Metric("ramp_completeness", "Ramp completeness", "ratio",
               weight=0.9, higher_is_better=True),
        Metric("source_coverage", "Source coverage", "ratio", weight=0.7),
    ),
    patterns=(
        "policy",
        "classification",
        "audit",
        "compliance",
    ),
    candidates=(
        ImprovementCandidate(
            candidate_id="admin_classification_review",
            headline_metric_id="policy_violation_count_7d",
            summary="Auto-flag confidential resources without an owner for review",
            proposed_change={
                "kind": "governance_check",
                "target": "owner_assignment",
                "change": "flag_confidential_no_owner",
            },
            expected_delta=-1.0,
        ),
        ImprovementCandidate(
            candidate_id="admin_ramp_seed",
            headline_metric_id="ramp_completeness",
            summary="Pre-seed marketing-domain ontology to push ramp from 65→78%",
            proposed_change={
                "kind": "ontology_seed",
                "target": "marketing_pack_v2",
                "change": "load_seed",
            },
            expected_delta=0.13,
        ),
    ),
)

_PRODUCT_MANAGER = Position(
    position_id="product_manager",
    label="Product manager",
    metrics=(
        Metric("activation_rate", "Activation rate", "ratio", weight=1.0),
        Metric("feature_adoption_p7", "P7 feature adoption", "ratio", weight=0.7),
        Metric("dau_wau_ratio", "DAU/WAU stickiness", "ratio", weight=0.7),
    ),
    patterns=(
        "activation",
        "adoption",
        "feature",
        "experiment",
    ),
    candidates=(
        ImprovementCandidate(
            candidate_id="pm_activation_funnel",
            headline_metric_id="activation_rate",
            summary="Re-cut activation funnel: drop step 4 (unused 92% of users)",
            proposed_change={
                "kind": "funnel_definition",
                "target": "activation_funnel",
                "change": "drop_step_4",
            },
            expected_delta=0.05,
        ),
        ImprovementCandidate(
            candidate_id="pm_feature_release_gate",
            headline_metric_id="feature_adoption_p7",
            summary="A/B gate new features at 25% before full rollout",
            proposed_change={
                "kind": "release_gate",
                "target": "feature_flags",
                "change": "ab_at_25_pct",
            },
            expected_delta=0.04,
        ),
    ),
)


_REGISTRY: dict[str, Position] = {
    p.position_id: p for p in (
        _CFO,
        _CMO,
        _DATA_ENGINEER,
        _MARKETING_LEAD,
        _OPS_MANAGER,
        _CUSTOMER_SUCCESS,
        _FOUNDER,
        _ADMIN,
        _PRODUCT_MANAGER,
    )
}


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------


def all_positions() -> list[Position]:
    """Return the canonical list of positions, sorted by id for stable order."""
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def get_position(position_id: str) -> Position | None:
    """Return the registry entry for ``position_id``; ``None`` if unknown."""
    return _REGISTRY.get(position_id)


def position_metrics(position_id: str) -> list[Metric]:
    """Return the position's metric set; empty list if unknown position."""
    p = _REGISTRY.get(position_id)
    return list(p.metrics) if p else []


def position_patterns(position_id: str) -> list[str]:
    """Return the position's question patterns; empty list if unknown."""
    p = _REGISTRY.get(position_id)
    return list(p.patterns) if p else []


def position_candidates(position_id: str) -> list[ImprovementCandidate]:
    """Return the position's improvement candidates; empty list if unknown."""
    p = _REGISTRY.get(position_id)
    return list(p.candidates) if p else []


def headline_metric_for_position(position_id: str) -> Metric | None:
    """Return the highest-weight metric for the position (a deterministic pick).

    Tie-broken by metric_id ascending so the result is stable across runs.
    """
    metrics = position_metrics(position_id)
    if not metrics:
        return None
    return sorted(metrics, key=lambda m: (-m.weight, m.metric_id))[0]


# ---------------------------------------------------------------------------
# Signal scoring (Wave B.5 G.4 — PositionInferenceReactivity)
# ---------------------------------------------------------------------------


def score_signals(
    texts: list[str] | tuple[str, ...],
) -> tuple[str | None, float, tuple[str, ...]]:
    """Score the chatter ``texts`` against every canonical position.

    Returns ``(best_position_id, confidence, signals)``:

      * ``best_position_id`` — the position with the highest score, or
        ``None`` if no position pattern matched in any text.
      * ``confidence`` — float in [0.0, 1.0] computed as
        ``unique_patterns_matched / total_patterns_in_position``.
      * ``signals`` — the matched pattern tokens for the best position,
        deduplicated and ordered by registry order. Surfaced to the
        trace UI for explainability.

    Implementation notes:

      * Matching is a simple lowercase substring match, mirroring the
        legacy classifier's keyword-driven approach. The scorer is
        intentionally cheap — high-precision tightening is a separate
        concern (the per-position rule packs in `classifier.py`).
      * Ties between positions break deterministically on the
        position_id alphabetical sort so re-runs produce stable
        proposals.
      * Empty input or no matches → ``(None, 0.0, ())``.
    """
    if not texts:
        return None, 0.0, ()

    blob = " \n ".join(t.lower() for t in texts if t)
    if not blob:
        return None, 0.0, ()

    best_pos: str | None = None
    best_score = 0.0
    best_signals: tuple[str, ...] = ()

    for pid in sorted(_REGISTRY):
        pos = _REGISTRY[pid]
        patterns = pos.patterns
        if not patterns:
            continue
        matched: list[str] = []
        for pat in patterns:
            if pat.lower() in blob and pat not in matched:
                matched.append(pat)
        if not matched:
            continue
        score = len(matched) / len(patterns)
        if score > best_score:
            best_score = score
            best_pos = pid
            best_signals = tuple(matched)

    if best_pos is None:
        return None, 0.0, ()
    return best_pos, best_score, best_signals


__all__ = [
    "ImprovementCandidate",
    "Metric",
    "Position",
    "all_positions",
    "get_position",
    "headline_metric_for_position",
    "position_candidates",
    "position_metrics",
    "position_patterns",
    "score_signals",
]
