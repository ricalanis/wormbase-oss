# Conversation Provenance + Lineage Architecture

**Date:** 2026-05-05
**Status:** Authoritative
**Plan:** `docs/superpowers/plans/2026-05-05-whatsapp-and-conversation-provenance.md`
**Doctrine alignment:** `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md`
(Addendum 3 records the +1 kind landed by this work)

This spec codifies the substrate that distinguishes **live conversation** from
**bulk history replay**, and the gating that protects the speak-path from
firing on stale or replayed events. It is the durable expression of what
shipped under Phases 1-4 of the 2026-05-05 plan and what Phase 5 pinned in
documentation and tests.

The model is provenance-and-lineage, not a stored "live flag." Live is a
**derived predicate** off two pieces of data: the per-message `delivery_mode`
and the per-message `platform_ts` (platform-clock timestamp at the moment of
authorship). The freshness window — the threshold beyond which a push delivery
is treated as stale — is policy, not data; it sits in `WORMBASE_FRESHNESS_WINDOW_S`
and defaults to 60 seconds.

---

## 1. Goal

Three concrete commitments:

1. **Provenance per message.** Every `chat_received` ledger entry can answer
   "was this delivered live, or replayed from history?" without consulting
   anything outside the entry's own payload. Audit on a single row.

2. **Lineage per session.** Bulk-import sessions (WhatsApp/Baileys reconnect,
   initial connect, channel join) are first-class ledger events. Each
   per-message `chat_received` entry from the import points back at its
   parent session via `history_sync_id`. Audit on a join.

3. **Speak-path gating.** Reactivities that produce outbound traffic
   (F1 chat triad → flow_dispatcher, F2 mention reply, F4 source-mentioned
   propose) only fire on **live** events. F3 InterjectionBudgetReactivity is
   observation-only and intentionally not gated — its job is to record budget
   consumption regardless of the inbound event's delivery mode.

The architecture is a strict generalization. Slack with no provenance fields
on its existing entries continues to work (defaults are permissive). New
adapters opt into provenance by stamping the fields. Wire-replay round-trips
provenance unchanged.

---

## 2. The model

### Provenance fields

Three fields land additively on `InfraEvent` (both copies — `wormbase_channel_adapters.types.InfraEvent`
and `wormbase_core.reactivity.InfraEvent`) and on `ChatReceivedPayload`:

```python
delivery_mode: Literal["push", "history_sync"] = "push"
platform_ts: datetime | None = None
history_sync_id: str | None = None
```

- `delivery_mode` — the wire-level mode. `"push"` means the platform delivered
  this as a real-time event; `"history_sync"` means it arrived as part of a
  bulk replay (Baileys reconnect, Slack history-fetch, channel-join backfill).
- `platform_ts` — the platform's authorship timestamp (the clock value the
  platform recorded at message creation). Distinct from `entry.ts`, which is
  the ledger-ingest timestamp.
- `history_sync_id` — when `delivery_mode == "history_sync"`, this is the
  string-form UUID of the parent `conversation_sync` ledger entry's `sync_id`.
  When `delivery_mode == "push"`, this is `None`.

All three default safely. Pre-provenance entries replay cleanly: missing
`delivery_mode` defaults to `"push"`, missing `platform_ts` is treated as
"unknown but permissive," missing `history_sync_id` is `None`.

### Lineage entry: `conversation_sync`

A new ledger entry kind, registered in `KIND_REGISTRY` (83 concrete kinds
post-Phase 1; well under the 100 freeze-pause threshold per Doctrine
Addendum 2). Quadrant: `passive_deterministic`.

Payload shape (`ConversationSyncPayload`, in `packages/ledger/src/wormbase_ledger/entries.py`):

```python
sync_id: UUID
platform: str  # "slack" | "whatsapp" | ...
install_id: str | None = None
channels: list[str] = []
trigger: Literal["initial_connect", "reconnect", "channel_join"]
started_at: datetime
completed_at: datetime | None = None
message_count: int = 0
earliest_ts: datetime | None = None
latest_ts: datetime | None = None
status: Literal["in_progress", "completed", "interrupted"] = "in_progress"
```

