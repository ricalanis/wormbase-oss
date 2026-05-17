"""The three Protocols: AcquirableSource, MaintainableSource, LakeStore.

Per ADR-0013 (continuous lake philosophy) + ADR-0003 (2026-05-17
addendum), Protocols live here in lake-surfaces — they describe the
faces of the lake. The lake-maintainer package consumes them; it does
NOT define them.

Per spike §8 C1: split the Source contract in two. AcquirableSource is
the existing Connector-style Protocol lifted to a per-instance object;
only external + filedrop families implement it. MaintainableSource
carries the four maintenance methods and is implemented by all four
families. LakeMaintainer iterates the union typed as MaintainableSource.

Per spike §8 C2: ``watch()`` is NOT on AcquirableSource. Empirically
every existing surface driver returns an empty async iterator; CDC
moves to an optional capability flag if a real consumer ever appears.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from wormbase_lake_surfaces.types import (
    Classification,
    ClassificationUpdate,
    DriftReport,
    LineageReport,
    Profile,
    ResourceProposal,
    SourceFamily,
    StalenessReport,
)


@runtime_checkable
class AcquirableSource(Protocol):
    """A Source the LakeMaintainer can pull from (external + filedrop only).

    Per spike C3: external + filedrop collapse to one acquisition family
    — they share ``MedallionCascade.cascade()`` downstream of
    ``SourceBuilder``. The difference is ``family`` metadata, not
    Protocol surface.

    Implementations wrap a ``wormbase_lake_surfaces.SurfaceDriver``
    driver plus per-instance metadata (id, classification, domain,
    owner). The SurfaceDriver is the *driver*; AcquirableSource is the
    *instance*.
    """

    id: UUID
    family: Literal["external", "filedrop"]
    classification: Classification
    domain: UUID | None
    owner: UUID | None

    async def discover(self) -> list[ResourceProposal]: ...

    async def profile(self, resource_id: str) -> Profile: ...

    async def sample(self, resource_id: str, n: int) -> bytes: ...


@runtime_checkable
class MaintainableSource(Protocol):
    """A Source the LakeMaintainer can maintain (all four families).

    The four methods are exactly what each family needs but doesn't
    have a home for today. The maintainer composes these into Reactivity
    instances (see ``factory.make_maintenance_reactivities``) which
    register with W5a's existing ``ReactivityRegistry``.

    ``source_mode`` distinguishes the two acquisition postures (Wave 3
    Task 7, 2026-05-11): ``"wormbase_owned"`` sources are bronze/silver/
    gold curated end-to-end by WormBase (the default). ``"upstream_mirror"``
    sources are catalog-mirrored from an external authoritative source
    (dbt, Snowflake, etc.); these additionally register the
    catalog-mirror Reactivities via
    ``source_builder.on_source_connected``. Conversation + evidence
    families are always ``wormbase_owned``.
    """

    id: UUID
    family: SourceFamily
    source_mode: Literal["wormbase_owned", "upstream_mirror"]

    async def detect_drift(self) -> DriftReport: ...

    async def refresh_classification(self) -> ClassificationUpdate: ...

    async def staleness_signal(self) -> StalenessReport: ...

    async def lineage_health(self) -> LineageReport: ...


@runtime_checkable
class LakeStore(Protocol):
    """The substrate-swappable layer where bronze/silver/gold actually live.

    > CORRECTED 2026-05-03: write methods take the medallion-typed
    > payload classes (``BronzeProfile`` / ``InferredColumn`` /
    > ``GoldArtifact``) since those are what ``MedallionCascade._write_*``
    > actually accepts. The lake-surfaces ``Profile`` is a different
    > shape and lives upstream of this Protocol.

    v1 impl wraps existing ``MedallionCascade._write_bronze/silver/gold``
    + SQLAlchemy reads against ``projection_*`` tables. Future swaps
    (DuckDB, Iceberg, customer Snowflake) port these four methods; the
    rest of the package is substrate-agnostic.

    Per spike §6: the Postgres projection layer has no PG-specific
    reach-throughs (verified by grep); the Protocol surface stays small
    enough to re-implement against a different store as a port.
    """

    async def write_bronze(
        self,
        *,
        company_id: UUID,
        source_id: UUID,
        profile: Any,  # BronzeProfile (lazy import to avoid worm-core dep at protocol layer)
    ) -> None: ...

    async def write_silver(
        self,
        *,
        company_id: UUID,
        source_id: UUID,
        columns: list[Any],  # list[InferredColumn]
        join_candidates: list[UUID],
    ) -> None: ...

    async def write_gold(
        self,
        *,
        company_id: UUID,
        source_id: UUID,
        gold: Any,  # GoldArtifact
    ) -> None: ...

    def read_layer(
        self,
        *,
        company_id: UUID,
        layer: Literal["bronze", "silver", "gold"],
        resource_id: str | None = None,
        n: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...


__all__ = ["AcquirableSource", "MaintainableSource", "LakeStore"]
