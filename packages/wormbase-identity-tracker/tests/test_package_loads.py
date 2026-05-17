"""Smoke test that the package is importable as a workspace member."""
from __future__ import annotations


def test_package_importable() -> None:
    import wormbase_identity_tracker

    assert wormbase_identity_tracker.__name__ == "wormbase_identity_tracker"


def test_protocol_and_types_importable_from_top_level() -> None:
    from wormbase_identity_tracker import (
        IdentityResolver,
        MemberLookup,
        Person,
        PersonHint,
        ProposalRef,
        TeamMembership,
    )
    # All six must be importable at the top level of the package.
    assert IdentityResolver is not None
    assert MemberLookup is not None
    assert Person is not None
    assert PersonHint is not None
    assert ProposalRef is not None
    assert TeamMembership is not None
