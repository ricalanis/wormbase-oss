# > AUTHORED 2026-05-03: encodes D14's three signature revisions:
# > (1) propose_person returns ProposalRef (not bare UUID),
# > (2) lookup_owner takes Topic (not bare UUID),
# > (3) lookup_team returns list[TeamMembership] (not bare set[UUID]).
"""IdentityResolver Protocol — frozen public surface.

Per **C2**, the four method signatures below are FROZEN after Wave A
landing. Three downstream worms (chat / process / research) and two
existing Reactivities (`StatementToOwnerReactivity`, `team_loop_runner`)
consume this surface via DI from `apps/worm-core`. Any signature change
after Wave A requires coordinated refactoring across those consumers.

Method semantics (numbered to match the spike's §6):

  1. resolve_platform_id — read fold over emit_person_proposed +
     emit_identity_linked + emit_identity_unlinked entries; returns
     the canonical Person OR None.
  2. propose_person — write fold; thin facade over
     write_actions.propose_person; returns ProposalRef carrying
     person_id + the four PEVR entry_ids.
  3. lookup_owner — lifts owner_lookup.lookup_owner verbatim; takes a
     `Topic` (NOT a bare resource UUID, per C7) because the resolution
     waterfall needs both topic.id and topic.domain_id.
  4. lookup_team — replaces team_lookup.team_for_person (which returns
     bare `set[UUID]`) with a richer dataclass return type carrying
     role + granted_at.

The Protocol is `runtime_checkable` so test code and the wire helper
can `isinstance(resolver, IdentityResolver)` to verify shape conformance.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

# `Topic` lives in worm-core (`wormbase_core.topic_extractor`) per **D1**.
# Identity-worm imports it because lookup_owner takes `topic: Topic`.
# This is a one-way import — identity-worm depends on worm-core's
# topic_extractor module; worm-core does not import identity-worm at
# module-import time (it imports lazily via the lifecycle factory).
from wormbase_core.topic_extractor import Topic

from wormbase_identity_tracker.types import (
    Person,
    PersonHint,
    ProposalRef,
    TeamMembership,
)


@runtime_checkable
class IdentityResolver(Protocol):
    """Read-side Protocol consumed by chat / process / research worms.

    All four methods are async because production implementations fold
    the live ledger; even the in-memory test path uses async ledger.
    """

    async def resolve_platform_id(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> Person | None:
        """Resolve `(platform, platform_user_id)` → Person, None if unknown.

        Used by chat-worm to populate `Person` on inbound messages and
        by process-worm to attribute decisions / process steps. Folds
        `emit_person_proposed` + `emit_identity_linked` /
        `emit_identity_unlinked` entries for the resolver's tenant.
        """

    async def propose_person(
        self,
        hint: PersonHint,
        *,
        proposed_by: str,
    ) -> ProposalRef:
        """Worm-side propose-Person path.

        Thin facade over `write_actions.propose_person` (see
        `apps/worm-core/src/wormbase_core/write_actions.py:133-180`).
        Always writes a full PEVR cycle.

        `proposed_by="worm"` for agent-initiated proposals;
        pass an admin UUID-as-str for human-initiated paths.
        """

    async def lookup_owner(
        self,
        topic: Topic,
    ) -> Person | None:
        """Lift verbatim from owner_lookup.lookup_owner.

        Note: takes a `Topic` (NOT a bare `resource_id: UUID`) because
        the resolution waterfall needs both `topic.id` and
        `topic.domain_id`. See spike §4 #3 for why.

        Returns None when no owner has been assigned OR when the matched
        Person has muted resource_conversations in their preferences.
        """

    async def lookup_team(
        self,
        person_id: UUID,
    ) -> list[TeamMembership]:
        """Resolve a Person to their Team-Domain memberships.

        Replaces the existing `team_lookup.team_for_person` (which
        returns a bare `set[UUID]`) with a richer dataclass list that
        includes `role` + `granted_at`. The bare-set helper stays as a
        package-private optimisation for the hot-path
        `autoresearch_loop.team_loop_runner` (which doesn't need the
        role).
        """


__all__ = ["IdentityResolver"]
