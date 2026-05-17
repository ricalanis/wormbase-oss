"""PostgresLakeStore — thin LakeStore over MedallionCascade + SQLAlchemy.

Per spike §6: the existing Postgres projection layer has no
PG-specific reach-throughs. This impl is the contract: writes
delegate to ``MedallionCascade._write_*``, reads come from the
live-mirror Tables in ``wormbase_ledger.schema``. A future DuckDB /
Iceberg port re-implements this single class.

Lives in lake-maintainer (not worm-core) for boundary reasons: the
package owns the ``LakeStore`` Protocol; this is its v1 reference impl.
The cascade dependency is injected at construction so we don't need
to import worm-core internals at module-load time.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from wormbase_ledger.schema import (
    projection_data_products,
    projection_sources,
)


@dataclass
class PostgresLakeStore:
    """v1 LakeStore impl. ~50 LOC.

    ``cascade`` is the existing ``wormbase_core.medallion.MedallionCascade``
    instance (injected — we don't import worm-core directly). Write
    methods delegate; read_layer maps a layer string to the appropriate
    projection table.
    """

    engine: AsyncEngine
    cascade: Any  # wormbase_core.medallion.MedallionCascade (duck-typed)

    async def write_bronze(
        self, *, company_id: UUID, source_id: UUID, profile: Any,
    ) -> None:
        await self.cascade._write_bronze(company_id, source_id, profile)

    async def write_silver(
        self,
        *,
        company_id: UUID,
        source_id: UUID,
        columns: list[Any],
        join_candidates: list[UUID],
    ) -> None:
        await self.cascade._write_silver(
            company_id, source_id, columns, join_candidates,
        )

    async def write_gold(
        self,
        *,
        company_id: UUID,
        source_id: UUID,
        gold: Any,
    ) -> None:
        await self.cascade._write_gold(company_id, source_id, gold)

    def read_layer(
        self,
        *,
        company_id: UUID,
        layer: Literal["bronze", "silver", "gold"],
        resource_id: str | None = None,
        n: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Read rows from a layer projection.

        Sync wrapper that returns an ``AsyncIterator`` — matches the
        ``LakeStore`` Protocol signature exactly (Protocol declares
        ``def`` returning ``AsyncIterator``, not ``async def``). The
        async-generator body lives in ``_read_layer_impl``; consumers
        write ``async for row in store.read_layer(...)`` either way.
        """
        return self._read_layer_impl(
            company_id=company_id,
            layer=layer,
            resource_id=resource_id,
            n=n,
        )

    async def _read_layer_impl(
        self,
        *,
        company_id: UUID,
        layer: Literal["bronze", "silver", "gold"],
        resource_id: str | None,
        n: int | None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Async-generator body for ``read_layer``.

        v1: bronze → projection_sources; gold → projection_data_products.
        Silver raises NotImplementedError — there is no separate silver
        projection in v1 and we prefer an explicit error over silently
        aliasing to bronze. A Phase 2 wave splits silver into its own
        projection if a real consumer appears.
        """
        if layer == "bronze":
            stmt = select(projection_sources).where(
                projection_sources.c.company_id == company_id,
            )
            if resource_id is not None:
                stmt = stmt.where(projection_sources.c.uri == resource_id)
            if n is not None:
                stmt = stmt.limit(n)
            async with self.engine.connect() as conn:
                result = await conn.execute(stmt)
                for row in result:
                    yield dict(row._mapping)
        elif layer == "silver":
            raise NotImplementedError(
                "silver: deferred to v1.5 — v1 folds silver metadata into "
                "projection_sources; no separate silver projection exists yet"
            )
        elif layer == "gold":
            stmt = select(projection_data_products).where(
                projection_data_products.c.tenant_id == company_id,
            )
            if n is not None:
                stmt = stmt.limit(n)
            async with self.engine.connect() as conn:
                result = await conn.execute(stmt)
                for row in result:
                    yield dict(row._mapping)
        else:
            raise ValueError(f"unknown layer: {layer!r}")


__all__ = ["PostgresLakeStore"]
