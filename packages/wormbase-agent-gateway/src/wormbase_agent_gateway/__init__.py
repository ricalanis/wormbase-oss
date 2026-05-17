"""WormBase agent-gateway — control plane for governed MCP access.

Public surface re-exports follow the lake-maintainer template:

  * ``wire_agent_gateway_for_install`` — boot wire (5th install-scope
    wire after Wave 1 cleanup-1a). Registers the agent-gateway
    Reactivities into the W5a registry.
  * ``Compounding`` — v2.B Phase 1 parameterised W5a Reactivity
    primitive that closes journey Seam #4. The two original Reactivities
    are constructed from it; v2.B Phase 2 added three new axes
    (failures-as-bad-patterns, gaps-as-escalations,
    consumption-as-recommendations) by instantiating the same primitive.
  * ``OutcomeToTemplatePromotionReactivity`` — the §4.5 compounding-
    layer Reactivity that promotes high-quality outcome clusters to
    durable query templates. Built on ``Compounding``.
  * ``QueryOutcomeToDataProductReactivity`` — W3.2 Hole #8 sister
    Reactivity that promotes individual high-quality outcomes to
    ``data_product_proposed`` entries (per-outcome, not clustered).
    Built on ``Compounding``.
  * ``make_query_failure_to_bad_pattern_reactivity`` — v2.B Phase 2
    Axis 3. Clusters of repeated failed/unhelpful outcomes →
    ``bad_pattern_proposed`` entries the next agent's semantic search
    deprioritizes.
  * ``make_semantic_gap_to_escalation_reactivity`` — v2.B Phase 2
    Axis 4. ``semantic_gap_proposed`` entries unresolved >7d →
    ``semantic_gap_escalated`` entries surfaced on the admin
    metric-proposal queue.
  * ``make_data_product_consumption_to_recommendation_reactivity`` —
    v2.B Phase 2 Axis 5. Multi-agent consumption clusters →
    ``data_product_recommended`` entries surfaced on ``/data-products``.
  * ``make_agent_gateway_reactivities`` — factory returning the list
    of Reactivities the wire registers (5 entries post-Phase-2: 2
    original + 3 v2.B Phase 2 axes); useful for tests + bespoke
    deployments.
"""
from __future__ import annotations

from .catalog_drift import (
    AcknowledgedDriftReader,
    AcknowledgedDriftRecord,
    CatalogDriftStrategy,
    CatalogSnapshot,
    CatalogSnapshotReader,
    ColumnSetDriftStrategy,
    ColumnTypeDriftStrategy,
    ProposedCatalogDrift,
    TableSetDriftStrategy,
    make_composite_catalog_drift_service,
    make_drift_id,
)
# NOTE: ``CatalogTable`` and ``CatalogColumn`` are intentionally NOT
# re-exported here — the lineage subpackage's :class:`CatalogTable`
# already lives under this name on the gateway top-level surface (with
# a different field shape: ``columns: tuple[str, ...]`` + ``source_kind``).
# Callers needing L2's snapshot-side records import from
# :mod:`wormbase_agent_gateway.catalog_drift` directly to avoid the
# name collision.
from .column_classification import (
    ClassificationLevel,
    ColumnClassificationStrategy,
    ConfirmedSemanticTypeReader,
    ConfirmedSemanticTypeRecord,
    DomainDefaultClassificationStrategy,
    DomainDefaultReader,
    NamingPatternClassificationStrategy,
    ProposedColumnClassification,
    SemanticTypeClassificationStrategy,
    make_classification_id,
    make_composite_column_classification_service,
)
from .entity_stitch import (
    EntityKind,
    EntityStitchStrategy,
    NameMatchEntityStrategy,
    ProposedEntityStitch,
    SampleOverlapEntityStrategy,
    SchemaShapeEntityStrategy,
    make_composite_entity_stitch_service,
    make_stitch_id,
)
from .lake_loop import (
    LakeLoopComposite,
    LakeLoopProposal,
    LakeLoopStrategy,
    default_cluster_merge,
    default_merge_winner,
)
from .lineage import (
    CatalogTable,
    CompositeLineageInferenceService,
    DbtManifestReader,
    DbtManifestStrategy,
    InferredEdge,
    LineageInferenceConfig,
    LineageInferenceService,
    NamingHeuristicStrategy,
    SampleOverlapStrategy,
    SamplerProtocol,
    make_edge_id,
)
from .quality import (
    CompositeQualityProposalService,
    DbtTestReader,
    DbtTestsStrategy,
    HistoricalStatsReader,
    HistoricalStatsStrategy,
    ProposedQualityCheck,
    QualityCheckKind,
    QualityCheckProposalService,
    SchemaPatternStrategy,
    make_check_id,
)
from .reactivities import (
    Compounding,
    OutcomeToTemplatePromotionReactivity,
    QueryOutcomeToDataProductReactivity,
    make_agent_gateway_reactivities,
    make_catalog_drift_discovery_reactivity,
    make_column_classification_discovery_reactivity,
    make_data_product_consumption_to_recommendation_reactivity,
    make_entity_stitch_discovery_reactivity,
    make_fingerprint_discovery_reactivity,
    make_lineage_discovery_reactivity,
    make_outcome_to_template_promotion_reactivity,
    make_quality_discovery_reactivity,
    make_query_failure_to_bad_pattern_reactivity,
    make_schema_impact_discovery_reactivity,
    make_semantic_gap_to_escalation_reactivity,
)
from .schema_impact import (
    ChangeKind,
    ColumnChange,
    CompositeSchemaImpactService,
    DbtTestImpactStrategy,
    ImpactKind,
    LineageEdgeImpactStrategy,
    LineageEdgeReader,
    LineageEdgeRecord,
    ProposedImpact,
    SchemaImpactService,
    TypeCoercionImpactStrategy,
    make_impact_id,
)
from .semantic_type import (
    ColumnNameFingerprintStrategy,
    DistributionFingerprintStrategy,
    FingerprintStrategy,
    ProposedSemanticType,
    SemanticType,
    ValuePatternFingerprintStrategy,
    make_composite_semantic_type_service,
    make_type_id,
)
from .tenancy import (
    InMemoryQuotaTracker,
    InMemoryRateLimiter,
    InMemoryTenantRouter,
    IsolatedTenantContext,
    LedgerQuotaTracker,
    QuotaConsumedEmitter,
    QuotaTracker,
    RateLimiter,
    StaticTenantEngineRegistry,
    TenantContext,
    TenantEngineRegistry,
    TenantQuotaExceededError,
    TenantRateLimitedError,
    TenantResolveError,
    TenantRevokedError,
    TenantRouter,
    TenantUnknownError,
    is_multi_tenant_mcp_enabled,
    is_tenant_quota_ledger_emission_enabled,
    resolve_default_quota_count_threshold,
    resolve_default_quota_per_day,
    resolve_default_quota_time_threshold_seconds,
    resolve_default_rate_limit_per_min,
)
from .wires import wire_agent_gateway_for_install

