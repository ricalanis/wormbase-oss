"""L3 lake-side lineage-discovery subpackage.

Public surface for the L3 Compounding axis:

  * :class:`LineageInferenceService` — Protocol every strategy + the
    composite implements.
  * :class:`InferredEdge` — strategy output dataclass; folds 1:1 onto
    a ``lineage_edge_proposed`` ledger entry.
  * :class:`CatalogTable` — strategy input dataclass.
  * :class:`LineageInferenceConfig` — frozen tunables bundle.
  * :func:`make_edge_id` — deterministic SHA-256 hash for edge identity.
  * :class:`NamingHeuristicStrategy` — metadata-only column-name match.
  * :class:`SampleOverlapStrategy` — Jaccard similarity of sampled
    values; requires an injected :class:`SamplerProtocol`.
  * :class:`DbtManifestStrategy` — manifest ``ref()``/``source()`` lift;
    requires an injected :class:`DbtManifestReader`.
  * :class:`CompositeLineageInferenceService` — Optional-Effect
    Injection composition over the 3 strategies (doctrine case 9).

Sub-wave B (2026-05-29) ships these. Sub-wave C wires them through the
boot path; Sub-wave D ships the admin dashboard surface.
"""
from __future__ import annotations

from .composite import CompositeLineageInferenceService
from .protocol import (
    CatalogTable,
    InferredEdge,
    LineageInferenceConfig,
    LineageInferenceService,
    make_edge_id,
)
from .strategies import (
    DbtManifestReader,
    DbtManifestStrategy,
    NamingHeuristicStrategy,
    SampleOverlapStrategy,
    SamplerProtocol,
)

__all__ = [
    "CatalogTable",
    "CompositeLineageInferenceService",
    "DbtManifestReader",
    "DbtManifestStrategy",
    "InferredEdge",
    "LineageInferenceConfig",
    "LineageInferenceService",
    "NamingHeuristicStrategy",
    "SampleOverlapStrategy",
    "SamplerProtocol",
    "make_edge_id",
]
