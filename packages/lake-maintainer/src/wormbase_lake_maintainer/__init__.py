"""WormBase LakeMaintainer — agentic data-lake maintenance.

See `docs/superpowers/notes/2026-05-02-lake-maintainer-phase-0-spike.md`
for the architecture and the GO-WITH-CAVEATS design rationale.
"""
from __future__ import annotations

from wormbase_lake_maintainer.protocols import (
    AcquirableSource,
    LakeStore,
    MaintainableSource,
)
from wormbase_lake_maintainer.types import (
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
    "AcquirableSource",
    "Capability",
    "Change",
    "Classification",
    "ClassificationHint",
    "ClassificationUpdate",
    "DriftReport",
    "LakeStore",
    "LineageEdge",
    "LineageReport",
    "MaintainableSource",
    "Profile",
    "ResourceProposal",
    "SourceFamily",
    "SourceId",
    "StalenessReport",
]
