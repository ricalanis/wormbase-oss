"""MentionedInConversationFlow — data-keyword in chat → source proposal.

Lifted from flows.py:301-426 (class) plus the proactive-offer helpers:
  - ``_REMOTE_ARCHETYPE_URIS``  (line 808)
  - ``recognized_remote_archetypes`` (line 818)
  - ``propose_remote_archetype`` (line 826)
  - ``_proactive_offer_text`` (line 886)
  - ``_emit_proactive_offer_entry`` (line 910)
  - ``ProactiveMentionResult`` (line 963)
  - ``_on_proactive_mention`` (line 976) — bound onto the class at module bottom

Behavior unchanged. This is the body of SourceMentionedReactivity.fire (Block F4).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from wormbase_chat_presence.chat_flows._shared import _InterjectionGateProto
from wormbase_core.reactivity import InfraEvent, SemanticInterpretation
from wormbase_core.source_builder import (
    SourceBuilder,
    SourceKind,
    SourceProposal,
)
from wormbase_core.types import CorrelationId
from wormbase_ledger import InMemoryLedger, Ledger


def _is_uuid(s: str) -> bool:
    try:
        UUID(s)
        return True
    except ValueError:
        return False


class MentionedInConversationFlow:
    """Three distinct mentioners of a source archetype within a window -> proposal."""

    def __init__(
        self,
        builder: SourceBuilder,
        ledger: Ledger | InMemoryLedger,
        interjection_gate: _InterjectionGateProto,
        *,
        window_days: int = 7,
        threshold_distinct_persons: int = 3,
    ) -> None:
        self._builder = builder
        self._ledger = ledger
        self._gate = interjection_gate
        self._window = timedelta(days=window_days)
        self._threshold = threshold_distinct_persons

    async def on_semantic_hit(
        self,
        event: InfraEvent,
        interp: SemanticInterpretation,
    ) -> CorrelationId | None:
        # Only fires on data_mention.
        if interp.event_type != "data_mention" or not interp.concepts:
            return None
        if not event.channel_id or not event.person_id:
            return None
        # Note the mention in the ledger as a memory_written entry.
        for archetype in interp.concepts:
            await self._record_mention(event, archetype)

        # For each archetype the current event mentioned, count distinct
        # mentioners over the window.
        for archetype in interp.concepts:
            distinct = await self._count_distinct_mentioners(
                event.company_id, archetype, event.ts
            )
            if distinct < self._threshold:
                continue
            # Skip if a proposal for this archetype already exists in window.
            if await self._has_open_proposal(event.company_id, archetype, event.ts):
                continue
            allowed = await self._gate.allow(
                event.channel_id, "clarification"
            )
            if not allowed:
                return None
            proposal = SourceProposal(
                proposed_uri=f"mention://{archetype}",
                proposed_type="rest_api",
                proposed_domain="general",
                proposed_classification="internal",
                added_via_flow="mentioned_in_conversation",
                added_in_response_to=f"mentions:{archetype}",
                company_id=event.company_id,
            )
            return await self._builder.propose(proposal)
        return None

    async def _record_mention(self, event: InfraEvent, archetype: str) -> None:
        await self._ledger.write(
            company_id=event.company_id,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "mention observed",
                "proposed_by": "mentioned_flow",
            },
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {
                    "memory_id": str(uuid4()),
                    "content": f"source_mention_observed:{archetype}",
                    "tags": [
                        "source_mention_observed",
                        f"archetype:{archetype}",
                        f"person:{event.person_id}",
                        f"channel:{event.channel_id}",
                    ],
                },
                "result_ref": archetype,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "mention_logged", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "mention observed",
            },
            timestamp=event.ts,
            quadrant="passive_deterministic",
        )

    async def _count_distinct_mentioners(
        self, company_id: UUID, archetype: str, until: datetime
    ) -> int:
        rows = await self._ledger.fetch(company_id, until_ts=until)
        threshold_ts = until - self._window
        persons: set[str] = set()
        for r in rows:
            if r["kind"] != "execute":
                continue
            args = r["payload"]["args"]
            if args.get("content") != f"source_mention_observed:{archetype}":
                continue
            if r["ts"] < threshold_ts:
                continue
            for tag in args.get("tags", []):
                if tag.startswith("person:") and tag != "person:None":
                    persons.add(tag)
        return len(persons)

    async def _has_open_proposal(
        self, company_id: UUID, archetype: str, until: datetime
    ) -> bool:
        rows = await self._ledger.fetch(company_id, until_ts=until)
        for r in rows:
            if r["kind"] != "execute":
                continue
            args = r["payload"]["args"]
            if args.get("added_in_response_to") == f"mentions:{archetype}":
                return True
        return False


# ---------------------------------------------------------------------------
# Remote-mention archetype helper.
#
# Step 2 of the canonical product arc adds keyword recognition for SaaS
# data sources (stripe, salesforce, hubspot, snowflake, postgres, s3).
# This helper translates a recognized keyword into a one-shot
# ``source_proposed`` entry with the right URI scheme — used by sim
# scenarios + demo plumbing without modifying the existing
# ``MentionedInConversationFlow`` machinery.
# ---------------------------------------------------------------------------


_REMOTE_ARCHETYPE_URIS: dict[str, tuple[str, SourceKind]] = {
    "stripe": ("https://api.stripe.com/v1", "rest_api"),
    "salesforce": ("https://api.salesforce.com", "rest_api"),
    "hubspot": ("https://api.hubapi.com", "rest_api"),
    "snowflake": ("snowflake://account/wh/db", "database"),
    "postgres": ("postgres://host/db", "database"),
    "s3": ("s3://bucket/prefix", "blob"),
}


def recognized_remote_archetypes(text: str) -> list[str]:
    """Return the lowercase keywords from ``text`` that match a known archetype."""
    if not text:
        return []
    lower = text.lower()
    return [k for k in _REMOTE_ARCHETYPE_URIS if k in lower]


async def propose_remote_archetype(
    builder: SourceBuilder,
    *,
    company_id: UUID,
    archetype: str,
    added_by_person_id: UUID | None = None,
    added_in_response_to: str | None = None,
) -> CorrelationId:
    """Write a single ``source_proposed`` for a recognized archetype.

    Used by the channel-mention path to translate "we should pull from
    stripe" into an actionable proposal. The URI scheme is derived from
    ``_REMOTE_ARCHETYPE_URIS`` so downstream connectors can pick up the
    proposal and run the credential flow.
    """
    if archetype not in _REMOTE_ARCHETYPE_URIS:
        raise ValueError(f"unknown remote archetype: {archetype!r}")
    uri, kind = _REMOTE_ARCHETYPE_URIS[archetype]
    proposal = SourceProposal(
        proposed_uri=uri,
        proposed_type=kind,
        proposed_domain="general",
        proposed_classification="internal",
        proposed_owner_person_id=added_by_person_id,
        added_by_person_id=added_by_person_id,
        added_via_flow="mentioned_in_conversation",
        added_in_response_to=added_in_response_to or f"mention:{archetype}",
        company_id=company_id,
    )
    return await builder.propose(proposal)


# ---------------------------------------------------------------------------
# === Step 2 (proactivity hook) ===
#
# Bind the proactive-mention path onto MentionedInConversationFlow. The
# existing ``on_semantic_hit`` requires N distinct mentioners over a 7-day
# window before proposing — that's the patient lurker behaviour. The
# proactive path below fires ONCE per detected archetype, immediately,
# in response to a single message. The relevance gate decides whether
# the firing happens at all (see ``_DATA_SOURCE_KEYWORDS`` +
# ``_PROACTIVE_MENTION_CONFIDENCE`` in relevance.py).
#
# Two ledger entries are written per call:
#
#   1. ``emit_source_proposed``   — via ``propose_remote_archetype``,
#      tagged ``added_via_flow="mentioned_in_conversation"`` and
#      ``added_in_response_to=f"proactive:<archetype>:<msg_id>"``.
#   2. ``emit_proactive_offer``  — distinct memory_written entry that
#      records the worm's speech act (the offer text, the channel, the
#      message that prompted it). This is what makes the "Bob mentioned
#      Stripe → worm offered → Bob said yes → DM credential" trail
#      reconstructable in the dashboard.
#
# The corresponding offer_text is the suggested DM prompt; callers
# typically post it via ``ConversationContract`` / ``_chat.send`` after
# receiving the return value.
# ---------------------------------------------------------------------------


def _proactive_offer_text(archetype: str) -> str:
    """The worm's hedged proactive offer, keyed on archetype."""
    pretty = {
        "stripe": "Stripe",
        "salesforce": "Salesforce",
        "hubspot": "HubSpot",
        "snowflake": "Snowflake",
        "postgres": "Postgres",
        "postgresql": "Postgres",
        "s3": "S3",
        "google sheets": "Google Sheets",
        "airtable": "Airtable",
        "mixpanel": "Mixpanel",
        "amplitude": "Amplitude",
        "segment": "Segment",
        "fivetran": "Fivetran",
        "dbt": "dbt",
    }.get(archetype, archetype)
    return (
        f"I noticed you mentioned {pretty} — want me to wire that up? "
        f"Reply yes and DM me your {pretty} credentials and I'll connect."
    )


