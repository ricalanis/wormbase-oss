"""wormbase_ledger — append-only hash-chained event ledger.

Public API (stable across Wave 2):
    Ledger             — async DB-backed implementation
    InMemoryLedger     — pytest fixture / in-process implementation
    EntryType          — alias = str; canonical values are KIND_REGISTRY keys
    write_primitive    — atomic propose → execute → verify → resolve (low-level)
    KIND_REGISTRY      — kind → Pydantic payload model
    LedgerEntry        — the on-the-wire envelope
    KpiNode            — KPI tree projection contract (P3 writes; P4 reads)
    QUADRANT_VALUES    — tuple of the four quadrant strings
    Errors: HashChainBroken, WriteRolledBack, UnknownEntryType, VerifyFailed
"""

from __future__ import annotations

__version__ = "0.1.0"

from wormbase_ledger.entries import (
    KIND_REGISTRY,
    QUADRANT_VALUES,
    AgentEventDeliveredPayload,
    AgentMetadataUpdatedPayload,
    AgentSubscriptionCreatedPayload,
    AgentSubscriptionRevokedPayload,
    CatalogColumnSpec,
    CatalogDriftAcknowledgedPayload,
    CatalogDriftKind,
    CatalogDriftProposedPayload,
    CatalogDriftRejectReason,
    CatalogDriftRejectedPayload,
    CatalogTableImportedPayload,
    ClockTickPayload,
    ColumnClassificationConfirmedPayload,
    ColumnClassificationProposedPayload,
    ColumnClassificationRejectedPayload,
    ConversationSyncPayload,
    DomainPackSelectedPayload,
    EntityStitchConfirmedPayload,
    EntityStitchProposedPayload,
    EntityStitchRejectedPayload,
    LedgerEntry,
    SourceCandidateProposedPayload,
    SourceCandidatePromotedPayload,
    SourceCandidateRejectedPayload,
    SourceCandidateRejectReason,
    make_candidate_id,
    make_drift_id,
    LineageEdgeConfirmedPayload,
    LineageEdgeProposedPayload,
    LineageEdgeRejectedPayload,
    PersonInvitedPayload,
    Quadrant,
    QualityCheckConfirmedPayload,
    QualityCheckProposedPayload,
    QualityCheckRejectedPayload,
    SchemaImpactConfirmedPayload,
    SchemaImpactProposedPayload,
    SchemaImpactRejectedPayload,
    SemanticTypeConfirmedPayload,
    SemanticTypeProposedPayload,
    SemanticTypeRejectedPayload,
    SpeechAct,
    TenantEngineRegisteredPayload,
    TenantQuotaConsumedPayload,
)
from wormbase_ledger.errors import (
    HashChainBroken,
    LedgerError,
    UnknownEntryType,
    VerifyFailed,
    WriteRolledBack,
)
from wormbase_ledger.ledger_api import InMemoryLedger, Ledger
from wormbase_ledger.projections import KpiNode, Projections
from wormbase_ledger.replay import ReplaySnapshot, replay
from wormbase_ledger.verify import VerifyReport, verify_company_chain
from wormbase_ledger.write_primitive import WriteResult, write_primitive

# String alias used throughout the codebase. Canonical values live in
# `KIND_REGISTRY.keys()`; we keep this as `str` so consumers can use plain
# string literals without importing an enum.
EntryType = str

__all__ = [
    "KIND_REGISTRY",
    "QUADRANT_VALUES",
    "AgentEventDeliveredPayload",
    "AgentMetadataUpdatedPayload",
    "AgentSubscriptionCreatedPayload",
    "AgentSubscriptionRevokedPayload",
    "CatalogColumnSpec",
    "CatalogDriftAcknowledgedPayload",
    "CatalogDriftKind",
    "CatalogDriftProposedPayload",
    "CatalogDriftRejectReason",
    "CatalogDriftRejectedPayload",
    "CatalogTableImportedPayload",
    "ClockTickPayload",
    "ColumnClassificationConfirmedPayload",
    "ColumnClassificationProposedPayload",
    "ColumnClassificationRejectedPayload",
    "ConversationSyncPayload",
    "DomainPackSelectedPayload",
    "EntityStitchConfirmedPayload",
    "EntityStitchProposedPayload",
    "EntityStitchRejectedPayload",
    "EntryType",
    "HashChainBroken",
    "InMemoryLedger",
    "KpiNode",
    "Ledger",
    "LedgerEntry",
    "LedgerError",
    "LineageEdgeConfirmedPayload",
    "LineageEdgeProposedPayload",
    "LineageEdgeRejectedPayload",
    "PersonInvitedPayload",
    "Projections",
    "Quadrant",
    "QualityCheckConfirmedPayload",
    "QualityCheckProposedPayload",
    "QualityCheckRejectedPayload",
    "ReplaySnapshot",
    "SchemaImpactConfirmedPayload",
    "SchemaImpactProposedPayload",
    "SchemaImpactRejectedPayload",
    "SemanticTypeConfirmedPayload",
    "SemanticTypeProposedPayload",
    "SemanticTypeRejectedPayload",
    "SourceCandidateProposedPayload",
    "SourceCandidatePromotedPayload",
    "SourceCandidateRejectedPayload",
    "SourceCandidateRejectReason",
    "SpeechAct",
    "TenantEngineRegisteredPayload",
    "TenantQuotaConsumedPayload",
    "UnknownEntryType",
    "VerifyFailed",
    "VerifyReport",
    "WriteResult",
    "WriteRolledBack",
    "__version__",
    "make_candidate_id",
    "make_drift_id",
    "replay",
    "verify_company_chain",
    "write_primitive",
]
