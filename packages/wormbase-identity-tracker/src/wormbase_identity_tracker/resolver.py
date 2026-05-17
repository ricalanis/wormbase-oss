# > AUTHORED 2026-05-03: composes the four Protocol methods over the
# > lifted helpers + write_actions.propose_person. resolve_platform_id
# > is a NEW fold (~30 LOC); the other three delegate.
"""Production implementation of `IdentityResolver`.

Per **C6**, the resolver reads from the ledger directly (no SQL
projection-table reads). InMemoryLedger and Postgres Ledger both
satisfy the contract identically.

Composition map:

| Protocol method      | Implementation                                      |
|----------------------|-----------------------------------------------------|
| resolve_platform_id  | NEW fold over emit_person_proposed +                |
|                      | emit_identity_linked + emit_identity_unlinked       |
| propose_person       | wraps wormbase_core.write_actions.propose_person    |
| lookup_owner         | delegates to owner_lookup.lookup_owner              |
| lookup_team          | composes team_lookup.team_for_person + ledger fold  |
|                      | over emit_domain_role_assigned for role + granted_at|
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_core.topic_extractor import Topic

from wormbase_identity_tracker.owner_lookup import lookup_owner
from wormbase_identity_tracker.team_lookup import team_for_person
from wormbase_identity_tracker.types import (
    Person,
    PersonHint,
    ProposalRef,
    TeamMembership,
)

logger = logging.getLogger("wormbase_identity_tracker.resolver")


class _LedgerBackedIdentityResolver:
    """The single production impl of `IdentityResolver`.

    Construction: takes a ledger handle + the resolver's tenant scope
    (company_id). Both are bound at construction time so Protocol
    methods accept only their semantic kwargs (no per-call ledger
    threading).
    """

    def __init__(
        self,
        *,
        ledger: Ledger | InMemoryLedger,
        company_id: UUID,
    ) -> None:
        self._ledger = ledger
        self._company_id = company_id

    # ------------------------------------------------------------------
    # resolve_platform_id — NEW fold
    # ------------------------------------------------------------------

    async def resolve_platform_id(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> Person | None:
        """Walk the ledger; return the latest Person bound to the tuple.

        Folds three entry kinds:
          * emit_person_proposed — initial bind
          * emit_identity_linked — additional bind
          * emit_identity_unlinked — explicit unbind (DROPS the tuple)

        Resolution rule: the LATEST bind (highest seq) wins. Unlinks
        remove the tuple from the result; if a later link re-binds it,
        the link wins. This mirrors the legacy known-set semantics in
        `_rehydrate_known_set` plus the unlink subtraction the legacy
        code didn't need (because it only built a set, not a Person).
        """
        rows = await self._ledger.fetch(self._company_id)
        # Walk in seq order so latest writes win.
        rows = sorted(rows, key=lambda r: int(r.get("seq", 0)))

        # bound[(platform, user)] -> person_id
        bound: dict[tuple[str, str], UUID] = {}
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            tool = payload.get("tool")
            args = payload.get("args") or {}
            p = args.get("platform")
            u = args.get("platform_user_id")
            if not p or not u:
                continue
            key = (str(p), str(u))
            pid_raw = args.get("person_id")
            if tool in ("emit_person_proposed", "emit_identity_linked"):
                if pid_raw:
                    try:
                        bound[key] = UUID(str(pid_raw))
                    except (ValueError, TypeError):
                        continue
            elif tool == "emit_identity_unlinked":
                bound.pop(key, None)

        person_id = bound.get((platform, platform_user_id))
        if person_id is None:
            return None

        # Hydrate the Person record from the same fold pattern
        # owner_lookup._hydrate_person uses. Reuse that helper indirectly
        # by walking propose/registered/preferences entries for our id.
        return _hydrate_person_from_rows(rows, person_id)

    # ------------------------------------------------------------------
    # propose_person — wraps write_actions.propose_person
    # ------------------------------------------------------------------

    async def propose_person(
        self,
        hint: PersonHint,
        *,
        proposed_by: str,
    ) -> ProposalRef:
        """Thin facade over write_actions.propose_person.

        Maps PersonHint → keyword args; lifts (person_id, WriteResult)
        into ProposalRef(person_id, entry_ids).
        """
        # Late import to break a potential cycle if write_actions ever
        # imports this package (it currently does not).
        from wormbase_core import write_actions

        person_id, write_result = await write_actions.propose_person(
            self._ledger,
            self._company_id,
            name=hint.name,
            email=hint.email,
            platform=hint.platform,
            platform_user_id=hint.platform_user_id,
            position=hint.position,
            proposed_by=proposed_by,
        )
        return ProposalRef(
            person_id=person_id,
            entry_ids=write_result.entry_ids,
        )

    # ------------------------------------------------------------------
    # lookup_owner — delegates to owner_lookup.lookup_owner
    # ------------------------------------------------------------------

    async def lookup_owner(
        self,
        topic: Topic,
    ) -> Person | None:
        """Delegate to owner_lookup.lookup_owner with bound ledger handle.

        owner_lookup returns its OWN `Person` dataclass; that dataclass
        has identical fields to types.Person (both lift from the same
        source) so it is value-compatible. We coerce explicitly here
        for type-checker clarity.
        """
        result = await lookup_owner(
            topic, ledger=self._ledger, company_id=self._company_id,
        )
        if result is None:
            return None
        # Coerce owner_lookup.Person → types.Person (identical fields).
        return Person(
            person_id=result.person_id,
            name=result.name,
            email=result.email,
            platform=result.platform,
            platform_user_id=result.platform_user_id,
            preferences=dict(result.preferences),
        )

    # ------------------------------------------------------------------
    # lookup_team — composes team_for_person + emit_domain_role_assigned fold
    # ------------------------------------------------------------------

    async def lookup_team(
        self,
        person_id: UUID,
    ) -> list[TeamMembership]:
        """Resolve a Person to TeamMembership records.

        team_for_person returns bare set[UUID] of team-domain ids; here
        we fold emit_domain_role_assigned to extract role + granted_at
        per (person, team) pair.
        """
        # Use the bare-set helper as the team-id source so the answer is
        # consistent with autoresearch_loop.team_loop_runner's view.
        team_ids = await team_for_person(
            self._ledger, self._company_id, person_id,
        )
        if not team_ids:
            return []

        # Fold to extract role + granted_at.
        rows = await self._ledger.fetch(self._company_id)
        memberships: list[TeamMembership] = []
        seen: set[tuple[UUID, str]] = set()  # (team_id, role) dedup
        for r in rows:
            if r.get("kind") != "execute":
                continue
            payload = r.get("payload") or {}
            if payload.get("tool") != "emit_domain_role_assigned":
                continue
            args = payload.get("args") or {}
            try:
                pid = UUID(str(args.get("person_id") or ""))
            except (ValueError, TypeError):
                continue
            if pid != person_id:
                continue
            try:
                tid = UUID(str(args.get("domain_id") or ""))
            except (ValueError, TypeError):
                continue
            if tid not in team_ids:
                continue
            role = args.get("role")
            if not isinstance(role, str):
                continue
            if (tid, role) in seen:
                continue
            seen.add((tid, role))
            ts: datetime | None = r.get("ts")
            memberships.append(TeamMembership(
                team_id=tid, role=role, granted_at=ts,
            ))

        return memberships


# ---------------------------------------------------------------------------
# Helper — local implementation mirroring owner_lookup._hydrate_person
# ---------------------------------------------------------------------------


def _hydrate_person_from_rows(
    rows: list[dict[str, Any]], person_id: UUID,
) -> Person | None:
    """Build a Person from emit_person_proposed + identity / preferences rows.

    Mirrors `wormbase_identity_tracker.owner_lookup._hydrate_person` but
    returns the public `types.Person`. Single helper kept here (not
    imported across the module boundary) because owner_lookup's helper
    is module-private.
    """
    target = str(person_id)
    name = ""
    email: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None
    preferences: dict[str, Any] = {}
    seen = False

    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        pid = str(args.get("person_id") or "")

        if tool == "emit_person_proposed" and pid == target:
            name = args.get("name", "") or name
            email = args.get("email") or email
            platform = args.get("platform") or platform
            platform_user_id = (
                args.get("platform_user_id") or platform_user_id
            )
            seen = True
        elif tool == "emit_identity_linked" and pid == target:
            platform = args.get("platform") or platform
            platform_user_id = (
                args.get("platform_user_id") or platform_user_id
            )
            seen = True
        elif tool == "emit_person_registered" and pid == target:
            name = args.get("name", "") or name
            email = args.get("email") or email
            seen = True
        elif tool == "set_person_preferences" and pid == target:
            prefs = args.get("preferences")
            if isinstance(prefs, dict):
                preferences = {**preferences, **prefs}
            seen = True

    if not seen:
        return None
    return Person(
        person_id=person_id,
        name=name or "Unknown",
        email=email,
        platform=platform,
        platform_user_id=platform_user_id,
        preferences=preferences,
    )


__all__ = ["_LedgerBackedIdentityResolver"]
