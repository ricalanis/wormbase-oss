"""Team membership lookup helpers for the autoresearch loop.

Lifted from ``wormbase_core.team_lookup`` as part of Wave A (identity-worm
extraction). Provides bare-set helpers (``team_for_person``,
``members_of_team``, ``all_teams``) optimised for the hot-path
``autoresearch_loop.team_loop_runner``. The richer
``IdentityResolver.lookup_team(person_id) -> list[TeamMembership]`` Protocol
method composes these helpers with a fold over ``emit_domain_role_assigned``
to extract role + granted_at — see Block E.

Wave-5 W5.A4 introduces Team-scoped and Company-scoped autoresearch loops in
addition to the existing Person-scoped loop. A "Team" in WormBase is modelled
as a ``Domain`` (i.e. a functional area like sales / retention / data_eng)
with ``kind="team"``. Until a dedicated Domain entity ships, Team-Domain
membership is inferred from the existing ``emit_domain_role_assigned`` ledger
entries — every Person who carries a domain-facet grant on a domain is a
member of that Team-Domain.

This module exposes two read-only helpers used by ``autoresearch_loop`` and by
``cli`` boot to register one ``team_loop_runner`` per discovered Team-Domain:

  * ``team_for_person(ledger, company_id, person_id)`` — the set of
    Team-Domain UUIDs the Person belongs to.
  * ``members_of_team(ledger, company_id, team_id)`` — the set of Person UUIDs
    that are members of a Team-Domain.

Both walk the live ledger via ``ledger.fetch`` so the answer is always replay-
deterministic and tenant-scoped. They tolerate revoked grants (none exist yet
at the entry-kind level for domain grants, but if a future
``emit_domain_role_revoked`` lands, this module will need to honour it — see
TODO at the bottom of the file).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from wormbase_ledger import InMemoryLedger, Ledger

logger = logging.getLogger("wormbase_identity_tracker.team_lookup")


def _maybe_uuid(v: Any) -> UUID | None:
    try:
        return UUID(str(v))
    except (ValueError, TypeError):
        return None


async def team_for_person(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    person_id: UUID,
) -> set[UUID]:
    """Return the set of Team-Domain UUIDs the Person belongs to.

    A Team-Domain is any ``domain_id`` referenced in an
    ``emit_domain_role_assigned`` execute entry whose ``person_id`` matches
    ``person_id``. Both ``owner`` and ``contributor`` grants count — the
    autoresearch Team loop runs experiments on behalf of the Team as a whole,
    so any active member is a participant.

    The helper is read-only and idempotent. Callers may invoke it on every
    cycle of the Team loop; the cost is one ``ledger.fetch(company_id)``.
    """
    rows = await ledger.fetch(company_id)
    teams: set[UUID] = set()
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        tool = payload.get("tool")
        if tool != "emit_domain_role_assigned":
            continue
        args = payload.get("args") or {}
        pid = _maybe_uuid(args.get("person_id"))
        if pid != person_id:
            continue
        did = _maybe_uuid(args.get("domain_id"))
        if did is None:
            continue
        teams.add(did)
    return teams


async def members_of_team(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    team_id: UUID,
) -> set[UUID]:
    """Return the set of Person UUIDs that are members of a Team-Domain.

    Symmetric to :func:`team_for_person`. Walks
    ``emit_domain_role_assigned`` entries, filters to ``domain_id ==
    team_id``, returns the deduplicated set of ``person_id`` values.
    """
    rows = await ledger.fetch(company_id)
    members: set[UUID] = set()
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        tool = payload.get("tool")
        if tool != "emit_domain_role_assigned":
            continue
        args = payload.get("args") or {}
        did = _maybe_uuid(args.get("domain_id"))
        if did != team_id:
            continue
        pid = _maybe_uuid(args.get("person_id"))
        if pid is None:
            continue
        members.add(pid)
    return members


async def all_teams(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
) -> set[UUID]:
    """Return every Team-Domain UUID seen in the ledger.

    Used by ``cli._run_async`` to register one ``team_loop_runner`` per
    discovered Team-Domain at boot. Replay-stable: the result is a set, sort
    by ``str(uuid)`` at the call site if deterministic iteration order is
    needed.
    """
    rows = await ledger.fetch(company_id)
    teams: set[UUID] = set()
    for r in rows:
        if r["kind"] != "execute":
            continue
        payload = r["payload"]
        tool = payload.get("tool")
        if tool != "emit_domain_role_assigned":
            continue
        args = payload.get("args") or {}
        did = _maybe_uuid(args.get("domain_id"))
        if did is None:
            continue
        teams.add(did)
    return teams


# TODO(post-W5): when ``emit_domain_role_revoked`` lands, both helpers must
# subtract the revoked (person, domain) pairs before returning. Today the
# domain-facet has no revoke entry kind (see entries.py line 856), so the
# question is moot.

__all__ = ["all_teams", "members_of_team", "team_for_person"]
