# > AUTHORED 2026-05-03: v1 returned list-of-one. Wave B.5 G.6 expanded
# > to three Reactivities (Position + ResourceOwnership lifted alongside
# > UnknownPlatformId). Per **C5** the factory keys on an Install, NOT a
# > Source — identity is upstream of source-building.
"""Factory — produce identity Reactivities for an Install.

Wave A shipped one Reactivity (`UnknownPlatformIdReactivity`); Wave B.5
expands the list to three by registering the two greenfield proposers:

* `UnknownPlatformIdReactivity` — auto-discovers Persons from unknown
  platform_user_ids in chat / file events.
* `PositionInferenceReactivity` — proposes `Person.position` from chatter
  signal scoring (Wave B.5 G.4).
* `ResourceOwnershipReactivity` — proposes `resource.maintainer` roles
  from chatter + consumption signals (Wave B.5 G.5).

Per the synthesis decisions **D10** + **D11**, the list grows additively;
new identity-tracker Reactivities will append here without breaking any
caller.

The factory is pure — no side effects. It constructs Reactivity
instances; registration into the ReactivityRegistry happens in
`lifecycle.wire_identity_for_install` (Block G).
"""
from __future__ import annotations

from typing import Any

from wormbase_identity_tracker.reactivities import (
    PositionInferenceReactivity,
    ResourceOwnershipReactivity,
    UnknownPlatformIdReactivity,
)
from wormbase_identity_tracker.types import MemberLookup


def make_identity_reactivities(
    *,
    install: Any,  # duck-typed: needs .id, .platform — see Block F header
    member_lookup: MemberLookup,
) -> list[Any]:
    """Return the list of identity Reactivities to register for an Install.

    Wave B.5: returns THREE Reactivities — `UnknownPlatformIdReactivity`,
    `PositionInferenceReactivity`, and `ResourceOwnershipReactivity`. The
    list is order-stable (UnknownPlatformId first to preserve the legacy
    ordering for any consumer that still indexes the list) but callers
    SHOULD identify Reactivities by type, not position.

    `member_lookup` is the platform-specific callable that resolves
    `(platform, platform_user_id)` to workspace metadata. The
    `cli.py` boot path constructs a Slack-flavoured lookup shim around
    `SlackChannelAdapter.users_info`; tests pass an in-memory dict.
    `PositionInferenceReactivity` and `ResourceOwnershipReactivity` do
    not consume `member_lookup` — they read directly from the ledger —
    so they ignore it at construction time.

    Currently returns `list[Any]` because the Reactivity Protocol type
    lives in `wormbase_reactivities` and importing it here would force
    a heavier dep on this otherwise-light factory. Caller upcasts.
    """
    return [
        UnknownPlatformIdReactivity(member_lookup=member_lookup),
        PositionInferenceReactivity(),
        ResourceOwnershipReactivity(),
    ]


__all__ = ["make_identity_reactivities"]
