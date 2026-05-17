# > REWRITTEN 2026-05-03 (Wave A — identity-worm extraction):
# > Full body lifted to packages/wormbase-identity-tracker/. This shim
# > preserves every existing import path. New code should import from
# > `wormbase_identity_tracker` directly.
"""Backwards-compat shim — see ``wormbase_identity_tracker`` for impl.

Wave A (2026-05-03) lifted this module's contents to
`packages/wormbase-identity-tracker/`. This shim preserves the legacy
import paths for:

- HTTP handlers in `apps/worm-core/src/wormbase_core/http_api.py`
- MCP tool surfaces
- `cli.py` (transitively, via `wire_identity_for_install`)
- Tests under `apps/worm-core/tests/`

The legacy class name `IdentityDiscoveryReactivity` is aliased to the
renamed `UnknownPlatformIdReactivity`. The `_REACTIVITY_ID` constant
is preserved as `"identity_discovery"` for any code that grep-matches
against it (e.g. trace-UI legacy entry alias).
"""
from __future__ import annotations

# Re-export from the new home.
from wormbase_identity_tracker.legacy import IdentityDiscoveryLoop
from wormbase_identity_tracker.reactivities import (
    LEGACY_REACTIVITY_ID,
    UnknownPlatformIdReactivity,
    _rehydrate_known_set,
    _safe_lookup_static,
)
from wormbase_identity_tracker.types import MemberLookup

# Legacy alias — old class name maps to the new one.
IdentityDiscoveryReactivity = UnknownPlatformIdReactivity

# Legacy constant — keep `"identity_discovery"` so any HTTP or test code
# that compares against the constant still works. The ACTIVE Reactivity
# id (what `emit_reactivity_fired` carries) is the new one; this constant
# is read-only documentation of the historical id.
_REACTIVITY_ID = LEGACY_REACTIVITY_ID  # "identity_discovery"


__all__ = [
    "IdentityDiscoveryLoop",
    "IdentityDiscoveryReactivity",
    "MemberLookup",
    "_REACTIVITY_ID",
    "_rehydrate_known_set",
    "_safe_lookup_static",
]
