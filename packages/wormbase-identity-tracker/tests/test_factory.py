"""Factory tests — make_identity_reactivities returns the package's Reactivities.

Wave A v1 returned a single Reactivity (UnknownPlatformIdReactivity).
Wave B.5 G.6 expanded the list to three: the original plus
PositionInferenceReactivity (G.4) and ResourceOwnershipReactivity (G.5).
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from wormbase_identity_tracker.factory import make_identity_reactivities
from wormbase_identity_tracker.reactivities import (
    PositionInferenceReactivity,
    ResourceOwnershipReactivity,
    UnknownPlatformIdReactivity,
)


@dataclass
class _FakeInstall:
    """Minimum duck-typed Install record."""

    id: object
    platform: str


def test_factory_returns_three_reactivities() -> None:
    install = _FakeInstall(id=uuid4(), platform="slack")

    def fake_lookup(platform: str, user: str) -> dict | None:
        return {"name": user, "email": None}

    reactivities = make_identity_reactivities(
        install=install, member_lookup=fake_lookup,
    )
    assert len(reactivities) == 3


def test_make_identity_reactivities_includes_position_and_resource_ownership() -> None:
    install = _FakeInstall(id=uuid4(), platform="slack")

    def fake_lookup(platform: str, user: str) -> dict | None:
        return {"name": user, "email": None}

    reactivities = make_identity_reactivities(
        install=install, member_lookup=fake_lookup,
    )
    names = {type(r).__name__ for r in reactivities}
    assert "PositionInferenceReactivity" in names
    assert "ResourceOwnershipReactivity" in names
    assert "UnknownPlatformIdReactivity" in names


def test_factory_threads_member_lookup_through_to_reactivity() -> None:
    install = _FakeInstall(id=uuid4(), platform="slack")
    sentinel = object()

    def fake_lookup(platform: str, user: str) -> object:  # type: ignore[return-value]
        return sentinel  # not a real dict; just probe the wiring

    reactivities = make_identity_reactivities(
        install=install, member_lookup=fake_lookup,
    )
    # Inspect the private slot of the unknown-platform-id Reactivity to
    # verify wiring. Find it by type rather than position so list-order
    # changes don't break the contract.
    upi = next(
        r for r in reactivities if isinstance(r, UnknownPlatformIdReactivity)
    )
    assert upi._member_lookup is fake_lookup


def test_factory_position_and_resource_ownership_have_default_thresholds() -> None:
    """The greenfield Reactivities ship with their canonical 0.5 thresholds.

    G.4 / G.5 fix the threshold at 0.5; the factory must not override or
    pass through a different value without an explicit knob (which Wave B.5
    intentionally does not introduce).
    """
    install = _FakeInstall(id=uuid4(), platform="slack")

    def fake_lookup(platform: str, user: str) -> dict | None:
        return {"name": user, "email": None}

    reactivities = make_identity_reactivities(
        install=install, member_lookup=fake_lookup,
    )
    pos = next(
        r for r in reactivities if isinstance(r, PositionInferenceReactivity)
    )
    res = next(
        r for r in reactivities if isinstance(r, ResourceOwnershipReactivity)
    )
    assert pos._threshold == 0.5
    assert res._threshold == 0.5
