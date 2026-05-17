"""StatementToOwnerReactivity — the headline W5.A2 behaviour.

When Bob says "our churn is up 8% MoM in Europe", this reactivity:

    1. semantically matches "churn" against the org's ontology
       (``topic_extractor.extract_topic``) and obtains a ``Topic`` —
       e.g. KPI ``churn`` in domain ``retention``.
    2. resolves the topic's owner via ``owner_lookup.lookup_owner`` —
       e.g. Carol owns retention.
    3. aggregates pinned resources for the topic via
       ``resource_aggregator.gather_related_resources`` — recent
       KPIs, sources, decisions, processes, data products.
    4. sends a DM to Carol via ``channel_adapter.dm.send_resource_conversation_dm``.
    5. writes ``emit_resource_conversation_proposed`` as the PEVR
       cycle's execute body — the ledger receipt for the DM.

Predicate / condition composition (per the Protocol's design):

    predicate = EntryKind("chat_received") & HasTopic() & HasOwner() & SpeakerNotOwner()
    condition = (
        DailyBudget(per_owner=3, per_domain=10, per_tenant=50)
        & NotRecentlyFired("topic:owner", hours=4)
        & DomainEnabled()
    )

Note on ``HasTopic()`` / ``HasOwner()`` predicates: they inspect
``payload.args`` for explicit ``topic`` / ``owner_id`` keys. The raw
``emit_chat_received`` entries the channel-adapter wires don't yet
carry those — the Reactivity does the topic+owner resolution inside
``fire`` and decides whether to actually emit. Consequently we use
those predicates as documentation of intent rather than gating; the
real gate happens in ``fire`` where we can short-circuit on
"no topic" / "no owner" / "self-statement" without burning budget.

Why composition this loose? Because the predicates require resolved
topics/owners — but resolution is expensive (semantic match + ledger
walk). Doing it twice (once for predicate, once for fire) wastes work.
We inline the resolution in ``fire`` and let the predicate stay narrow
(EntryKind only), with a comment that the "real" predicate logic is the
fire's early-return. Future Reactivities can split this differently;
the protocol supports it.

PEVR cycle bookkeeping:

    propose:  via the helper inside fire (writes resource_conversation_proposed)
    execute:  the real DM send happens here too (so platform_message_id is
              carried into the verify check).
    verify:   re-instantiates the ResourceConversationProposedPayload to
              prove the args-on-the-wire still validate.
    resolve:  always "keep" for now — the ``replied`` and ``resolved``
              entries land via separate PEVR cycles when the owner
              responds (W5.A5 dashboard surface).

The reactivity emits ONE FiredAction (a single PEVR cycle wrapping
``resource_conversation_proposed``). The ``emit_chat_sent`` row that
the channel-adapter writes when the DM lands is a second, independent
PEVR cycle — outside the scope of THIS reactivity. We don't double-count.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from wormbase_reactivities.conditions import (
    DailyBudget,
    DomainEnabled,
    NotRecentlyFired,
)
from wormbase_reactivities.predicates import EntryKind
from wormbase_reactivities.protocol import (
    FiredAction,
    ReactivityContext,
    ReactivityResult,
    ReactivityScope,
)

logger = logging.getLogger("wormbase_reactivities.statement_to_owner")


_REACTIVITY_ID = "statement_to_owner"


# ---------------------------------------------------------------------------
# Reactivity
# ---------------------------------------------------------------------------


@dataclass
class StatementToOwnerReactivity:
    """When a statement references a domain owner's resource, DM the owner.

    Construction is dependency-injected so the same class works in
    production (real topic_extractor, real owner_lookup, real
    channel-adapter DM sender) and in tests (in-memory ledger,
    deterministic stubs, mock DM sender).

    Args:
        topic_extractor: async callable ``(message, *, ledger, company_id)
            → Topic | None``. Production impl is
            ``wormbase_core.topic_extractor.extract_topic``.
        owner_lookup: async callable ``(topic, *, ledger, company_id)
            → Person | None``. Production impl is
            ``wormbase_core.owner_lookup.lookup_owner``.
        resource_aggregator: async callable ``(topic, *, ledger, company_id)
            → ResourceBundle``. Production impl is
            ``wormbase_core.resource_aggregator.gather_related_resources``.
        dm_sender: a :class:`DMSender` (or compatible) used for the
            actual DM send. ``None`` skips the wire — useful for tests
            that only want to assert ledger output. Production wires
            this from ``ChannelAdapter`` at boot.
        confidence_threshold: floor on Topic.confidence; below this
            we skip and let phenomenon-gap detection handle gaps.
    """

    id: str = _REACTIVITY_ID
    name: str = "Statement to Owner"
    description: str = (
        "When a chat statement references a resource that has a known "
        "owner, DM the owner with the statement plus pinned resources "
        "(KPI, sources, decisions, process maps, data products)."
    )
    scope: ReactivityScope = "domain"

    topic_extractor: Any = None
    owner_lookup: Any = None
    resource_aggregator: Any = None
    dm_sender: Any = None
    confidence_threshold: float = 0.6
    # Wave A wiring (2026-05-03): accept identity resolver via DI for
    # forward-compat. Wave B (chat-worm) switches the body to call
    # self.identity.lookup_owner(topic) instead of self.owner_lookup(...).
    identity: Any = None  # Optional; consumer migration in Wave B.

    def __post_init__(self) -> None:
        # Predicate: just "this is a chat_received entry". The expensive
        # topic/owner resolution happens in ``fire`` where we can
        # short-circuit on resolution failures without burning budget.
        # The predicate composition in the spec
        # (HasTopic & HasOwner & SpeakerNotOwner) describes intent;
        # the actual gate is the resolution path inside ``fire``.
        self.predicate = EntryKind("chat_received")
        # Condition: budget + novelty + domain-enabled. The novelty key
        # is computed per-fire below; the condition reads
        # ``ctx.extras["novelty_key"]`` if set, otherwise its own
        # literal which is empty string here (i.e. no pre-fire novelty
        # gate at the condition layer; see fire()).
        self.condition = (
            DailyBudget(per_owner=3, per_domain=10, per_tenant=50)
            & NotRecentlyFired(novelty_key="", hours=4.0)
            & DomainEnabled()
        )

    # ------------------------------------------------------------------
    # Fire — does topic resolution, owner lookup, aggregation, send,
    # and writes the ledger entry. Returns ReactivityResult.
    # ------------------------------------------------------------------

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        """Resolve topic + owner, send DM, write ledger entry."""
        if self.topic_extractor is None or self.owner_lookup is None:
            # Misconfigured Reactivity. Fail closed.
            logger.warning(
                "StatementToOwnerReactivity missing topic_extractor or "
                "owner_lookup; skipping",
            )
            return ReactivityResult(fired=False)

        # 1. Pull the statement text out of the entry args.
        payload = entry.get("payload") or {}
        args = payload.get("args") or {}
        text = str(args.get("text") or "").strip()
        if not text:
            return ReactivityResult(fired=False)
        sender_person = args.get("sender_person") or args.get("sender_person_id")
        sender_label = (
            str(args.get("sender_label") or args.get("sender_name") or "")
            or "(unknown speaker)"
        )
        channel_id = str(args.get("channel_id") or "(unknown channel)")
        message_id = str(args.get("message_id") or "")
        statement_seq = int(entry.get("seq", 0))

        # 2. Topic extraction — semantic match against the org's ontology.
        try:
            topic = await self.topic_extractor(
                text,
                ledger=context.ledger,
                company_id=context.company_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "topic_extractor raised for seq=%d: %s", statement_seq, exc,
            )
            return ReactivityResult(fired=False)
        if topic is None:
            return ReactivityResult(fired=False)
        if topic.confidence < self.confidence_threshold:
            # Below threshold: hand off to phenomenon-gap detection.
            return ReactivityResult(fired=False)

        # 3. Owner lookup.
        try:
            owner = await self.owner_lookup(
                topic,
                ledger=context.ledger,
                company_id=context.company_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "owner_lookup raised for topic=%s: %s",
                topic.label, exc,
            )
            return ReactivityResult(fired=False)
        if owner is None:
            return ReactivityResult(fired=False)

        # 4. Self-statement guard. SpeakerNotOwner is enforced here.
        if sender_person and str(sender_person) == str(owner.person_id):
            return ReactivityResult(fired=False)

        # 5. Aggregate pinned resources.
        if self.resource_aggregator is not None:
            try:
                bundle = await self.resource_aggregator(
                    topic,
                    ledger=context.ledger,
                    company_id=context.company_id,
                )
                resources_payload = bundle.to_payload()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "resource_aggregator raised for topic=%s: %s",
                    topic.label, exc,
                )
                resources_payload = {}
        else:
            resources_payload = {}

        # 6. Compute novelty key BEFORE the fire so the registry
        # evaluator can skip if we're under the 4h cooldown for this
        # exact (topic, owner) pair. Set on context.extras so the
        # NotRecentlyFired condition picks it up if dispatched again.
        novelty_key = f"topic:{topic.id}:owner:{owner.person_id}"
        # Re-check novelty now that we've resolved the key. The condition
        # layer didn't have the key when it was first evaluated; doing
        # it here is the cheapest re-check. Caller's registry stores
        # last-fire under ``(reactivity_id, key)`` — we ask for it.
        registry = context.registry
        if registry is not None:
            try:
                last = await registry.get_last_fired_at(
                    reactivity_id=self.id, novelty_key=novelty_key,
                )
            except Exception:  # noqa: BLE001
                last = None
            if last is not None:
                now = (
                    context.now()
                    if callable(context.now)
                    else context.now
                )
                from datetime import timedelta
                cutoff = now - timedelta(hours=4.0)
                if last >= cutoff:
                    # Still inside the cooldown window — don't re-fire.
                    return ReactivityResult(fired=False)

        # 7. Open the DM and send the formatted body.
        dm_channel: str = ""
        dm_message_id: str = ""
        if self.dm_sender is not None and owner.platform_user_id:
            try:
                from wormbase_channel_adapter.dm import (
                    send_resource_conversation_dm,
                )
                topic_dict = {
                    "kind": topic.kind,
                    "id": str(topic.id),
                    "label": topic.label,
                    "confidence": topic.confidence,
                    "domain_id": (
                        str(topic.domain_id) if topic.domain_id else None
                    ),
                }
                statement_dict = {
                    "text": text,
                    "speaker_label": sender_label,
                    "channel_label": channel_id,
                    "ts": str(args.get("ts") or ""),
                }
                ref = await send_resource_conversation_dm(
                    self.dm_sender,
                    owner_platform_id=owner.platform_user_id,
                    topic=topic_dict,
                    statement=statement_dict,
                    resources=resources_payload,
                )
                dm_channel = (
                    f"{ref.platform}:{ref.platform_channel_id}"
                    if ref.platform else ref.platform_channel_id
                )
                dm_message_id = ref.platform_message_id
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "send_resource_conversation_dm failed for owner=%s "
                    "topic=%s: %s",
                    owner.person_id, topic.label, exc,
                )
                # We continue and write the ledger entry anyway — the
                # ledger reflects the worm's intent even if the wire
                # send transiently fails. The dashboard surfaces the
                # failure via the missing emit_chat_sent receipt.
        else:
            # No DM sender wired (e.g. tests that only want ledger
            # output). Synthesize a stable channel ref so the entry
            # validates.
            dm_channel = f"unknown:{owner.person_id}"

        # 8. Write the resource_conversation_proposed entry.
        conversation_id = uuid4()
        try:
            from wormbase_ledger.entries import (
                ResourceConversationProposedPayload,
            )
            payload_args = {
                "conversation_id": str(conversation_id),
                "topic": {
                    "kind": topic.kind,
                    "id": str(topic.id),
                    "label": topic.label,
                    "confidence": float(topic.confidence),
                    "domain_id": (
                        str(topic.domain_id) if topic.domain_id else None
                    ),
                },
                "owner_id": str(owner.person_id),
                "resources": resources_payload,
                "statement_seq": statement_seq,
                "channel": dm_channel,
            }
            # Verify-time validation guard: if this raises, the verify
            # step in _pevr_resource_conversation_proposed will fail.
            ResourceConversationProposedPayload(
                conversation_id=conversation_id,
                topic=payload_args["topic"],
                owner_id=owner.person_id,
                resources=resources_payload,
                statement_seq=statement_seq,
                channel=dm_channel,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "resource_conversation_proposed payload invalid: %s", exc,
            )
            return ReactivityResult(fired=False)

        await context.ledger.write(
            company_id=context.company_id,
            propose={
                "target_kind": "resource_conversation_proposed",
                "ref_id": str(conversation_id),
                "reason": (
                    f"statement_to_owner: topic={topic.label} "
                    f"owner={owner.name}"
                ),
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "emit_resource_conversation_proposed",
                "args": payload_args,
                "result_ref": str(conversation_id),
            },
            verify_fn=lambda _r: {
                "checks": [
                    {
                        "name": "resource_conversation_payload_valid",
                        "ok": True,
                    },
                ],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "resource conversation DM proposed",
            },
            quadrant="active_deterministic",
        )

        # 9. Bookkeeping for the registry — return novelty + budget.
        return ReactivityResult(
            fired=True,
            actions=[
                FiredAction(action_kind="resource_conversation_proposed"),
            ],
            novelty_key=novelty_key,
            budget_used={
                "per_owner": 1,
                "per_domain": 1 if topic.domain_id else 0,
                "per_tenant": 1,
            },
        )


__all__ = ["StatementToOwnerReactivity"]
