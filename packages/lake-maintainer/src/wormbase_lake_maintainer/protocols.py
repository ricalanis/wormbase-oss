"""Protocols re-export shim.

> 2026-05-17 — Per ADR-0013 (continuous lake philosophy) and the
> ADR-0003 addendum, the canonical home for the lake-side Protocols
> (AcquirableSource, MaintainableSource, LakeStore) is now
> ``wormbase_lake_surfaces.protocols``. This module re-exports them
> for backwards compatibility within the lake-maintainer package.
"""
from __future__ import annotations

from wormbase_lake_surfaces.protocols import (
    AcquirableSource,
    LakeStore,
    MaintainableSource,
)

__all__ = ["AcquirableSource", "LakeStore", "MaintainableSource"]
