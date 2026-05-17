"""Report and value types for LakeMaintainer.

Acquisition types (``Profile``, ``ResourceProposal``, ``Capability``,
``Change``) re-export the canonical shapes from ``wormbase_connectors.types``
so AcquirableSource doesn't fork them. Maintenance types
(``DriftReport``, ``ClassificationUpdate``, ``StalenessReport``,
``LineageReport``) are new — none of the four families have a home for
these signals today.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

from wormbase_connectors.types import (  # re-exports
    Capability,
    Change,
    ClassificationHint,
    Profile,
    ResourceProposal,
)

SourceFamily = Literal["external", "filedrop", "conversation", "evidence"]
Classification = Literal["public", "internal", "confidential", "pii", "regulated"]


@dataclass(frozen=True)
class DriftReport:
    """Result of ``MaintainableSource.detect_drift()``.

    ``drifted`` is the headline boolean. ``reason`` is operator-readable
    (e.g. "schema_hash changed: 0xabc → 0xdef" or "topic cluster appeared:
    'churn-q3'"). ``baseline_hash`` / ``current_hash`` are SHA-256 hex
    digests when applicable; ``None`` for non-tabular families where
    drift is semantic rather than schema.
    """

    drifted: bool
    reason: str
    baseline_hash: str | None = None
    current_hash: str | None = None


@dataclass(frozen=True)
class ClassificationUpdate:
    """Result of ``MaintainableSource.refresh_classification()``."""

    updated: bool
    classification: Classification
    previous_classification: Classification | None = None
    reason: str = ""


@dataclass(frozen=True)
class StalenessReport:
    """Result of ``MaintainableSource.staleness_signal()``.

    ``stale`` flips when ``last_seen`` is older than the per-family
    freshness SLA. The maintainer's StalenessSignalReactivity emits an
    ``emit_source_staleness_signaled`` ledger entry on the True->False
    edge.
    """

    stale: bool
    last_seen: datetime | None
    sla_hours: float = 24.0


@dataclass(frozen=True)
class LineageEdge:
    """One edge in a lineage chain (e.g. source → silver_column → kpi_node)."""

    upstream_kind: str
    upstream_id: str
    downstream_kind: str
    downstream_id: str
    healthy: bool
    reason: str = ""


@dataclass(frozen=True)
class LineageReport:
    """Result of ``MaintainableSource.lineage_health()``."""

    healthy: bool
    broken_edges: list[LineageEdge] = field(default_factory=list)


@dataclass(frozen=True)
class SourceId:
    """Wrapper around the (company_id, source_id) compound key.

    ``source_id`` is a UUID for external/filedrop/evidence; for
    conversation, ``source_id`` is deterministically derived from
    ``(company_id, channel_id)``.
    """

    company_id: UUID
    source_id: UUID


__all__ = [
    "Capability",
    "Change",
    "Classification",
    "ClassificationHint",
    "ClassificationUpdate",
    "DriftReport",
    "LineageEdge",
    "LineageReport",
    "Profile",
    "ResourceProposal",
    "SourceFamily",
    "SourceId",
    "StalenessReport",
]
