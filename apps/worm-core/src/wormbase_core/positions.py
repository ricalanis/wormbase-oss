# > REWRITTEN 2026-05-03 (Wave A — identity-worm extraction):
# > Full body lifted to packages/wormbase-identity-tracker/positions.py.
"""Backwards-compat shim — see ``wormbase_identity_tracker.positions``."""
from __future__ import annotations

from wormbase_identity_tracker.positions import (
    ImprovementCandidate,
    Metric,
    Position,
    all_positions,
    get_position,
    headline_metric_for_position,
    position_candidates,
    position_metrics,
    position_patterns,
)

__all__ = [
    "ImprovementCandidate",
    "Metric",
    "Position",
    "all_positions",
    "get_position",
    "headline_metric_for_position",
    "position_candidates",
    "position_metrics",
    "position_patterns",
]