__all__ = [
    "AcknowledgedDriftReader",
    "AcknowledgedDriftRecord",
    "CatalogDriftStrategy",
    "CatalogSnapshot",
    "CatalogSnapshotReader",
    "CatalogTable",
    "ChangeKind",
    "ClassificationLevel",
    "ColumnChange",
    "ColumnClassificationStrategy",
    "ColumnNameFingerprintStrategy",
    "ColumnSetDriftStrategy",
    "ColumnTypeDriftStrategy",
    "Compounding",
    "CompositeLineageInferenceService",
    "CompositeQualityProposalService",
    "CompositeSchemaImpactService",
    "ConfirmedSemanticTypeReader",
    "ConfirmedSemanticTypeRecord",
    "DbtManifestReader",
    "DbtManifestStrategy",
    "DbtTestImpactStrategy",
    "DbtTestReader",
    "DbtTestsStrategy",
    "DistributionFingerprintStrategy",
    "DomainDefaultClassificationStrategy",
    "DomainDefaultReader",
    "EntityKind",
    "EntityStitchStrategy",
    "FingerprintStrategy",
    "HistoricalStatsReader",
    "HistoricalStatsStrategy",
    "ImpactKind",
    "InMemoryQuotaTracker",
    "InMemoryRateLimiter",
    "InMemoryTenantRouter",
    "InferredEdge",
    "IsolatedTenantContext",
    "LakeLoopComposite",
    "LakeLoopProposal",
    "LakeLoopStrategy",
    "LedgerQuotaTracker",
    "LineageEdgeImpactStrategy",
    "LineageEdgeReader",
    "LineageEdgeRecord",
    "LineageInferenceConfig",
    "LineageInferenceService",
    "NameMatchEntityStrategy",
    "NamingHeuristicStrategy",
    "NamingPatternClassificationStrategy",
    "OutcomeToTemplatePromotionReactivity",
    "ProposedCatalogDrift",
    "ProposedColumnClassification",
    "ProposedEntityStitch",
    "ProposedImpact",
    "ProposedQualityCheck",
    "ProposedSemanticType",
    "QualityCheckKind",
    "QualityCheckProposalService",
    "QueryOutcomeToDataProductReactivity",
    "QuotaConsumedEmitter",
    "QuotaTracker",
    "RateLimiter",
    "SampleOverlapEntityStrategy",
    "SampleOverlapStrategy",
    "SamplerProtocol",
    "SchemaImpactService",
    "SchemaPatternStrategy",
    "SchemaShapeEntityStrategy",
    "SemanticType",
    "SemanticTypeClassificationStrategy",
    "StaticTenantEngineRegistry",
    "TableSetDriftStrategy",
    "TenantContext",
    "TenantEngineRegistry",
    "TenantQuotaExceededError",
    "TenantRateLimitedError",
    "TenantResolveError",
    "TenantRevokedError",
    "TenantRouter",
    "TenantUnknownError",
    "TypeCoercionImpactStrategy",
    "ValuePatternFingerprintStrategy",
    "default_cluster_merge",
    "default_merge_winner",
    "is_multi_tenant_mcp_enabled",
    "is_tenant_quota_ledger_emission_enabled",
    "make_agent_gateway_reactivities",
    "make_catalog_drift_discovery_reactivity",
    "make_check_id",
    "make_classification_id",
    "make_column_classification_discovery_reactivity",
    "make_composite_catalog_drift_service",
    "make_composite_column_classification_service",
    "make_composite_entity_stitch_service",
    "make_composite_semantic_type_service",
    "make_data_product_consumption_to_recommendation_reactivity",
    "make_drift_id",
    "make_edge_id",
    "make_entity_stitch_discovery_reactivity",
    "make_fingerprint_discovery_reactivity",
    "make_impact_id",
    "make_lineage_discovery_reactivity",
    "make_outcome_to_template_promotion_reactivity",
    "make_quality_discovery_reactivity",
    "make_query_failure_to_bad_pattern_reactivity",
    "make_schema_impact_discovery_reactivity",
    "make_semantic_gap_to_escalation_reactivity",
    "make_stitch_id",
    "make_type_id",
    "resolve_default_quota_count_threshold",
    "resolve_default_quota_per_day",
    "resolve_default_quota_time_threshold_seconds",
    "resolve_default_rate_limit_per_min",
    "wire_agent_gateway_for_install",
]
