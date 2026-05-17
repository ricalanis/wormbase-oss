"""L5 lake-side semantic-type fingerprinting subpackage.

Public surface for the L5 Compounding axis:

  * :data:`SemanticType` — strict 19-value Literal covering the
    canonical semantic-type taxonomy (identity / temporal / identifiers
    / geo-locale / PII / metric / catch-all).
  * :class:`ProposedSemanticType` — strategy output dataclass; folds
    1:1 onto a ``semantic_type_proposed`` ledger entry.
  * :class:`FingerprintStrategy` — Protocol every strategy implements
    (runtime_checkable).
  * :func:`make_type_id` — deterministic SHA-256 hash for proposal
    identity.
  * :class:`ColumnNameFingerprintStrategy` — productive-today regex
    over column names (30-40 patterns).
  * :class:`ValuePatternFingerprintStrategy` — value-pattern regex over
    sampled values via L7's :class:`SamplerProtocol` (reused, no new
    cross-axis Protocol).
  * :class:`DistributionFingerprintStrategy` — column-level statistical
    heuristics via L7's :class:`HistoricalStatsReader` (reused).
  * :func:`make_composite_semantic_type_service` — Optional-Effect
    Injection composition over the 3 strategies via
    :class:`LakeLoopComposite` (doctrine case 12). ~15 LOC factory
    instead of a ~250 LOC custom composite class — first lake-side
    axis to use the shared abstraction from day one.

Sub-wave B (2026-06-05) ships these. Sub-wave C wires them through
the boot path with concrete reader impls; Sub-wave D ships the admin
``/lake/semantic-types`` dashboard surface.
"""
from __future__ import annotations

from .composite import make_composite_semantic_type_service
from .protocol import (
    FingerprintStrategy,
    ProposedSemanticType,
    SemanticType,
    make_type_id,
)
from .strategies import (
    ColumnNameFingerprintStrategy,
    DistributionFingerprintStrategy,
    ValuePatternFingerprintStrategy,
)

__all__ = [
    "ColumnNameFingerprintStrategy",
    "DistributionFingerprintStrategy",
    "FingerprintStrategy",
    "ProposedSemanticType",
    "SemanticType",
    "ValuePatternFingerprintStrategy",
    "make_composite_semantic_type_service",
    "make_type_id",
]
