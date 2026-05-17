# > AUTHORED 2026-05-03: lifts Person verbatim from owner_lookup.py:45-63;
# > introduces PersonHint, ProposalRef, TeamMembership as new types per
# > D14. MemberLookup callable type alias lifts unchanged from
# > identity_discovery.py:75-78.
"""Value types for identity-worm.

Every type is a frozen dataclass to keep the Protocol's I/O surface
hashable and trivially safe to thread across DI boundaries. The four
business types here are also re-exported from `wormbase_identity_tracker`
top-level (`__init__.py`).

Stability: per design constraint **C2** these shapes are FROZEN after
Wave A landing. Adding optional fields is permitted (additive change,
matches schema-evolution doctrine Rule 2). Renaming or removing fields
is forbidden — three downstream worms (chat / process / research) and
two existing W5a Reactivities consume this surface.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable  # noqa: F401  Awaitable used inside the MemberLookup forward-ref string annotation below.
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


# ---------------------------------------------------------------------------
# Person — the canonical resolved identity record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Person:
    """The Person record returned by IdentityResolver methods.

    Lifts verbatim from `wormbase_core.owner_lookup.Person`. The shape is
    identical because the existing `StatementToOwnerReactivity` consumer
    (now read via DI through the IdentityResolver Protocol) already
    expects this surface.

    Field semantics:
        person_id — canonical UUID for the Person across all platforms
        name — display name; "Unknown" when nothing better is available
        email — None when unverified
        platform / platform_user_id — the FIRST identity bound to the
            person (additional identities are visible only by re-folding
            the ledger; this is acceptable because downstream consumers
            today only ever need one platform identity per Person)
        preferences — freeform dict; the ``resource_conversations`` key
            controls owner-mute (see owner_lookup.py:122-129)
    """

    person_id: UUID
    name: str
    email: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None
    preferences: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# PersonHint — input type for the propose-Person path
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PersonHint:
    """Inputs for `IdentityResolver.propose_person`.

    Mirrors the kwargs of `write_actions.propose_person` minus the
    bookkeeping fields (`person_id`, `tenant_id`, `proposed_by`). The
    resolver fills `tenant_id = company_id` and threads `proposed_by`
    through as a separate Protocol-method kwarg.

    Three required fields, two optional. Mirrors the shape of the chat
    event payloads that drive UnknownPlatformIdReactivity's
    member_lookup result — `name` is always present (even if "Unknown"),
    email + position are best-effort.
    """

    platform: str
    platform_user_id: str
    name: str
    email: str | None = None
    position: str | None = None


# ---------------------------------------------------------------------------
# ProposalRef — output type for propose_person
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposalRef:
    """Outcome of `IdentityResolver.propose_person`.

    Carries BOTH the new ``person_id`` AND the ``entry_ids`` tuple from
    the underlying `WriteResult`. Per **D14** of the synthesis decisions,
    we surface entry_ids so the trace UI can attribute the four-PEVR
    fan-out back to the Reactivity that fired the propose.

    `entry_ids` is typed as open-ended (``tuple[UUID, ...]``) even though
    in practice every PEVR cycle writes exactly four entries. This keeps
    the Protocol robust against future write-primitive shape changes
    (e.g. a wave that adds a fifth `attest` step).
    """

    person_id: UUID
    entry_ids: tuple[UUID, ...]


# ---------------------------------------------------------------------------
# TeamMembership — typed return for lookup_team
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TeamMembership:
    """A Person's grant on a Team-Domain.

    `role` ∈ {"owner", "contributor"} per `emit_domain_role_assigned`
    payload (see `packages/ledger/src/wormbase_ledger/entries.py`
    DomainRoleAssignedPayload).

    `granted_at` is the timestamp from the granting entry's `ts` column.
    `None` when the source row carries no timestamp (in-memory tests
    that omit `timestamp` on `ledger.write` — though InMemoryLedger
    defaults to `datetime.now(UTC)`, this is still typed `| None` for
    forward-compat with replay scenarios where the granting entry was
    redacted).
    """

    team_id: UUID
    role: str  # "owner" | "contributor" — typed str for additive robustness
    granted_at: datetime | None = None


# ---------------------------------------------------------------------------
# Position — Wave B.5 G.2: input/output for PositionInferenceReactivity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    """A position-inference proposal for a Person.

    Emitted by `PositionInferenceReactivity` (G.4) when chat-signal scoring
    crosses the confidence threshold. Becomes the payload of
    `emit_position_proposed` (G.3) and, after PEVR resolve(keep), populates
    `state["persons"][pid]["position"]` in the projection fold.

    Field semantics:
        name — slug-cased role name from the static positions registry
            (e.g. "senior_engineer", "data_analyst", "product_manager").
            Matches the keys in `positions.py`.
        confidence — float in [0.0, 1.0]. The Reactivity threshold is
            ≥ 0.5 to fire propose; downstream consumers may apply higher
            bars before auto-resolving keep.
        signals — tuple of signal-token names that contributed to the
            score (e.g. ``("commit_msg", "design_doc")``). Surfaced to
            the trace UI so admins can see *why* the position was proposed.
            Defaults to empty for direct constructions in tests.
    """

    name: str
    confidence: float
    signals: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# ResourceRole — Wave B.5 G.2: input/output for ResourceOwnershipReactivity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceRole:
    """A resource-role proposal binding a Person to a Resource.

    Emitted by `ResourceOwnershipReactivity` (G.5) when chatter +
    data-product-consumption signals cross threshold for a
    (person, resource) pair. Becomes the payload of
    `emit_resource_role_proposed` (G.3) and, after PEVR resolve(keep),
    writes a row into `state["roles"]` with ``facet='resource'``.

    Field semantics:
        person_id — canonical Person UUID (resolved via IdentityResolver
            before the Reactivity emits).
        resource_id — UUID of the resource (KPI, table, mart, model,
            concept, etc.) the Person is being bound to.
        role — typed `str` for additive robustness; canonical values are
            "maintainer" and "contributor" per the resource facet of the
            role model in CLAUDE.md §5.
        confidence — float in [0.0, 1.0]; same thresholding semantics as
            `Position.confidence`.
        signals — tuple of signal-token names that contributed
            (e.g. ``("chat_mention", "data_product_consumed")``).
            Surfaced to the trace UI for explainability. Defaults to
            empty for direct constructions in tests.
    """

    person_id: UUID
    resource_id: UUID
    role: str
    confidence: float
    signals: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# MemberLookup — callable type alias (NOT a Protocol; keep light)
# ---------------------------------------------------------------------------


# Lift verbatim from `wormbase_core.identity_discovery:75-78`.
# Sync OR async: implementations may return the dict directly OR an
# Awaitable. _safe_lookup_static handles both cases via inspect.isawaitable.
MemberLookup = Callable[
    [str, str],
    "dict[str, Any] | None | Awaitable[dict[str, Any] | None]",
]


__all__ = [
    "MemberLookup",
    "Person",
    "PersonHint",
    "Position",
    "ProposalRef",
    "ResourceRole",
    "TeamMembership",
]
