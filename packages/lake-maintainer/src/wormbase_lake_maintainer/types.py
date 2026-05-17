"""Report and value types for LakeMaintainer.

> 2026-05-17 — Per ADR-0013 (continuous lake philosophy) and the
> ADR-0003 addendum, the canonical home for the lake-side types
> (acquisition + maintenance + family enums) is now
> ``wormbase_lake_surfaces.types``. This module re-exports them for
> backwards compatibility within the lake-maintainer package.

Acquisition types (``Profile``, ``ResourceProposal``, ``Capability``,
``Change``) re-export the canonical shapes from
``wormbase_lake_surfaces.types`` so AcquirableSource doesn't fork them.
Maintenance types (``DriftReport``, ``ClassificationUpdate``,
``StalenessReport``, ``LineageReport``) live in lake-surfaces too, as
the Protocols there depend on them.
"""
from __future__ import annotations

from wormbase_lake_surfaces.types import (
    Capability,
    Change,
    Classification,
    ClassificationHint,
    ClassificationUpdate,
    DriftReport,
    LineageEdge,
    LineageReport,
    Profile,
    ResourceProposal,
    SourceFamily,
    SourceId,
    StalenessReport,
)

__all__ = [
    "Capability",
    "Change",
    "Classification",
    "ClassificationHint",
    "ClassificationUpdate",
    "DriftReport",
    "LineageEdge",
    "LineageReport",
    "Profile",
    "ResourceProposal",
    "SourceFamily",
    "SourceId",
    "StalenessReport",
]
