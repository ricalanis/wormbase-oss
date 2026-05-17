# ADR-0004: Chat Presence reactivity for channel-first conversation ingest

**Status:** Accepted
**Date:** 2026-05-03

## Context

Before this decision, chat handling in WormBase lived as a tangle of modules
inside `apps/worm-core`: `service.py`'s chat poller, `conversation.py`'s
`ConversationContract`, `relevance.py`'s rules-based gate, `lurker.py`'s
optional second Slack socket, `setup_conversation.py`'s tenant-driving
DM scripts, and four chat-driven source-building flows inside `flows.py`.
The chat triad (infrastructure → semantic → relevance) was implicit;
talkativeness and the daily interjection budget were constructor arguments
with no projection-backed home; the worm could detect intent to speak but
had no PEVR-tracked write primitive for actually speaking.

The chat surface needed to become a named-actor package — one of the five
worms-as-packages anchoring the architecture. The lake-maintainer template
established the shape: a public Protocol surface, a `make_*_reactivities`
factory, a `wire_*_for_install` lifecycle hook, and composition with the
W5a `ReactivityRegistry` rather than a new orchestrator loop.

## Decision

WormBase ships **`packages/wormbase-chat-presence`** as the chat worm. Its
public surface is a Protocol triad plus four Reactivities plus an outbound
speech primitive:

```python
class ChatPolicy(Protocol):
    talkativeness: Literal["lurker", "responsive", "proactive"]
    daily_interjection_budget: int

class ConversationContext(Protocol):
    company_id: UUID
    channel_id: str | None
    domain_id: UUID | None
    is_dm: bool
    classification: Classification
    policy: ChatPolicy

class RelevanceGate(Protocol):
    async def should_react(
        self, ctx: ConversationContext, msg: Message,
    ) -> RelevanceDecision: ...

class ChatReply(Protocol):
    async def speak(
        self,
        ctx: ConversationContext,
        text: str,
        *,
        speech_act: Literal["answer", "proposal", "clarification"],
    ) -> MessageRef: ...
```

Four Reactivities register with the existing W5a `ReactivityRegistry`:

- `ChatReceivedReactivity` — runs the chat triad (infrastructure trigger →
  semantic trigger → relevance gate), routes to flows.
- `MentionResponseReactivity` — @-mention bypasses the interjection budget.
- `InterjectionBudgetReactivity` — observation-only, tracks the daily budget
  per channel.
- `SourceMentionedReactivity` — data-keyword hit proposes a source.

Talkativeness becomes **projection-backed state**, not a constructor
argument. A new `projection_channels` table is created in the same wave,
folded from `policy_applied` entries with template
`policy:channel_talkativeness`. A new `ChatStore` Protocol exposes
`read_messages` / `read_policy` / `count_interjections_today` as a
substrate-swappable read layer.

`ChatReply` is a new write primitive — the worm-side intent to speak — that
emits a four-cycle `chat_reply_*` PEVR sequence (`proposed → executed →
verified → resolved`) and triggers the channel-adapter's outbound send. The
existing `emit_chat_sent` entry remains as the platform-side echo. Four new
entry kinds, deliberately additive.

Scope tightenings versus the original ambition:

- `lurker.py` (Slack-Bolt second socket) stays in worm-core as a legacy
  fallback; it carries a hard `slack_bolt` dependency and would reverse the
  package's platform-agnostic stance.
- `DashboardFormFlow` belongs to the dashboard write surface, not chat.
- `LakeDiscoveryFlow` is a one-shot install-time CLI helper, not chat.
- `setup_conversation.py` splits: chat-presence owns the DM driver
  (`SetupDmDriver`, YAML script load, answer parser); worm-core's
  `onboarding/` retains the per-tenant scan and the setup-step ledger
  writes. The seam is the natural import boundary already visible in the
  code.
- The chat poller (`chat_received_reactivity_poller`) stays in worm-core as
  infrastructure; chat-presence ships only Reactivities and the dispatcher
  the poller threads through.

## Consequences

**Positive:**

- The chat triad and the speech primitives become a single coherent
  package, addressable independently from the rest of the worm.
- Talkativeness is "policy is code": a `policy_applied` entry mutates a
  channel's posture; the worm folds it on next read. The dashboard's
  `/channels` tab can render and edit talkativeness without reaching into
  worm-core internals.
- `ChatReply` makes the worm's intent to speak a first-class ledger entry,
  audit-equivalent to every other write. The platform-side `emit_chat_sent`
  remains the echo; the worm-side `chat_reply_*` PEVR cycle is the intent.
- Lift fraction is ~78%: mostly renames and module moves with light
  refactors. The ~22% of net new code is the Reactivities, the `ChatReply`
  primitive, the `projection_channels` migration, and the factory/lifecycle
  wiring.

**Negative:**

- Four new entry kinds (`chat_reply_proposed`, `chat_reply_executed`,
  `chat_reply_verified`, `chat_reply_resolved`) consume registry budget per
  the schema-evolution doctrine.
- The lurker module remains in worm-core unresolved. Either it deletes once
  the channel-adapter log-tail is the canonical path in production, or it
  stays as a known second-Slack-socket fallback. Either way, it is not
  chat-presence's responsibility.
- The chat-presence package depends on the `InterjectionGate` in the
  governance package for budget enforcement, reading its state via
  `ChatStore`. This is correct composition but it does mean chat-presence
  imports from governance — the dependency direction must stay clean.

**Neutral:**

- The chat poller's `flow_dispatcher` parameter becomes the seam:
  chat-presence's factory produces the dispatcher (which internally runs
  the four Reactivities); the poller calls it. Same pattern as
  lake-maintainer.
- `classifier.py` is chat-presence-private for v1. A future inference-router
  consolidation wave can pull it out when a second consumer appears (likely
  process-worm or research-worm); shipping the empty inference-router
  package on the critical path would be over-architecture today.

## Cross-references

- Related ADRs: ADR-0003 (chat-presence follows the same package template);
  ADR-0005 (the `RulesBasedRelevanceGate` lifts into the governance package
  rather than staying chat-private); ADR-0007 (identity discovery feeds
  chat-presence's `ConversationContext`).
- Architecture: `ARCHITECTURE.md` §4 ("The ChannelAdapter contract") and
  the worm decomposition in §2.
