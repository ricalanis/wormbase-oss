"""Demo-day projections (composite_score, keep-rate).

Pure-function projections folded over the ledger entry stream. These
sit in worm-core (not the canonical packages/ledger projections folder)
because they read across many entry kinds — gate-fire precision,
propose→keep ratio, ramp deltas, reactivity confirm rate — and the
canonical projections in ``wormbase_ledger.projections.builder`` keep
the per-resource fold isolated.

Per CLAUDE.md (project root) the ledger is the single source of truth.
These projections never persist intermediate state to a separate table;
they recompute deterministically from the ledger row stream every time
the dashboard asks. Replay safety: same row stream → same scalar.
"""

from __future__ import annotations

from wormbase_core.projections.composite_score import (
    CompositeScore,
    CompositeScoreSeries,
    CompositeScorePoint,
    composite_score,
    composite_score_series,
)
from wormbase_core.projections.keep_rate import (
    KeepRateRow,
    keep_rate_for_window,
    keep_rate_series,
)
from wormbase_core.projections.knowledge_ramp import (
    GAUGE_AXES,
    SPARKLINE_BUCKETS,
    SPARKLINE_MAX_ENTRIES,
    SPARKLINE_WINDOW,
    TRACE_FILTER_KIND,
    GaugeAxis,
    GaugeReading,
    KnowledgeRampGauges,
    compute_knowledge_ramp_gauges,
)
from wormbase_core.projections.first_knowings import (
    PHENOMENON_KINDS,
    FirstKnowingRow,
    FirstKnowingsResult,
    PhenomenonKind,
    RecencyFilter,
    ScopeFilter,
    compute_first_knowings,
)

__all__ = [
    "CompositeScore",
    "CompositeScorePoint",
    "CompositeScoreSeries",
    "FirstKnowingRow",
    "FirstKnowingsResult",
    "GAUGE_AXES",
    "PHENOMENON_KINDS",
    "PhenomenonKind",
    "RecencyFilter",
    "ScopeFilter",
    "SPARKLINE_BUCKETS",
    "SPARKLINE_MAX_ENTRIES",
    "SPARKLINE_WINDOW",
    "TRACE_FILTER_KIND",
    "GaugeAxis",
    "GaugeReading",
    "KeepRateRow",
    "KnowledgeRampGauges",
    "composite_score",
    "composite_score_series",
    "compute_first_knowings",
    "compute_knowledge_ramp_gauges",
    "keep_rate_for_window",
    "keep_rate_series",
]
