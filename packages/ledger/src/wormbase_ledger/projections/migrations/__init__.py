"""Versioned schema migrations for the projection_* tables.

Each migration is a class with ``version`` (monotonic, no gaps),
``description`` (human-readable), and ``up(conn)`` (idempotent
forward step). The runner in
``wormbase_ledger.projections.migrate`` applies pending migrations
in order on every worm-core boot.

Adding a migration:
    1. Create ``vNNN_<short_name>.py`` with a single ``Migration``
       class. ``vNNN`` must be the next integer in the series.
    2. Append the class instance to ``MIGRATIONS`` below.
    3. Update ``schema.py`` so future fresh installs replay through
       the metadata.create_all path consistently — though the
       migration runner is the source of truth.

Idempotency invariants every migration must satisfy:
    - re-running an already-applied migration produces no change
      (CREATE TABLE IF NOT EXISTS, ADD COLUMN guarded by a presence
      check, etc.)
    - the migration is a single forward step; downgrades are not
      supported (see ``migrate.py`` docstring)
"""

from __future__ import annotations

from typing import Protocol

from wormbase_ledger.projections.migrations.v001_initial import (
    Migration as V001InitialMigration,
)
from wormbase_ledger.projections.migrations.v002_setup_mode import (
    Migration as V002SetupModeMigration,
)
from wormbase_ledger.projections.migrations.v003_source_last_seen import (
    Migration as V003SourceLastSeenMigration,
)
from wormbase_ledger.projections.migrations.v004_projection_conversations import (
    Migration as V004ProjectionConversationsMigration,
)
from wormbase_ledger.projections.migrations.v005_projection_channels import (
    Migration as V005ProjectionChannelsMigration,
)
from wormbase_ledger.projections.migrations.v006_projection_tenants import (
    Migration as V006ProjectionTenantsMigration,
)
from wormbase_ledger.projections.migrations.v007_projection_topics import (
    Migration as V007ProjectionTopicsMigration,
)
from wormbase_ledger.projections.migrations.v008_external_catalog import (
    Migration as V008ExternalCatalogMigration,
)
from wormbase_ledger.projections.migrations.v009_external_lineage import (
    Migration as V009ExternalLineageMigration,
)
from wormbase_ledger.projections.migrations.v010_external_policy import (
    Migration as V010ExternalPolicyMigration,
)
from wormbase_ledger.projections.migrations.v011_external_metric import (
    Migration as V011ExternalMetricMigration,
)
from wormbase_ledger.projections.migrations.v012_projection_agents import (
    Migration as V012ProjectionAgentsMigration,
)
from wormbase_ledger.projections.migrations.v013_projection_agent_grants import (
    Migration as V013ProjectionAgentGrantsMigration,
)
from wormbase_ledger.projections.migrations.v014_projection_agent_queries import (
    Migration as V014ProjectionAgentQueriesMigration,
)
from wormbase_ledger.projections.migrations.v015_projection_credentials import (
    Migration as V015ProjectionCredentialsMigration,
)
from wormbase_ledger.projections.migrations.v016_projection_query_outcomes import (
    Migration as V016ProjectionQueryOutcomesMigration,
)
from wormbase_ledger.projections.migrations.v017_projection_query_templates import (
    Migration as V017ProjectionQueryTemplatesMigration,
)
from wormbase_ledger.projections.migrations.v018_resize_embeddings_to_768 import (
    Migration as V018ResizeEmbeddingsTo768Migration,
)
from wormbase_ledger.projections.migrations.v019_hnsw_index_query_outcomes import (
    Migration as V019HNSWIndexQueryOutcomesMigration,
)
from wormbase_ledger.projections.migrations.v020_dim_flexible_embedding import (
    Migration as V020DimFlexibleEmbeddingMigration,
)
from wormbase_ledger.projections.migrations.v021_projection_lineage_edges import (
    Migration as V021ProjectionLineageEdgesMigration,
)
from wormbase_ledger.projections.migrations.v022_projection_quality_checks import (
    Migration as V022ProjectionQualityChecksMigration,
)
from wormbase_ledger.projections.migrations.v023_projection_schema_impacts import (
    Migration as V023ProjectionSchemaImpactsMigration,
)
from wormbase_ledger.projections.migrations.v024_projection_semantic_types import (
    Migration as V024ProjectionSemanticTypesMigration,
)
from wormbase_ledger.projections.migrations.v025_projection_column_classifications import (
    Migration as V025ProjectionColumnClassificationsMigration,
)
from wormbase_ledger.projections.migrations.v026_projection_entity_stitches import (
    Migration as V026ProjectionEntityStitchesMigration,
)
from wormbase_ledger.projections.migrations.v027_projection_source_candidates import (
    Migration as V027ProjectionSourceCandidatesMigration,
)
from wormbase_ledger.projections.migrations.v028_projection_catalog_drifts import (
    Migration as V028ProjectionCatalogDriftsMigration,
)
from wormbase_ledger.projections.migrations.v029_projection_catalog_tables import (
    Migration as V029ProjectionCatalogTablesMigration,
)


class Migration(Protocol):
    """Protocol every migration class implements.

    ``version`` is monotonic and gap-free across the MIGRATIONS list.
    ``description`` is a short human-readable string surfaced in logs.
    ``up`` is the forward step; it MUST be idempotent so a partial
    apply followed by a re-run lands cleanly.
    """

    version: int
    description: str

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        ...


# Canonical migration list — append-only. Order is enforced by the
# runner; gaps and duplicates raise on apply.
MIGRATIONS: list[Migration] = [
    V001InitialMigration(),
    V002SetupModeMigration(),
    V003SourceLastSeenMigration(),
    V004ProjectionConversationsMigration(),
    V005ProjectionChannelsMigration(),
    V006ProjectionTenantsMigration(),
    V007ProjectionTopicsMigration(),
    V008ExternalCatalogMigration(),
    V009ExternalLineageMigration(),
    V010ExternalPolicyMigration(),
    V011ExternalMetricMigration(),
    V012ProjectionAgentsMigration(),
    V013ProjectionAgentGrantsMigration(),
    V014ProjectionAgentQueriesMigration(),
    V015ProjectionCredentialsMigration(),
    V016ProjectionQueryOutcomesMigration(),
    V017ProjectionQueryTemplatesMigration(),
    V018ResizeEmbeddingsTo768Migration(),
    V019HNSWIndexQueryOutcomesMigration(),
    V020DimFlexibleEmbeddingMigration(),
    V021ProjectionLineageEdgesMigration(),
    V022ProjectionQualityChecksMigration(),
    V023ProjectionSchemaImpactsMigration(),
    V024ProjectionSemanticTypesMigration(),
    V025ProjectionColumnClassificationsMigration(),
    V026ProjectionEntityStitchesMigration(),
    V027ProjectionSourceCandidatesMigration(),
    V028ProjectionCatalogDriftsMigration(),
    V029ProjectionCatalogTablesMigration(),
]


__all__ = ["MIGRATIONS", "Migration"]
