# > AUTHORED 2026-05-06 (Wave B2 — first-class WhatsApp identity discovery):
# > parallel-track Reactivity that mirrors UnknownPlatformIdReactivity's
# > shape but does NOT consult a member_lookup callable. WhatsApp has no
# > workspace roster (`list_workspace_members` returns []) so the only path
# > to learn about a Person is from inbound `chat_received`. The Reactivity
# > extracts a display name from the jid's phone-number prefix, formats it
# > as ``+<E.164>``, and emits a ``person_proposed`` PEVR cycle.
"""WhatsApp organic identity discovery.

Slack identity discovery uses :class:`UnknownPlatformIdReactivity` paired
with a Slack ``users.info`` ``member_lookup`` callable. WhatsApp has no
equivalent — :meth:`WhatsAppChannelAdapter.list_workspace_members` honestly
returns ``[]``. The only path to learn about a WhatsApp Person is from
inbound ``chat_received`` messages.

This Reactivity fills that gap:

* **Predicate** — ``EntryKind("chat_received")``. Same predicate family as
  Slack's discovery; no overlap with file-receive (WhatsApp's file-upload
  surface lands in a later wave).
* **Inner platform filter** — ``args["platform"] == "whatsapp"`` AND
  ``args["platform_user_id"]`` matches the DM-jid regex
  ``^\\d+@s\\.whatsapp\\.net$``. Group jids (``@g.us``) are NOT proposed
  as Persons — groups are channels, not people. Per-group-message senders
  surface via the per-message ``key.participant`` jid (already extracted
  by :meth:`WhatsAppChannelAdapter._normalize_message`), which DOES match
  the DM-jid regex (it carries the actual sender's @s.whatsapp.net jid).
* **Idempotency** — two layers, mirroring Wave A2's
  :class:`WhatsAppLogCapture._ensure_default_policy` shape:
    1. **Per-tenant LRU** — ``_seen_jids`` dict keyed by ``str(jid)``,
       insertion-order eviction at ``_SEEN_JIDS_MAX``.
    2. **Ledger fold safety net** — on cache miss, re-fold the ledger
       for any prior ``emit_person_proposed`` / ``emit_identity_linked``
       entry tied to ``(whatsapp, jid)``. If found, mark seen and skip.
* **Display name** — ``+<phone>`` where ``<phone>`` is the leading digit
  prefix of the jid (i.e. ``5491100000000@s.whatsapp.net`` → ``+5491100000000``).
  Operators rename via the ``/people`` UI; this is a placeholder display
  name until then.
* **Capability honesty** — ``proposed_by="worm:whatsapp_organic_discovery"``.
  The ``proposed_by`` field on ``PersonProposedPayload`` is intentionally
  free-form ``str`` (see ``packages/ledger/src/wormbase_ledger/entries.py``
  line 1057), with the projection layer treating any non-UUID-non-denylist
  value as "the worm" (see
  ``apps/worm-core/src/wormbase_core/projections/first_knowings.py``
  ``_is_worm_proposer``). Encoding the discovery source in the proposer
  string keeps the dashboard's pending-proposals tab able to group by
  source WITHOUT adding a new schema field (Schema-Evolution Doctrine
  Rule 2 — additive-only field changes).

This Reactivity sits ALONGSIDE :class:`UnknownPlatformIdReactivity`:

* The Slack-wired ``UnknownPlatformIdReactivity`` will also see WhatsApp
  ``chat_received`` entries, but its Slack ``member_lookup`` callable will
  return ``None`` for a WhatsApp jid (or raise harmlessly), so it
  ``ReactivityResult(fired=False)``-skips. The WhatsApp Reactivity then
  proposes via this dedicated path.
* Once this Reactivity proposes, the ``(whatsapp, jid)`` is in the
  known-set — a future ``UnknownPlatformIdReactivity`` fire on the same
  jid sees it as known and skips its own propose. No double-write.

Slack identity discovery is **byte-identical** — this module does not
touch :class:`UnknownPlatformIdReactivity` or its lookup path.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_reactivities import (
    AlwaysAllow,
    EntryKind,
    FiredAction,
    ReactivityContext,
    ReactivityResult,
)

logger = logging.getLogger("wormbase_identity_tracker.whatsapp_discovery")


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


_REACTIVITY_ID = "whatsapp_organic_discovery"

# DM jid grammar: ``<digits>@s.whatsapp.net``. Group jids end in ``@g.us``
# and are explicitly excluded — groups are channels, not people. The
# leading digits are the E.164 phone number (no leading ``+`` in jids).
_WA_DM_JID_RE = re.compile(r"^(?P<phone>\d+)@s\.whatsapp\.net$")

# Per-tenant LRU cap on the in-memory seen-jid set. Same posture as
# Wave A2's _SEEN_CHANNELS_MAX in WhatsAppLogCapture: bounded so a
# misbehaving log generator can't unbound memory. Real deployments see
# at most a handful of WhatsApp Persons per tenant in v1 (one bot phone
# in DMs + N group participants).
_SEEN_JIDS_MAX = 4096

# Tools whose `emit_*` writes count as "this jid is now known".
# Mirrors `_KNOWN_TOOLS` in reactivities.py — both Reactivities share
# the same known-set semantics so cross-firing is correctly suppressed.
_KNOWN_TOOLS = (
    "emit_person_proposed",
    "emit_identity_linked",
)

# The chat-received tool the channel-adapter writer emits.
_CHAT_RECEIVED_TOOL = "channel_adapter.emit_chat_received"

# Marker proposer string. Encodes the discovery source so the dashboard's
# /people pending-proposals tab can group by source. See module docstring
# for the schema-evolution rationale.
_PROPOSED_BY = "worm:whatsapp_organic_discovery"


class WhatsAppOrganicDiscoveryReactivity:
    """Reactivity — auto-discover WhatsApp Persons from inbound chat.

    Construction takes no platform-lookup callable (unlike
    :class:`UnknownPlatformIdReactivity`); WhatsApp has no roster.
    Display name is derived from the jid's phone-number prefix.

    The internal seen-jid LRU is per-instance, so each
    ``wire_whatsapp_identity_for_install`` call gets its own cache. The
    cache is a fast-path; correctness is guaranteed by the ledger fold
    on cache miss (matches the Wave A2 belt-and-suspenders pattern).

    Multi-tenant safety: ``ReactivityContext.company_id`` flows through
    every fire, and the ledger fold is company-scoped via
    ``ledger.fetch(company_id)``. The seen-jid cache is shared across
    tenants on the same instance (it's keyed by jid only, not tenant),
    which is fine: the ledger-fold safety net catches the cross-tenant
    case ("same jid in tenant A and tenant B" → both write their own
    ``emit_person_proposed`` because the fold is company-scoped). The
    cache simply avoids the fold work in the steady state.
    """

    id = _REACTIVITY_ID
    name = "WhatsApp Organic Discovery"
    description = (
        "Auto-discover WhatsApp Persons from inbound chat_received "
        "entries. WhatsApp has no workspace roster — every Person is "
        "learned from inbound messages. Display name is the jid's "
        "phone-number prefix until the operator renames via /people."
    )
    scope = "company"

    def __init__(self) -> None:
        self.predicate = EntryKind("chat_received")
        # Condition stays AlwaysAllow; the platform / jid filtering and
        # dedup happen inside fire() — same posture as
        # UnknownPlatformIdReactivity.
        self.condition = AlwaysAllow()
        # Per-tenant cache: ``(company_id_str, jid_str) → None``,
        # insertion-ordered for LRU eviction. Multi-tenant safe.
        self._seen_jids: dict[tuple[str, str], None] = {}

    @property
    def seen_jids(self) -> set[tuple[str, str]]:
        """Inspectable cache (test hook)."""
        return set(self._seen_jids)

    def _mark_seen(self, company_id: UUID, jid: str) -> None:
        """Insert into the LRU; evict oldest if at cap."""
        key = (str(company_id), str(jid))
        # If already present, refresh insertion order by re-inserting.
        if key in self._seen_jids:
            del self._seen_jids[key]
        elif len(self._seen_jids) >= _SEEN_JIDS_MAX:
            self._seen_jids.pop(next(iter(self._seen_jids)))
        self._seen_jids[key] = None

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        payload = entry.get("payload") or {}
        tool = payload.get("tool") or ""
        if tool != _CHAT_RECEIVED_TOOL:
            return ReactivityResult(fired=False)

        args = payload.get("args") or {}
        platform = args.get("platform")
        platform_user_id = args.get("platform_user_id")
        if platform != "whatsapp":
            # Not our platform — let UnknownPlatformIdReactivity handle.
            return ReactivityResult(fired=False)
        if not platform_user_id:
            return ReactivityResult(fired=False)

        jid = str(platform_user_id)

        # Group jids are NOT proposed as Persons. The per-message
        # `participant` extraction in WhatsAppChannelAdapter._normalize_message
        # already substitutes the actual sender's @s.whatsapp.net jid for
        # group messages, so when this Reactivity sees `platform_user_id`
        # it should already be a DM-shaped jid. Defensive filter against
        # any pure-observation entry where only the group jid is set.
        match = _WA_DM_JID_RE.match(jid)
        if not match:
            # Group jid (`@g.us`) or any other shape — skip.
            return ReactivityResult(fired=False)

        # Cache hit → skip fast.
        cache_key = (str(context.company_id), jid)
        if cache_key in self._seen_jids:
            return ReactivityResult(fired=False)

        # Cache miss → ledger fold for correctness.
        if await _has_existing_proposal(
            context.ledger, context.company_id, jid=jid,
        ):
            self._mark_seen(context.company_id, jid)
            return ReactivityResult(fired=False)

        # First-touch: propose the Person via the same write_actions path
        # the dashboard's Person API uses, so the PEVR cycle, projection
        # writes, and trace UI all see it as a normal proposal.
        phone = match.group("phone")
        display_name = f"+{phone}"

        try:
            from wormbase_core import write_actions

            _, write_result = await write_actions.propose_person(
                context.ledger,
                context.company_id,
                name=display_name,
                email=None,
                platform="whatsapp",
                platform_user_id=jid,
                position=None,
                proposed_by=_PROPOSED_BY,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "WhatsAppOrganicDiscoveryReactivity: propose_person failed "
                "for jid=%s: %s",
                jid, exc,
            )
            # Don't mark seen on failure — a future fire will retry. Same
            # posture as Wave A2's _ensure_default_policy.
            return ReactivityResult(fired=False)

        self._mark_seen(context.company_id, jid)
        logger.info(
            "whatsapp organic discovery: proposed Person for jid=%s "
            "display_name=%s",
            jid, display_name,
        )

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="person_proposed")],
            novelty_key=f"whatsapp:{jid}",
            budget_used={"per_tenant": 1},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _has_existing_proposal(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    *,
    jid: str,
) -> bool:
    """Fold the ledger for an existing Person proposal tied to this jid.

    Matches the read shape ``UnknownPlatformIdReactivity._rehydrate_known_set``
    uses: any execute row whose tool is ``emit_person_proposed`` or
    ``emit_identity_linked`` AND whose args carry
    ``(platform="whatsapp", platform_user_id=jid)``. This guarantees that
    even if the in-memory LRU is empty (fresh process boot, cache wraparound)
    we don't double-propose.

    Conservative on read failure: returns ``True`` (treat as proposed) so
    we skip the write rather than potentially double-writing during
    transient ledger errors. Mirrors Wave A2's
    ``WhatsAppLogCapture._has_existing_policy`` posture.
    """
    try:
        rows = await ledger.fetch(company_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "whatsapp organic discovery: ledger fold failed for jid=%s: %s",
            jid, exc,
        )
        return True
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool")
        if tool not in _KNOWN_TOOLS:
            continue
        args = payload.get("args") or {}
        if args.get("platform") != "whatsapp":
            continue
        if str(args.get("platform_user_id")) == jid:
            return True
    return False


__all__ = [
    "WhatsAppOrganicDiscoveryReactivity",
    "_has_existing_proposal",
]
