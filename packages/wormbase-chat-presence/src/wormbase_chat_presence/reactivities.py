"""Chat-worm Reactivities — one class per chat-triad agent action.

Per spike §C5: each Reactivity composes from W5a's existing
predicate/condition algebra and consumes chat-worm services
(RelevanceGate, ChatReply, ChatStore) via ReactivityContext.extras.
The factory in factory.py produces the four-instance list; the W5a
ReactivityRegistry registers them; the existing ReactivityRunner
dispatches them. **No new orchestrator loop.**

The four Reactivities:
  - ChatReceivedReactivity        — chat triad: infra → semantic → relevance → route
  - MentionResponseReactivity     — @-mention bypass; speaks via ChatReply
  - InterjectionBudgetReactivity  — observation-only; tracks daily budget per channel
  - SourceMentionedReactivity     — data-keyword hit → propose source + ChatReply

Each fire() returns ReactivityResult; observation-only emissions write
PEVR cycles via the canonical _emit_signal pattern.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from wormbase_chat_presence.predicates import DataKeywordMatch, MentionsWorm, match_keyword
from wormbase_chat_presence.types import (
    ChatPolicy,
    ConversationContext,
)
from wormbase_core.reactivity import (
    InfraEvent,
    RelevanceDecision,
    SemanticInterpretation,
)
from wormbase_reactivities.conditions import (
    AlwaysAllow,
    DomainEnabled,
    LiveOnly,
    NotRecentlyFired,
)
from wormbase_reactivities.predicates import EntryKind
from wormbase_reactivities.protocol import (
    FiredAction,
    ReactivityCondition,
    ReactivityContext,
    ReactivityPredicate,
    ReactivityResult,
    ReactivityScope,
)


# ---------------------------------------------------------------------------
# F1 — ChatReceivedReactivity
# ---------------------------------------------------------------------------


@dataclass
class ChatReceivedReactivity:
    """Chat triad runner: infra → semantic → relevance → flow_dispatcher.

    The entry point for every chat event into the chat-worm. Services are
    constructor-injected via `make_chat_reactivities` factory kwargs (per
    the O-B2 spike's Option A recommendation, 2026-05-04):
      - `_chat_store`: ChatStore — for read_policy
      - `_relevance_gate`: RelevanceGate — for should_react
      - `_semantic_classifier`: SemanticTrigger-shaped object — for the
        middle stage of the triad
      - `_flow_dispatcher`: async (event, decision) → None — the chat-worm
        dispatcher; receives the decision and routes to the correct flow

    Does NOT call ChatReply.speak directly. Routing to ChatReply happens in
    MentionResponseReactivity (F2) and SourceMentionedReactivity (F4); this
    Reactivity is a router only.

    scope = "company" — chat triad is tenant-scoped.
    """

    scope: ReactivityScope = "company"
    _chat_store: Any = None
    _relevance_gate: Any = None
    _semantic_classifier: Any = None
    _flow_dispatcher: Any = None

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = EntryKind("chat_received")
        # LiveOnly suppresses fires on history-replay (WhatsApp/Baileys
        # reconnect) and stale-fetch (Slack reconnect) — the speak-path
        # never resurrects a 4-hour-old message because of an
        # infrastructure event. DomainEnabled is the existing
        # admin-toggleable per-domain mute.
        self.condition = LiveOnly() & DomainEnabled()
        self.name = "Chat Received"
        self.description = (
            "Chat triad entrypoint: builds ConversationContext, runs the "
            "semantic classifier and relevance gate, routes the decision "
            "to the chat-worm flow_dispatcher (Block G). Gated by LiveOnly "
            "to suppress history-replay fires."
        )

    @property
    def id(self) -> str:
        return "chat_received"

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        chat_store = self._chat_store
        relevance_gate = self._relevance_gate
        classifier = self._semantic_classifier
        dispatcher = self._flow_dispatcher
        if (
            chat_store is None
            or relevance_gate is None
            or classifier is None
            or dispatcher is None
        ):
            # Misconfigured wiring — log via fired=False so the registry
            # doesn't penalize budgets. wire_chat_for_install asserts all
            # four services are threaded through make_chat_reactivities.
            return ReactivityResult(fired=False, actions=[])

        payload = entry.get("payload") or {}
        args = payload.get("args") or {}
        channel_id = args.get("channel_id")
        text = str(args.get("text") or "")
        is_dm = bool(args.get("is_dm")) or args.get("source") == "dm"
        platform = str(args.get("platform") or "slack")
        ts = entry.get("ts") or datetime.now(UTC)

        # Build InfraEvent for the legacy semantic+relevance call surface.
        infra = InfraEvent(
            source="dm" if is_dm else "channel_message",
            payload=args,
            channel_id=channel_id,
            person_id=str(args.get("sender_person") or "") or None,
            message_id=str(args.get("message_id") or ""),
            ts=ts,
            company_id=context.company_id,
            text=text,
        )

        # Resolve the channel's policy.
        if channel_id:
            policy = await chat_store.read_policy(
                company_id=context.company_id, channel_id=channel_id,
            )
        else:
            policy = ChatPolicy(
                talkativeness="responsive", daily_interjection_budget=3,
            )

        ctx = ConversationContext(
            company_id=context.company_id,
            channel_id=channel_id,
            domain_id=None,  # resolution deferred to a future wave
            is_dm=is_dm,
            classification=args.get("classification") or "internal",
            policy=policy,
        )

        interp: SemanticInterpretation | None = await classifier.handle(infra)
        if interp is None:
            return ReactivityResult(fired=False, actions=[])

        decision: RelevanceDecision = await relevance_gate.should_react(
            ctx, infra, interp,
        )

        if decision.should_react:
            try:
                # The dispatcher's signature mirrors the existing
                # `flow_dispatcher` parameter on the worm-core poller.
                synthesized = {
                    "type": "channel_message" if not is_dm else "dm",
                    "ts": ts,
                    "channel_id": channel_id,
                    "user_id": str(args.get("sender_person") or ""),
                    "text": text,
                    "message_id": str(args.get("message_id") or ""),
                    "company_id": str(context.company_id),
                    "payload": args,
                    "platform": platform,
                }
                await dispatcher(synthesized, decision)
            except Exception:
                return ReactivityResult(fired=False, actions=[])

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="chat_routed", action_seqs=[])],
            novelty_key="",
            budget_used={},
        )


# ---------------------------------------------------------------------------
# F2 — MentionResponseReactivity
# ---------------------------------------------------------------------------


@dataclass
class MentionResponseReactivity:
    """@-mention bypass — speaks via ChatReply on every @worm event.

    Bypasses interjection budget (per spike §6 — @-mentions are user-initiated
    so they don't consume the worm's daily proactive-question budget).

    Services are constructor-injected via `make_chat_reactivities` (O-B2):
      - `_chat_reply`: ChatReply — to speak
      - `_chat_store`: ChatStore — for read_policy

    v1 fire body posts a literal "Acknowledged." reply. Real answer content
    is a future-wave concern (responder protocol).

    scope = "company".
    """

    handle: str = "@worm"
    scope: ReactivityScope = "company"
    _chat_reply: Any = None
    _chat_store: Any = None

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        from wormbase_reactivities.predicates import And
        self.predicate = And(
            EntryKind("chat_received"),
            MentionsWorm(handle=self.handle),
        )
        # LiveOnly + DomainEnabled — even @-mentions don't resurrect on
        # a Baileys history replay (or a Slack stale-fetch). A 4-hour-old
        # @-mention re-delivered via reconnect is not a new mention.
        self.condition = LiveOnly() & DomainEnabled()
        self.name = "Mention Response"
        self.description = (
            f"Acknowledges @-mentions of {self.handle!r} via ChatReply.speak. "
            "Bypasses interjection budget. Gated by LiveOnly."
        )

    @property
    def id(self) -> str:
        return "mention_response"

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        chat_reply = self._chat_reply
        chat_store = self._chat_store
        if chat_reply is None or chat_store is None:
            return ReactivityResult(fired=False, actions=[])

        args = (entry.get("payload") or {}).get("args") or {}
        channel_id = args.get("channel_id")
        message_id = str(args.get("message_id") or "")

        if not channel_id:
            return ReactivityResult(fired=False, actions=[])

        policy = await chat_store.read_policy(
            company_id=context.company_id, channel_id=channel_id,
        )
        ctx = ConversationContext(
            company_id=context.company_id,
            channel_id=channel_id,
            domain_id=None,
            is_dm=bool(args.get("is_dm")),
            classification=args.get("classification") or "internal",
            policy=policy,
        )

        ref = await chat_reply.speak(
            ctx,
            "Acknowledged.",
            speech_act="answer",
            in_reply_to=message_id or None,
        )
        if ref is None:
            return ReactivityResult(fired=False, actions=[])

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="chat_reply_proposed", action_seqs=[])],
            novelty_key="",
            budget_used={},
        )


# ---------------------------------------------------------------------------
# F3 — InterjectionBudgetReactivity (observation-only)
# ---------------------------------------------------------------------------


@dataclass
class _ClarifyAskedPredicate:
    """Internal predicate: matches emit_memory_written with content prefix `clarify_asked:`.

    Chat-worm-private — not added to W5a's predicates registry because
    InterjectionBudgetReactivity is the only consumer. Future budget-style
    Reactivities can lift this to W5a predicates if needed.
    """

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        if entry.get("kind") != "execute":
            return False
        payload = entry.get("payload") or {}
        if payload.get("tool") != "emit_memory_written":
            return False
        args = payload.get("args") or {}
        content = str(args.get("content") or "")
        return content.startswith("clarify_asked:")


@dataclass
class InterjectionBudgetReactivity:
    """Observation-only: tracks daily interjection budget consumption per channel.

    Fires after each clarify_asked entry; if today's count crosses the
    channel's daily_interjection_budget, emits a policy_applied SNAPSHOT
    with rule="interjection_budget_consumed:<channel>" recording the
    threshold-cross moment. The snapshot is a doctrine §3 observation-only
    PEVR cycle — verify_fn passes, resolve_fn keeps.

    Does NOT itself enforce a budget; enforcement is in the
    governance.InterjectionGate. This Reactivity is the AUDIT TRAIL — it
    records that the budget was consumed for governance dashboards.

    Service is constructor-injected via `make_chat_reactivities` (O-B2):
      - `_chat_store`: ChatStore — for count_interjections_today + read_policy

    scope = "company".
    """

    scope: ReactivityScope = "company"
    _chat_store: Any = None

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        self.predicate = _ClarifyAskedPredicate()
        self.condition = AlwaysAllow()
        self.name = "Interjection Budget"
        self.description = (
            "Observation-only: emits a policy_applied snapshot when a "
            "channel's daily interjection budget is consumed."
        )

    @property
    def id(self) -> str:
        return "interjection_budget"

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        chat_store = self._chat_store
        if chat_store is None:
            return ReactivityResult(fired=False, actions=[])

        args = (entry.get("payload") or {}).get("args") or {}
        content = str(args.get("content") or "")
        if not content.startswith("clarify_asked:"):
            return ReactivityResult(fired=False, actions=[])
        channel_id = content.split(":", 1)[1]

        now = entry.get("ts") or datetime.now(UTC)
        count = await chat_store.count_interjections_today(
            company_id=context.company_id, channel_id=channel_id, now=now,
        )
        policy = await chat_store.read_policy(
            company_id=context.company_id, channel_id=channel_id,
        )
        if count < policy.daily_interjection_budget:
            # Budget not yet consumed — no observation to record.
            return ReactivityResult(fired=False, actions=[])

        # Threshold crossed — emit a policy_applied snapshot.
        snapshot_id = uuid4_factory()
        await context.ledger.write(
            company_id=context.company_id,
            propose={
                "target_kind": "policy_applied",
                "ref_id": str(snapshot_id),
                "reason": f"interjection_budget_consumed:{channel_id}",
                "proposed_by": "chat-worm",
            },
            execute_fn=lambda sid=snapshot_id: {
                "tool": "emit_policy_applied",
                "args": {
                    "policy_id": str(sid),
                    "policy_name": "policy:channel_talkativeness",
                    "applies_to": {"scope": "channel", "channel_id": channel_id},
                    "rule": f"interjection_budget_consumed:{channel_id}:{count}",
                    "gate_impl": "channel_talkativeness_default",
                    "talkativeness": policy.talkativeness,
                    "daily_interjection_budget": policy.daily_interjection_budget,
                    "current_count": count,
                },
                "result_ref": channel_id,
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "snapshot_recorded", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "interjection budget consumed observation",
            },
            timestamp=now,
            quadrant="active_deterministic",
        )

        return ReactivityResult(
            fired=True,
            actions=[FiredAction(action_kind="policy_applied", action_seqs=[])],
            novelty_key="",
            budget_used={},
        )


# ---------------------------------------------------------------------------
# F4 — SourceMentionedReactivity
# ---------------------------------------------------------------------------


@dataclass
class SourceMentionedReactivity:
    """Data-keyword in chat → MentionedInConversationFlow → ChatReply.speak(proposal).

    Composes the data-keyword detection (DataKeywordMatch) with the
    1-hour novelty gate (NotRecentlyFired) to avoid spamming the same
    archetype offer.

    Services are constructor-injected via `make_chat_reactivities` (O-B2):
      - `_chat_store`: ChatStore — for read_policy
      - `_chat_reply`: ChatReply — to speak the offer text
      - `_mentioned_in_conversation_flow`: MentionedInConversationFlow —
        produces the offer_text (lifted body from flows.py:976-1024)

    scope = "company".
    """

    scope: ReactivityScope = "company"
    _chat_store: Any = None
    _chat_reply: Any = None
    _mentioned_in_conversation_flow: Any = None

    predicate: ReactivityPredicate = field(init=False)
    condition: ReactivityCondition = field(init=False)
    name: str = field(init=False)
    description: str = field(init=False)

    def __post_init__(self) -> None:
        from wormbase_reactivities.predicates import And
        self.predicate = And(EntryKind("chat_received"), DataKeywordMatch())
        # NotRecentlyFired guards against keyword-spam novelty;
        # LiveOnly guards against speech on history-replay messages
        # (a 4-hour-old "we should pull from Stripe" replayed via
        # reconnect is not a fresh source-mention). DomainEnabled is
        # the per-domain mute.
        self.condition = (
            NotRecentlyFired(novelty_key="source_mention", hours=1.0)
            & LiveOnly()
            & DomainEnabled()
        )
        self.name = "Source Mentioned"
        self.description = (
            "Data-source-keyword hit in chat → propose source + speak offer. "
            "1-hour novelty window per (keyword, channel). Gated by LiveOnly."
        )

    @property
    def id(self) -> str:
        return "source_mentioned"

    async def fire(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> ReactivityResult:
        chat_store = self._chat_store
        chat_reply = self._chat_reply
        flow = self._mentioned_in_conversation_flow
        if chat_store is None or chat_reply is None or flow is None:
            return ReactivityResult(fired=False, actions=[])

        args = (entry.get("payload") or {}).get("args") or {}
        channel_id = args.get("channel_id")
        text = str(args.get("text") or "")
        kw = match_keyword(text)
        if not channel_id or not kw:
            return ReactivityResult(fired=False, actions=[])

        ts = entry.get("ts") or datetime.now(UTC)
        infra = InfraEvent(
            source="channel_message",
            payload=args,
            channel_id=channel_id,
            person_id=str(args.get("sender_person") or "") or None,
            message_id=str(args.get("message_id") or ""),
            ts=ts,
            company_id=context.company_id,
            text=text,
        )

        result = await flow.on_proactive_mention(infra)
        if result is None:
            return ReactivityResult(fired=False, actions=[])

        policy = await chat_store.read_policy(
            company_id=context.company_id, channel_id=channel_id,
        )
        ctx = ConversationContext(
            company_id=context.company_id,
            channel_id=channel_id,
            domain_id=None,
            is_dm=False,
            classification=args.get("classification") or "internal",
            policy=policy,
        )

        ref = await chat_reply.speak(
            ctx, result.offer_text, speech_act="proposal",
        )
        if ref is None:
            return ReactivityResult(fired=False, actions=[])

        return ReactivityResult(
            fired=True,
            actions=[
                FiredAction(action_kind="source_proposed", action_seqs=[]),
                FiredAction(action_kind="chat_reply_proposed", action_seqs=[]),
            ],
            novelty_key=f"source_mention:{kw}:{channel_id}",
            budget_used={"per_owner": 1},
        )


def uuid4_factory() -> UUID:
    """Wrapper for testability (mock at module scope)."""
    return uuid4()