One `conversation_sync` PEVR cycle is written per **session** — per reconnect,
per initial-connect, per channel-join. The cycle is written at session END
(when the quiet-window timer fires, when an explicit `messaging-history.set`
event arrives, or when the connection drops mid-sync — `interrupted`).
Per-message `chat_received` entries from the same session reference the
sync's `ref_id` via their `history_sync_id`.

### `is_live` derivation

The InfraEvent dataclass exposes `is_live` as a property, not a stored field:

```python
@property
def is_live(self) -> bool:
    if self.delivery_mode != "push":
        return False
    if self.platform_ts is None:
        return True  # permissive when unknown
    return (self.ts - self.platform_ts).total_seconds() < FRESHNESS_WINDOW_S
```

The freshness window defaults to 60 seconds (`_DEFAULT_FRESHNESS_WINDOW_S`),
overridable via `WORMBASE_FRESHNESS_WINDOW_S`. Liveness is not stored anywhere
in the ledger — it is recomputed on demand from the entry's two provenance
inputs.

### `LiveOnly` ReactivityCondition

`packages/reactivities/src/wormbase_reactivities/conditions.py::LiveOnly`
implements the codebase's `ReactivityCondition` Protocol via `allows()`:

```python
class LiveOnly(_ConditionBase):
    async def allows(self, entry, context) -> bool: ...
```

The condition reads `delivery_mode` and `platform_ts` from
`entry.payload.args` (i.e. the on-ledger ChatReceivedPayload form), normalizes
both ISO-8601 strings and datetime instances, and returns:

- `False` when `delivery_mode != "push"` (history_sync, or any future non-push mode)
- `False` when `delivery_mode == "push"` AND `(entry.ts - platform_ts) >= FRESHNESS_WINDOW_S`
- `True` when fields are missing (back-compat for pre-provenance entries — the
  speak-path defaults to permissive when it cannot reason about freshness)
- `True` when `delivery_mode == "push"` AND `(entry.ts - platform_ts) < FRESHNESS_WINDOW_S`

Composes via `__and__` with the existing condition algebra:
`LiveOnly() & DomainEnabled()`, `NotRecentlyFired(...) & LiveOnly() & DomainEnabled()`.
F1/F2/F4 chat-presence reactivities all use this composition; F3 keeps
`AlwaysAllow`.

---

## 3. Slack behavior

Slack is unchanged at the ingest path. The existing `chat_received` flow
through `apps/channel-adapter` continues to write entries; provenance fields
are stamped with their permissive defaults (`delivery_mode="push"`,
`platform_ts=None`, `history_sync_id=None`) until a future SlackChannelAdapter
upgrade backfills them.

**Latent stale-fetch fix.** Slack's reconnect cycle previously had a window
where a re-fetched message could be delivered to F1/F2/F4 long after the
original event. Pre-provenance code had no signal to suppress this. Once the
SlackChannelAdapter upgrade lands provenance stamping (out of scope here —
tracked alongside this spec), `LiveOnly` will close the window without further
code changes: a stamp of `platform_ts=t_orig, delivery_mode="push"` re-arriving
at `entry.ts >> t_orig + 60s` will fail `LiveOnly` and the speak-path will not
fire.

This is a substrate fix, not a Slack-specific patch. The wire protects every
adapter that opts into provenance.

---

## 4. WhatsApp behavior

