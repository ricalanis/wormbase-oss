# > REWRITTEN 2026-05-03 (Wave A — identity-worm extraction):
# > Full body lifted to packages/wormbase-identity-tracker/team_lookup.py.
"""Backwards-compat shim — see ``wormbase_identity_tracker.team_lookup``."""
from __future__ import annotations

from wormbase_identity_tracker.team_lookup import (
    all_teams,
    members_of_team,
    team_for_person,
)

__all__ = ["all_teams", "members_of_team", "team_for_person"]
