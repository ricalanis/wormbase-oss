"""Factory: one Reactivity per (Source x maintenance_method).

Per spike section 8 C6: each MaintainableSource gets four Reactivity
instances, one per maintenance method. The factory is the single point
of construction so the (Source x method) cardinality is enforced
structurally — no caller can register, say, just StalenessSignalReactivity
for a Source and forget the others.
"""
from __future__ import annotations

from typing import Any

from wormbase_reactivities.protocol import Reactivity

from wormbase_lake_maintainer.reactivities import (
    ClassificationRefreshReactivity,
    DriftDetectorReactivity,
    LineageHealthReactivity,
    StalenessSignalReactivity,
)


def make_maintenance_reactivities(*, source: Any) -> list[Reactivity]:
    """Return the four maintenance Reactivities for one MaintainableSource.

    The order is fixed: staleness, drift, classification, lineage. The
    Source's caller-side registration code can rely on this order if it
    needs to wire per-method telemetry.
    """
    return [
        StalenessSignalReactivity(source=source),
        DriftDetectorReactivity(source=source),
        ClassificationRefreshReactivity(source=source),
        LineageHealthReactivity(source=source),
    ]


__all__ = ["make_maintenance_reactivities"]
