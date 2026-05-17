"""Shared types for the lake-surfaces Protocols (SurfaceDriver + AcquirableSource + MaintainableSource).

Every type here is a frozen dataclass — surface drivers are pure
functions of (secrets, handle, resource_id), and the input/output
shapes need to be hashable for trace-replay determinism.

Per ADR-0013 / ADR-0003 (2026-05-17 addendum), the maintenance types
(``DriftReport``, ``ClassificationUpdate``, ``StalenessReport``,
``LineageReport``, ``SourceId``, ``SourceFamily``, ``Classification``)
live here so the Protocols home (lake-surfaces) doesn't depend back
on lake-maintainer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

# Capability + ClassificationHint are exposed as plain string aliases
# for documentary convenience. The registry does not enforce the
# allowed values; that's per-surface-driver documentation.
Capability = str  # "discover" | "profile" | "sample" | "watch"
ClassificationHint = str  # "pii" | "confidential" | "regulated" | ...

# ConnectorStatus drives capability honesty in the dashboard's lake-surface
# picker (D4). Production: every SurfaceDriver method is wired; preview: some
# methods work but others stub/skeletal; coming_soon: skeleton only —
# discover returns [], profile/sample/watch raise NotImplementedError.
#
# Name retained as ``ConnectorStatus`` for code reuse; the user-facing
# vocabulary is "surface status."
ConnectorStatus = Literal["production", "preview", "coming_soon"]

# Lake-side source-family enum: the four kinds of surface.
SourceFamily = Literal["external", "filedrop", "conversation", "evidence"]
Classification = Literal["public", "internal", "confidential", "pii", "regulated"]


@dataclass(frozen=True)
class SecretBundle:
    """Opaque container for connector credentials. KMS-wrapped at rest.

    The ``payload`` dict is connector-specific: a Postgres connector may
    expect ``{"dsn": ...}`` while a Stripe connector may expect
    ``{"api_key": ...}``. The `Connector.authenticate` method validates
    the shape and raises ValueError if the bundle is malformed.

    Secrets are NEVER logged. The registry, the HTTP write-API, and the
    ledger emit redacted projections only.
    """

    payload: dict[str, Any]


@dataclass(frozen=True)
class AuthHandle:
    """Returned by :meth:`Connector.authenticate`. Used in subsequent calls.

    ``handle_id`` is a stable, non-secret identifier the connector can
    use to resolve runtime state (e.g. a connection-pool key, a session
    cookie cache, a thread-local boto client). ``extra`` is a free-form
    bag for connector-internal state — never logged, never serialized
    to the ledger.
    """

    connector_kind: str
    handle_id: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceProposal:
    """A resource discovered by :meth:`Connector.discover`.

    ``resource_id`` is connector-internal but stable across calls —
    e.g. a fully-qualified Postgres `schema.table`, an S3 object key,
    a Stripe object name like ``charges``. The source-builder uses
    this id to call subsequent ``profile``/``sample``/``watch``.
    """

    resource_id: str
    name: str
    kind: str  # "table" | "file" | "endpoint" | ...
    classification_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    """Result of :meth:`Connector.profile`.

    ``schema_hash`` is a short stable digest of the ordered (column,
    dtype) pairs — used by the lake-builder to detect schema drift
    between profile calls.
    """

    row_count: int | None
    column_count: int | None
    columns: list[dict[str, Any]]
    schema_hash: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Change:
    """Streaming change record from :meth:`Connector.watch`.

    Most day-one connectors do not implement watch; those that do
    yield ``Change`` records for the lake-builder's CDC ingestion.
    """

    resource_id: str
    seq: int
    kind: str  # "insert" | "update" | "delete"
    payload: dict[str, Any]


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
    "AuthHandle",
    "Capability",
    "Change",
    "Classification",
    "ClassificationHint",
    "ClassificationUpdate",
    "ConnectorStatus",
    "DriftReport",
    "LineageEdge",
    "LineageReport",
    "Profile",
    "ResourceProposal",
    "SecretBundle",
    "SourceFamily",
    "SourceId",
    "StalenessReport",
]
