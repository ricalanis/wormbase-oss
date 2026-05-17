"""EvidenceSource — Maintainer-facing wrapper over projection_notebooks + projection_data_products.

Per spike §8 C5: no acquisition surface. Ingest happens upstream via
``emit_data_product_*`` / ``emit_notebook_*`` / ``emit_kpi_proposed``
written by ``data_product_actions``, the autoresearch loop, and
dashboard write paths. EvidenceSource only implements
MaintainableSource — its read methods are wrappers over the projection
tables.

There is intentionally no ``discover``, ``profile``, or ``sample``.
``isinstance(src, AcquirableSource)`` returns False.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from wormbase_ledger.schema import (
    projection_data_products,
    projection_notebooks,
)

from wormbase_lake_maintainer.types import (
    Classification,
    ClassificationUpdate,
    DriftReport,
    LineageReport,
    StalenessReport,
)


@dataclass
class EvidenceSource:
    """MaintainableSource for one tenant's evidence projections.

    One EvidenceSource per tenant covers all data-products + notebooks.
    Per-domain or per-owner scoping happens inside the Reactivities
    when needed.

    State fields:
    - ``baseline_data_product_count`` / ``baseline_notebook_count`` —
      drift heuristic baselines. Drift = "evidence pool shrank
      unexpectedly" (a data product was retired without a successor).
    - ``staleness_sla_hours`` — gap between consecutive evidence
      publishes that flips stale=True.
    """

    id: UUID
    company_id: UUID
    classification: Classification
    domain: UUID | None
    owner: UUID | None
    engine: AsyncEngine

    baseline_data_product_count: int | None = None
    baseline_notebook_count: int | None = None
    staleness_sla_hours: float = 24.0

    family: Literal["evidence"] = "evidence"
    # Evidence is always WormBase-curated (no upstream catalog).
    source_mode: Literal["wormbase_owned", "upstream_mirror"] = "wormbase_owned"

    async def _last_evidence_seen(self) -> datetime | None:
        """Newest data_product publish timestamp.

        SQLite/aiosqlite drops tzinfo on DateTime(timezone=True) round-trip;
        Postgres preserves it. The column is canonically UTC, so naive→UTC
        coercion is sound (no-op on Postgres).
        """
        async with self.engine.connect() as conn:
            stmt = (
                select(projection_data_products.c.generated_at)
                .where(projection_data_products.c.tenant_id == self.company_id)
                .order_by(desc(projection_data_products.c.generated_at))
                .limit(1)
            )
            row = (await conn.execute(stmt)).first()
            if row and row[0]:
                last_seen = row[0]
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=UTC)
                return last_seen
        return None

    async def _evidence_counts(self) -> tuple[int, int]:
        """Return (data_product_count, notebook_count) for the tenant."""
        async with self.engine.connect() as conn:
            dp_count = await conn.scalar(
                select(func.count())
                .select_from(projection_data_products)
                .where(projection_data_products.c.tenant_id == self.company_id)
            )
            nb_count = await conn.scalar(
                select(func.count())
                .select_from(projection_notebooks)
                .where(projection_notebooks.c.tenant_id == self.company_id)
            )
        return int(dp_count or 0), int(nb_count or 0)

    # ------------------------------------------------------------------
    # MaintainableSource impl
    # ------------------------------------------------------------------

    async def detect_drift(self) -> DriftReport:
        """Drift = evidence pool shrank below baseline."""
        dp_count, nb_count = await self._evidence_counts()
        if (
            self.baseline_data_product_count is None
            and self.baseline_notebook_count is None
        ):
            return DriftReport(drifted=False, reason="no baseline yet")
        baseline_dp = self.baseline_data_product_count or 0
        baseline_nb = self.baseline_notebook_count or 0
        if dp_count < baseline_dp or nb_count < baseline_nb:
            return DriftReport(
                drifted=True,
                reason=(
                    f"evidence pool shrank: data_products {baseline_dp} → {dp_count}, "
                    f"notebooks {baseline_nb} → {nb_count}"
                ),
            )
        return DriftReport(drifted=False, reason="evidence pool stable or growing")

    async def refresh_classification(self) -> ClassificationUpdate:
        return ClassificationUpdate(
            updated=False,
            classification=self.classification,
            previous_classification=self.classification,
            reason="evidence classification is set per-artifact at publish time (v1)",
        )

    async def staleness_signal(self) -> StalenessReport:
        last_seen = await self._last_evidence_seen()
        if last_seen is None:
            return StalenessReport(
                stale=True, last_seen=None,
                sla_hours=self.staleness_sla_hours,
            )
        age = datetime.now(UTC) - last_seen
        return StalenessReport(
            stale=age > timedelta(hours=self.staleness_sla_hours),
            last_seen=last_seen,
            sla_hours=self.staleness_sla_hours,
        )

    async def lineage_health(self) -> LineageReport:
        """v1: lineage check requires walking notebook→source→KPI edges.

        That walk lives in autoresearch_loop.py today. Block F's
        LineageHealthReactivity wraps it; v1 baseline returns healthy.
        """
        return LineageReport(healthy=True, broken_edges=[])


__all__ = ["EvidenceSource"]
