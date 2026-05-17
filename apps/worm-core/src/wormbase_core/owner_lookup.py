# > REWRITTEN 2026-05-03 (Wave A — identity-worm extraction):
# > Full body lifted to packages/wormbase-identity-tracker/owner_lookup.py.
"""Backwards-compat shim — see ``wormbase_identity_tracker.owner_lookup``."""
from __future__ import annotations

from wormbase_identity_tracker.owner_lookup import Person, lookup_owner

__all__ = ["Person", "lookup_owner"]
