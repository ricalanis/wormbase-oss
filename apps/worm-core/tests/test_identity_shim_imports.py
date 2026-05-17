"""Smoke test: lifted modules' shims preserve every import path."""
from __future__ import annotations


def test_identity_discovery_module_imports() -> None:
    """The legacy module re-exports the renamed Reactivity + legacy Loop."""
    from wormbase_core.identity_discovery import (
        IdentityDiscoveryLoop,           # legacy class via shim
        IdentityDiscoveryReactivity,     # alias for UnknownPlatformIdReactivity
        MemberLookup,                    # type alias
        _REACTIVITY_ID,                  # const some tests grep for
    )
    assert IdentityDiscoveryLoop is not None
    assert IdentityDiscoveryReactivity is not None
    assert MemberLookup is not None
    # Legacy id constant — preserved verbatim for trace-UI alias mapping.
    assert _REACTIVITY_ID == "identity_discovery"


def test_identity_discovery_reactivity_alias_is_unknown_platform_id() -> None:
    """The alias points at the renamed class; importing the old name works."""
    from wormbase_core.identity_discovery import IdentityDiscoveryReactivity
    from wormbase_identity_tracker import UnknownPlatformIdReactivity
    assert IdentityDiscoveryReactivity is UnknownPlatformIdReactivity


def test_owner_lookup_module_imports() -> None:
    from wormbase_core.owner_lookup import Person, lookup_owner
    assert Person is not None
    assert lookup_owner is not None


def test_team_lookup_module_imports() -> None:
    from wormbase_core.team_lookup import (
        all_teams, members_of_team, team_for_person,
    )
    assert callable(all_teams)
    assert callable(members_of_team)
    assert callable(team_for_person)


def test_positions_module_imports() -> None:
    from wormbase_core.positions import (  # noqa: F401  Intentionally re-imported to test shim import surface.
        ImprovementCandidate, Metric, Position,
        all_positions, get_position,
        headline_metric_for_position,
        position_candidates, position_metrics, position_patterns,
    )
    assert all_positions is not None
    assert get_position is not None
    # Registry has the canonical positions
    assert len(all_positions()) >= 8  # CFO, CMO, ...