async def _emit_proactive_offer_entry(
    ledger: Ledger | InMemoryLedger,
    *,
    company_id: UUID,
    archetype: str,
    channel_id: str,
    prompted_by_message_id: str,
    prompted_by_person: str | None,
    offer_text: str,
    ts: datetime,
) -> str:
    """Write the ``emit_proactive_offer`` ledger entry, return the offer_id."""
    offer_id = str(uuid4())
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "memory_written",
            "ref_id": offer_id,
            "reason": f"proactive offer for {archetype}",
            "proposed_by": "mentioned_in_conversation_flow",
        },
        execute_fn=lambda: {
            "tool": "emit_proactive_offer",
            "args": {
                "offer_id": offer_id,
                "archetype": archetype,
                "channel_id": channel_id,
                "prompted_by_message_id": prompted_by_message_id,
                "prompted_by_person": prompted_by_person,
                "offer_text": offer_text,
                "tags": [
                    "proactive_offer",
                    f"archetype:{archetype}",
                    f"channel:{channel_id}",
                    f"prompted_by:{prompted_by_message_id}",
                ],
            },
            "result_ref": offer_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "proactive_offer_logged", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "proactive offer recorded",
        },
        timestamp=ts,
        quadrant="active_probabilistic",
    )
    return offer_id


