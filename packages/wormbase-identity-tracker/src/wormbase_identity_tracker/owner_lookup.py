"""Owner lookup — resolve the Person who owns a Topic.

Lifted from ``wormbase_core.owner_lookup`` as part of Wave A (identity-worm
extraction). The original module becomes a backwards-compat shim that
re-exports from this module.

W5.A2 — companion to ``StatementToOwnerReactivity``. Given a ``Topic``
(KPI / source / domain / process), return the canonical owning Person,
or ``None`` if no owner has been confirmed.

Resolution order, by topic kind:

  1. **kpi / source / process** — first try a resource-facet grant:
     ``emit_resource_role_assigned`` with role ∈ {maintainer, contributor}
     and ``resource_id == topic.id``. Maintainer beats contributor.
  2. If no resource-facet grant exists OR the topic is a domain, fall
     through to the **domain-facet** owner: ``emit_domain_role_assigned``
     with role=="owner" and ``domain_id == topic.domain_id``.
  3. Still nothing? Try domain-facet ``contributor`` as a last resort.
     This catches the case where a domain has contributors but no owner
     — the worm still has someone to talk to.

Person preferences:

  * Each Person carries a ``preferences.resource_conversations`` boolean
    in the projection, exposed via ``Person.preferences``. When the
    matched Person has set that to ``False``, this function returns
    ``None`` so the reactivity skips them — owner muting honours user
    intent, not just admin policy.

The function walks the ledger directly (no SQL) so it works with the
in-memory ledger used by tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from wormbase_ledger import InMemoryLedger, Ledger

from wormbase_core.topic_extractor import Topic

logger = logging.getLogger("wormbase_identity_tracker.owner_lookup")


@dataclass(frozen=True)
class Person:
    """Lightweight Person record returned by :func:`lookup_owner`.

    Carries the minimum the StatementToOwnerReactivity needs to send the
    DM — the canonical Person id, name, optional email, and the
    platform identity (so channel-adapter can address the DM).

    ``preferences`` is the freeform dict the Person sets via
    ``/people/<id>/preferences``; the reactivity checks
    ``preferences.get("resource_conversations", True)`` before firing.
    """

    person_id: UUID
    name: str
    email: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None
    preferences: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def lookup_owner(
    topic: Topic,
    *,
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
) -> Person | None:
    """Return the Person who owns the topic's resource, or ``None``.

    Args:
        topic: the Topic returned by :func:`extract_topic`.
        ledger: tenant-scoped ledger handle.
        company_id: tenant id (multi-tenant gate).

    Returns ``None`` when:
      * No owner has been assigned (no resource_role_assigned + no
        domain_role_assigned for the topic).
      * The matched Person has set ``preferences.resource_conversations``
        to ``False`` — owner mute honours user intent.

    The function fetches the ledger once. Callers that need to look up
    many owners in succession should do their own folding for
    efficiency.
    """
    rows = await ledger.fetch(company_id)

    # First pass: build (resource-facet, domain-facet) owner candidates.
    resource_owners = _resource_role_grants_for(rows, topic.id)
    domain_owners = (
        _domain_role_grants_for(rows, topic.domain_id)
        if topic.domain_id is not None
        else {"owner": [], "contributor": []}
    )

    # Pick the strongest candidate.
    candidate_id: UUID | None = None
    if resource_owners["maintainer"]:
        candidate_id = resource_owners["maintainer"][0]
    elif domain_owners["owner"]:
        candidate_id = domain_owners["owner"][0]
    elif resource_owners["contributor"]:
        candidate_id = resource_owners["contributor"][0]
    elif domain_owners["contributor"]:
        candidate_id = domain_owners["contributor"][0]

    if candidate_id is None:
        return None

    person = _hydrate_person(rows, candidate_id)
    if person is None:
        return None

    # Owner-mute: respect Person.preferences.resource_conversations == False.
    if person.preferences.get("resource_conversations") is False:
        logger.debug(
            "owner_lookup: Person %s has muted resource conversations; "
            "skipping topic %s",
            person.person_id, topic.label,
        )
        return None
    return person


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resource_role_grants_for(
    rows: list[dict[str, Any]], resource_id: UUID,
) -> dict[str, list[UUID]]:
    """Return {role: [person_id, ...]} for a resource id.

    Walks ``emit_resource_role_assigned`` execute entries. Insertion
    order preserved so callers can pick "first to be granted".
    """
    out: dict[str, list[UUID]] = {"maintainer": [], "contributor": []}
    target = str(resource_id)
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_resource_role_assigned":
            continue
        args = payload.get("args") or {}
        if str(args.get("resource_id") or "") != target:
            continue
        role = args.get("role")
        pid = _maybe_uuid(args.get("person_id"))
        if role in out and pid is not None:
            out[role].append(pid)
    return out


def _domain_role_grants_for(
    rows: list[dict[str, Any]], domain_id: UUID,
) -> dict[str, list[UUID]]:
    """Return {role: [person_id, ...]} for a domain id."""
    out: dict[str, list[UUID]] = {"owner": [], "contributor": []}
    target = str(domain_id)
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_domain_role_assigned":
            continue
        args = payload.get("args") or {}
        if str(args.get("domain_id") or "") != target:
            continue
        role = args.get("role")
        pid = _maybe_uuid(args.get("person_id"))
        if role in out and pid is not None:
            out[role].append(pid)
    return out


def _hydrate_person(
    rows: list[dict[str, Any]], person_id: UUID,
) -> Person | None:
    """Hydrate a ``Person`` from the latest ledger entries for that id.

    Walks (in order): ``emit_person_proposed``, ``emit_person_confirmed``,
    ``emit_identity_linked``, ``emit_person_preferences_updated`` (if
    present). Returns the latest known state.

    Person.preferences is read from a synthetic ``person_preferences_set``
    payload if present in the ledger, otherwise defaults to ``{}``. We
    accept any execute tool ending with ``set_person_preferences`` so the
    dashboard's preferences API can land later without churning this code.
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
            # An identity_linked event may add a second platform binding.
            platform = args.get("platform") or platform
            platform_user_id = (
                args.get("platform_user_id") or platform_user_id
            )
            seen = True
        elif tool == "emit_person_registered" and pid == target:
            # Step-5 registered Persons; mirrors emit_person_proposed.
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


def _maybe_uuid(v: Any) -> UUID | None:
    if v is None:
        return None
    try:
        return UUID(str(v))
    except (ValueError, TypeError):
        return None


__all__ = ["Person", "lookup_owner"]
