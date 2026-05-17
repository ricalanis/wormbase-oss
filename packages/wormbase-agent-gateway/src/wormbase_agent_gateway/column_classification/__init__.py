"""L6 lake-side column-level governance classification subpackage.

Public surface for the L6 Compounding axis:

  * :data:`ClassificationLevel` — strict 5-value Literal covering the
    canonical governance levels (public / internal / confidential /
    pii / regulated).
  * :class:`ProposedColumnClassification` — strategy output dataclass;
    folds 1:1 onto a ``column_classification_proposed`` ledger entry.
  * :class:`ColumnClassificationStrategy` — Protocol every strategy
    implements (runtime_checkable).
  * :class:`ConfirmedSemanticTypeRecord` — minimum-coupling projection
    of an L5 confirmed semantic type (the field set L6 needs).
  * :class:`ConfirmedSemanticTypeReader` — **NEW cross-axis Protocol**
    (second instance after L4's :class:`LineageEdgeReader`). Owned by
    L6; fulfilled by an adapter in worm-core wiring (Sub-wave C).
  * :func:`make_classification_id` — deterministic SHA-256 hash for
    proposal identity (includes ``strategy`` — diverges from L5's
    :func:`make_type_id` so each strategy's per-column-per-level
    proposal is its own projection row).
  * :class:`SemanticTypeClassificationStrategy` — cross-axis chain;
    reads L5 confirmed types via :class:`ConfirmedSemanticTypeReader`
    and maps to classifications per spec §4.3.
  * :class:`NamingPatternClassificationStrategy` — productive-today
    regex over column names (credentials / regulated PII / explicit
    naming conventions).
  * :class:`DomainDefaultClassificationStrategy` — reads domain-pack
    classification_defaults via :class:`DomainDefaultReader` (consumer-
    owned Protocol — minimum coupling).
  * :class:`DomainDefaultReader` — Protocol for the
    :class:`DomainDefaultClassificationStrategy` upstream read.
  * :func:`make_composite_column_classification_service` — Optional-
    Effect Injection composition over the 3 strategies via
    :class:`LakeLoopComposite` (doctrine case 13 — **second lake-side
    axis built on the shared abstraction from day one**, after L5).
    ~15 LOC factory instead of a ~250 LOC custom composite class.

Sub-wave B (2026-06-06) ships these. Sub-wave C wires them through the
boot path with a concrete ``LedgerConfirmedSemanticTypeReader`` impl
(mirrors L4's ``LedgerLineageEdgeReader``); Sub-wave D ships the admin
``/lake/column-classification`` dashboard surface.
"""
from __future__ import annotations

from .composite import make_composite_column_classification_service
from .protocol import (
    ClassificationLevel,
    ColumnClassificationStrategy,
    ConfirmedClassificationReader,
    ConfirmedClassificationRecord,
    ConfirmedSemanticTypeReader,
    ConfirmedSemanticTypeRecord,
    ProposedColumnClassification,
    make_classification_id,
)
from .strategies import (
    DomainDefaultClassificationStrategy,
    DomainDefaultReader,
    NamingPatternClassificationStrategy,
    SemanticTypeClassificationStrategy,
)

__all__ = [
    "ClassificationLevel",
    "ColumnClassificationStrategy",
    "ConfirmedClassificationReader",
    "ConfirmedClassificationRecord",
    "ConfirmedSemanticTypeReader",
    "ConfirmedSemanticTypeRecord",
    "DomainDefaultClassificationStrategy",
    "DomainDefaultReader",
    "NamingPatternClassificationStrategy",
    "ProposedColumnClassification",
    "SemanticTypeClassificationStrategy",
    "make_classification_id",
    "make_composite_column_classification_service",
]
