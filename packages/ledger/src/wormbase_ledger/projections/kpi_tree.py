"""KPI tree projection contract (Wave-2 review resolution: P3 writes, P4 reads).

This module defines the shape that:
    - Phase 3 (worm-core) writes when classifying / proposing new KPI nodes.
    - Phase 4 (dashboard) reads to render the KPI tree.
    - the ledger package hosts as the single source of truth.

The Pydantic model is intentionally narrow: only the fields both producers
and consumers must agree on. Additional implementation details (e.g. SQL
references, last-updated timestamps) are derived projection state and live
in `projection_kpi_nodes` table rows but are not part of this contract.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Confidence buckets used by both worm-core (writer) and dashboard (renderer).
# String values keep canonical-JSON byte-stable across replays.
Confidence = Literal["proposed", "draft", "confirmed", "deprecated"]

# Metric-type vocabulary. Extend with care — both producers and consumers
# must accept new values, so prefer additive evolution.
MetricType = Literal[
    "rate",
    "ratio",
    "count",
    "amount",
    "duration",
    "percentage",
    "score",
    "other",
]


class KpiNode(BaseModel):
    """The KPI tree projection's single node.

    `id` is a stable string (e.g. "churn.monthly", "revenue.mrr") so the
    dashboard can deep-link without knowing UUIDs. `source_resource_id`
    points to the underlying `projection_sources.source_id` if a metric
    has a definitional source.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    domain_id: UUID | None = None
    owner_person_id: UUID | None = None
    parent_node_id: str | None = None
    source_resource_id: UUID | None = None
    metric_type: MetricType = "other"
    confidence: Confidence = "proposed"


__all__ = ["Confidence", "KpiNode", "MetricType"]
