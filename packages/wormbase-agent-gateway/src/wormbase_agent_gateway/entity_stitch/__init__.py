"""L8 lake-side cross-source entity stitching subpackage.

Public surface for the L8 Compounding axis:

  * :data:`EntityKind` — strict 8-value Literal covering the canonical
    entity classes the L8 strategy bank can bridge across sources
    (person / organization / transaction / product / event / location /
    session / other).
  * :class:`ProposedEntityStitch` — strategy output dataclass; folds
    1:1 onto an ``entity_stitch_proposed`` ledger entry.
  * :class:`EntityStitchStrategy` — Protocol every strategy implements
    (runtime_checkable).
  * :func:`make_stitch_id` — deterministic, **order-independent**
    SHA-256 hash for proposal identity (omits strategy — diverges from
    L6's :func:`make_classification_id` so cross-strategy proposals on
    the same pair merge into one row).
  * :class:`NameMatchEntityStrategy` — **the cross-axis chain**. Reuses
    L6's :class:`ConfirmedSemanticTypeReader` Protocol (second consumer
    of the same Protocol; L6 is the first). Plus fuzzy-name fallback.
  * :class:`SampleOverlapEntityStrategy` — reuses L7's
    :class:`SamplerProtocol`. Jaccard overlap of sampled values;
    honest-stub today (NoopSampler).
  * :class:`SchemaShapeEntityStrategy` — productive-today catch-all on
    bare catalog metadata; compares parent-table shapes (column count
    + name-set overlap).
  * :func:`make_composite_entity_stitch_service` — Optional-Effect
    Injection composition over the 3 strategies via
    :class:`LakeLoopComposite` (doctrine case 14 — **third lake-side
    axis built on the shared abstraction from day one**, after L5 and
    L6). ~15 LOC factory instead of a ~250 LOC custom composite class.

Sub-wave B (2026-06-07) ships these. Sub-wave C wires them through the
boot path (reuses L6's existing ``LedgerConfirmedSemanticTypeReader``
adapter — no new adapter to build); Sub-wave D ships the admin
``/lake/entity-stitch`` dashboard surface.

Reuse posture — L8 declares NO new Protocols. Two reuses:

  * :class:`wormbase_agent_gateway.column_classification.ConfirmedSemanticTypeReader`
    — second consumer (L6's strategy is the first).
  * :class:`wormbase_agent_gateway.lineage.SamplerProtocol`.

Cleanest Sub-wave B in the lake-side family.
"""
from __future__ import annotations

from .composite import make_composite_entity_stitch_service
from .protocol import (
    EntityKind,
    EntityStitchStrategy,
    ProposedEntityStitch,
    make_stitch_id,
)
from .strategies import (
    NameMatchEntityStrategy,
    SampleOverlapEntityStrategy,
    SchemaShapeEntityStrategy,
)

__all__ = [
    "EntityKind",
    "EntityStitchStrategy",
    "NameMatchEntityStrategy",
    "ProposedEntityStitch",
    "SampleOverlapEntityStrategy",
    "SchemaShapeEntityStrategy",
    "make_composite_entity_stitch_service",
    "make_stitch_id",
]
