"""AcquirableSourceImpl — shared wrapper for external + filedrop families.

Per spike §8 C3, external + filedrop collapse to one acquisition impl.
The Connector driver (kind="postgres" / "csv_local" / "stripe" / etc.)
provides discover/profile/sample; this class adds per-instance metadata
(id, family, classification, domain, owner) and a stored auth handle.

The wrapper is deliberately thin — no caching, no retry, no
classification logic. Those responsibilities belong to the maintenance
Reactivities (Block F).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from wormbase_lake_surfaces.base import Connector
from wormbase_lake_surfaces.types import Profile, ResourceProposal

from wormbase_lake_surfaces.types import (
    Classification,
    ClassificationUpdate,
    DriftReport,
    LineageReport,
    StalenessReport,
)


@dataclass
class AcquirableSourceImpl:
    """Concrete ``AcquirableSource`` for external + filedrop families.

    Holds a Connector driver + the auth handle returned by
    ``connector.authenticate(secrets)``. discover/profile/sample
    delegate verbatim. ``family`` is metadata; it does not change
    behaviour (per spike C3).

    Also implements ``MaintainableSource`` — the maintenance state
    fields (``baseline_schema_hash``, ``last_seen``,
    ``primary_resource_id``, ``staleness_sla_hours``) are mutable and
    drive ``detect_drift`` / ``staleness_signal``.
    """

    id: UUID
    family: Literal["external", "filedrop"]
    classification: Classification
    domain: UUID | None
    owner: UUID | None
    connector: Connector
    auth_handle: Any
    baseline_schema_hash: str | None = None
    last_seen: datetime | None = None
    primary_resource_id: str = "default"
    staleness_sla_hours: float = 24.0
    # Acquisition posture (Wave 3 Task 7, 2026-05-11). ``"upstream_mirror"``
    # sources additionally register catalog-mirror Reactivities via
    # ``source_builder.on_source_connected``; ``"wormbase_owned"`` is the
    # default and means bronze/silver/gold are curated end-to-end by
    # WormBase.
    source_mode: Literal["wormbase_owned", "upstream_mirror"] = "wormbase_owned"

    async def discover(self) -> list[ResourceProposal]:
        return await self.connector.discover(self.auth_handle)

    async def profile(self, resource_id: str) -> Profile:
        return await self.connector.profile(self.auth_handle, resource_id)

    async def sample(self, resource_id: str, n: int) -> bytes:
        return await self.connector.sample(self.auth_handle, resource_id, n)

    async def detect_drift(self) -> DriftReport:
        """Schema-hash compare against the baseline.

        Re-profiles the primary resource via the wrapped connector and
        compares ``Profile.schema_hash`` against ``baseline_schema_hash``.
        Returns no-drift on first call (``baseline_schema_hash is None``)
        — that call's hash establishes the baseline.
        """
        current = await self.connector.profile(
            self.auth_handle, self.primary_resource_id,
        )
        if self.baseline_schema_hash is None:
            return DriftReport(
                drifted=False,
                reason="no baseline yet",
                baseline_hash=None,
                current_hash=current.schema_hash,
            )
        if current.schema_hash == self.baseline_schema_hash:
            return DriftReport(
                drifted=False,
                reason="schema_hash matches",
                baseline_hash=self.baseline_schema_hash,
                current_hash=current.schema_hash,
            )
        return DriftReport(
            drifted=True,
            reason=(
                f"schema_hash changed: {self.baseline_schema_hash[:10]} → "
                f"{current.schema_hash[:10]}"
            ),
            baseline_hash=self.baseline_schema_hash,
            current_hash=current.schema_hash,
        )

    async def refresh_classification(self) -> ClassificationUpdate:
        """v1: report current classification unchanged."""
        return ClassificationUpdate(
            updated=False,
            classification=self.classification,
            previous_classification=self.classification,
            reason="classifier not yet wired (v1)",
        )

    async def staleness_signal(self) -> StalenessReport:
        """``last_seen`` older than ``staleness_sla_hours`` triggers stale=True.

        ``last_seen is None`` means "never observed" — treat as stale.
        """
        if self.last_seen is None:
            return StalenessReport(
                stale=True, last_seen=None,
                sla_hours=self.staleness_sla_hours,
            )
        age = datetime.now(UTC) - self.last_seen
        return StalenessReport(
            stale=age > timedelta(hours=self.staleness_sla_hours),
            last_seen=self.last_seen,
            sla_hours=self.staleness_sla_hours,
        )

    async def lineage_health(self) -> LineageReport:
        """v1: no lineage check; returns healthy."""
        return LineageReport(healthy=True, broken_edges=[])


__all__ = ["AcquirableSourceImpl"]