class ProactiveMentionResult(BaseModel):
    """Return shape from ``MentionedInConversationFlow.on_proactive_mention``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    archetype: str
    source_correlation_id: str
    offer_id: str
    offer_text: str
    channel_id: str
    prompted_by_message_id: str


async def _on_proactive_mention(
    self: "MentionedInConversationFlow",
    event: InfraEvent,
) -> ProactiveMentionResult | None:
    """Single-shot proactive proposal driven by the relevance gate.

    Unlike ``on_semantic_hit`` (which patiently waits for N mentioners),
    this path fires immediately — the relevance gate already decided this
    keyword + confidence combination warrants a worm response. Writes:
      1. ``emit_source_proposed`` (added_via_flow=mentioned_in_conversation,
         status conceptually proposed-pending-confirmation)
      2. ``emit_proactive_offer``   (the worm's speech act, with offer_text)
    """
    archetypes = recognized_remote_archetypes(event.text or "")
    if not archetypes or not event.channel_id:
        return None
    archetype = archetypes[0]
    msg_id = event.message_id or "0"
    person_id = (
        UUID(event.person_id)
        if event.person_id and _is_uuid(event.person_id)
        else None
    )
    cid = await propose_remote_archetype(
        self._builder,
        company_id=event.company_id,
        archetype=archetype,
        added_by_person_id=person_id,
        added_in_response_to=f"proactive:{archetype}:{msg_id}",
    )
    offer_text = _proactive_offer_text(archetype)
    offer_id = await _emit_proactive_offer_entry(
        self._ledger,
        company_id=event.company_id,
        archetype=archetype,
        channel_id=event.channel_id,
        prompted_by_message_id=msg_id,
        prompted_by_person=event.person_id,
        offer_text=offer_text,
        ts=event.ts,
    )
    return ProactiveMentionResult(
        archetype=archetype,
        source_correlation_id=str(cid),
        offer_id=offer_id,
        offer_text=offer_text,
        channel_id=event.channel_id,
        prompted_by_message_id=msg_id,
    )


# Append the method onto MentionedInConversationFlow without rewriting
# the original class body (Step 2 is append-only). The bound method is
# the canonical entry point used by the dispatcher in service.py.
MentionedInConversationFlow.on_proactive_mention = _on_proactive_mention  # type: ignore[attr-defined]


__all__ = [
    "MentionedInConversationFlow",
    "ProactiveMentionResult",
    "propose_remote_archetype",
    "recognized_remote_archetypes",
]