WhatsApp ships at `status="preview"` via OpenClaw's Baileys plugin (WhatsApp
Web reverse-engineered protocol). Capability: `{"ingest", "dm"}`. Send is NOT
in the capability set — the OpenClaw outbound HTTP route is unverified
upstream (issue #73016 tracks Meta Cloud API support); calling `send()` raises
`NotImplementedError`. This is capability honesty, not omission.

### Sync state machine

The WhatsApp adapter (`packages/channel-adapters/src/wormbase_channel_adapters/whatsapp.py`)
owns an internal three-state machine that distinguishes Baileys' bulk-replay
windows from steady-state push delivery:

```
IDLE ──on_connection_open──▶ SYNC_IN_PROGRESS
        ▲                          │
        │                          ├── on_history_set ─────────▶ LIVE
        │                          ├── 5s quiet timer fires ───▶ LIVE
        │                          └── on_connection_drop ─────▶ IDLE (status="interrupted")
        │                                                            │
        └─────────── on_connection_drop ─────────────────────────────┤
                                                                     ▼
                                                                   LIVE
```

In `SYNC_IN_PROGRESS`, every message is stamped `delivery_mode="history_sync"`
with the active `history_sync_id`. In `LIVE`, every message is stamped
`delivery_mode="push"` with `history_sync_id=None`. On the
`SYNC_IN_PROGRESS → LIVE` transition (or interrupt), the adapter writes the
parent `conversation_sync` ledger entry via the constructor-injected
`sync_emitter` (in production: `LedgerWriter.emit_conversation_sync`).

The 5-second quiet-window heuristic is the empirical crossover where Baileys'
post-reconnect history burst (~50 messages per channel within seconds) settles
into steady-state. An explicit `messaging-history.set` event from Baileys
short-circuits the heuristic when surfaced.

### Opt-in via env

The WhatsApp wire is opt-in via `WHATSAPP_ACCOUNT_ID`. Slack-only deployments
stay byte-identical with pre-Phase-3 behavior — the `platform_admit_handlers`
dispatch dict in `apps/channel-adapter/service.py` only registers a WhatsApp
handler when the env var is set. Without it, `whatsapp: allow channel ...`
log-tail lines hit the existing "no adapter registered" graceful drop branch.

### ToS posture

Baileys is unofficial (WhatsApp Web reverse-engineered library). Account bans
are possible. **Use only on dedicated test numbers — never production CEO
numbers.** Production transport will land via Meta Cloud API once OpenClaw
issue #73016 closes; the current adapter swaps the transport string in the
config block (`transport: "baileys"` → `transport: "meta_cloud_api"`) without
adapter code changes.

The pairing flow and ToS notice live at `infra/openclaw/WHATSAPP_PAIRING.md`.

---

## 5. Wire-replay orthogonality

Provenance is wire-replay-orthogonal. Replay reads recorded JSONL of
`InfraEvent`s and feeds them through `channel-adapter` in replay mode — the
SAME code path as production, deterministic input.

Recorded events round-trip their `delivery_mode`, `platform_ts`, and
`history_sync_id` unchanged. Replay does not synthesize fresh values. A
recorded `history_sync` event remains `history_sync` on replay; a recorded
`push` event with a 5-second-old `platform_ts` remains live on replay.

The freshness window is computed against the entry's own `entry.ts`, not
against wall-clock at replay time. This is load-bearing: wall-clock at replay
is a dev-machine clock 18 months after the original event; using it would
cause every replayed entry to be stale. By using the recorded `entry.ts`, we
preserve the original liveness verdict.

Consequence: wire-replay is the canonical determinism backstop
(per CLAUDE.md §1). It produces identical ledger projections, identical
reactivity-fire decisions, and identical Person/Domain/Resource state to the
original run, modulo the explicitly-allowed sources of nondeterminism (LLM
inference, randomness in retries).

---

## 6. Reactivity gating

| Reactivity | Condition (post-provenance) | Why |
|---|---|---|
| F1 ChatReceivedReactivity (chat triad routing) | `LiveOnly() & DomainEnabled()` | Triad routes to flow_dispatcher → reply path. Suppresses on history-replay. |
| F2 MentionResponseReactivity (@-mention reply) | `LiveOnly() & DomainEnabled()` | A 4-hour-old @-mention re-delivered via reconnect is not a new mention. |
| F3 InterjectionBudgetReactivity (observation-only) | `AlwaysAllow()` | Budget audit must record consumption regardless of how the inbound landed. |
| F4 SourceMentionedReactivity (data-keyword propose) | `NotRecentlyFired("source_mention", hours=1.0) & LiveOnly() & DomainEnabled()` | A reconnect should not propose every source the channel ever mentioned. |

Downstream pipelines that fold `chat_received` for **bronze cascade**
(conversation lake bronze → silver → gold per CLAUDE.md "Conversations as a
first-class data source") accept all delivery modes. The bronze layer is the
conversation history; it must include history-replayed messages, or a
freshly-installed worm gets only post-install conversation. The gating
applies to the speak-path, not to the ingest path.

The split is precise: speak = filtered, ingest = total. F3's observation-only
status is consistent with both — it observes the inbound flow at full
fidelity for budget accounting; the budget-enforcement gate (governance.InterjectionGate)
applies separately at write time.

---

## 7. Traceability — the four questions

Provenance + lineage answer four questions on a single ledger:

| Question | Query (conceptual) |
|---|---|
| What sessions has this WhatsApp install run? | `kind="execute" AND tool="channel_adapter.emit_conversation_sync" AND args.install_id=<id>` |
| Which messages came from session X? | `kind="execute" AND tool="channel_adapter.emit_chat_received" AND args.history_sync_id=<sync_id_str>` |
| Was this message live or replayed? | Read `args.delivery_mode` directly off the chat_received entry. |
| Is this message stale? | Compute `(entry.ts - args.platform_ts) < freshness_window`. (Or call `LiveOnly().allows(entry, ctx)`.) |

Example projection-style queries (against any tenant ledger):

```python
# All conversation_sync sessions for an install:
sessions = [
    r for r in await ledger.fetch(company_id)
    if r["kind"] == "execute"
    and r["payload"].get("tool") == "channel_adapter.emit_conversation_sync"
    and r["payload"]["args"].get("install_id") == install_id
]

# All chat_received entries that came in via session X:
sync_id_str = str(session_uuid)
replay_messages = [
    r for r in await ledger.fetch(company_id)
    if r["kind"] == "execute"
    and r["payload"].get("tool") == "channel_adapter.emit_chat_received"
    and r["payload"]["args"].get("history_sync_id") == sync_id_str
]

# Live vs replay split for a channel:
chat_executes = [
    r for r in await ledger.fetch(company_id)
    if r["kind"] == "execute"
    and r["payload"].get("tool") == "channel_adapter.emit_chat_received"
    and r["payload"]["args"].get("channel_id") == channel_id
]
live = [r for r in chat_executes if r["payload"]["args"].get("delivery_mode") == "push"]
replayed = [r for r in chat_executes if r["payload"]["args"].get("delivery_mode") == "history_sync"]
```

A future projection (`projection_conversation_syncs`, deferred per plan §12)
materializes these queries as a SQL view; the ledger queries above remain the
canonical source of truth.

---

## 8. Cross-references

- **Plan:** `docs/superpowers/plans/2026-05-05-whatsapp-and-conversation-provenance.md`
- **Phase 1 commit (substrate):** `0969537` (provenance fields, `conversation_sync` kind, `LiveOnly` via `allows()`)
- **Phase 1 follow-up:** `8b4e71c`
- **Phase 2 commit (gateway config):** `5fd0cb4` (channels.whatsapp block in OpenClaw entrypoint, transport="baileys")
- **Phase 4 commit (log-tail dispatch):** `3d9df35` (regex generalized, platform_admit_handlers dispatch)
- **Phase 3 commit (WhatsApp adapter):** `6d81bc1` (sync state machine, capability honesty, opt-in via env)
- **Doctrine Addendum 3:** `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md` (records 82 → 83 kinds; freeze-pause at 100)
- **WhatsApp pairing runbook:** `infra/openclaw/WHATSAPP_PAIRING.md`
- **OpenClaw issue #73016:** Meta Cloud API support upstream (gates production WhatsApp send)
- **Module docstring (canonical narrative for the state machine):** `packages/channel-adapters/src/wormbase_channel_adapters/whatsapp.py` (lines 1-61)
- **End-to-end integration test (architectural pin):** `tests/integration/test_whatsapp_provenance_e2e.py`
