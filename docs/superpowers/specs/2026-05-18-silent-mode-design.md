# Silent Mode — System-wide Listen-Only Flag

**Status:** draft (design approved 2026-05-18)
**Owner:** Ricardo Alanis
**Related code:**
- `packages/wormbase-chat-presence/src/wormbase_chat_presence/presence.py`
- `apps/channel-adapter/src/wormbase_channel_adapter/{service.py,writer.py}`
- `apps/voice-agent/src/wormbase_voice_agent/`
- `apps/worm-core/src/wormbase_core/write_actions.py`

## Problem

Operators need a single switch that puts the entire WormBase stack into
listen-only mode: every inbound event is still ingested, ranked, and stored,
but no outbound action is taken on any surface. Today the closest equivalent
is the per-channel `talkativeness` policy (default `lurker`), but it has
escape hatches that defeat a true silence guarantee:

- DMs always respond (`Presence.should_speak` returns `True` on
  `event.source == "dm"`).
- Channel `@mentions` always respond.
- The voice-agent has an independent egress path (TTS sink) not gated by
  channel `talkativeness`.
- The agent-gateway can invoke MCP write tools (`write_actions`) that
  mutate external systems — also independent of chat presence.

A `lurker` policy on every channel still produces outbound activity through
these paths. We need a system-wide override that cuts all of them.

## Goals

- One flag, one obvious activation surface, no chance of partial activation.
- Listen-everything still works: ingestion, ledger writes, presence/relevance
  decisions all run normally.
- Every suppressed would-have-been-action is captured as a first-class
  ledger entry so operators can see what the system *would have done*.
- Adding a new outbound surface in the future is hard to do without
  hitting the gate (a CI guard makes the omission loud).

## Non-Goals

- Per-tenant silent mode. The flag is process-global; multi-tenant
  deployments toggle for all tenants at once.
- Runtime toggle. Silent mode is set at process start via env var and is
  immutable for the lifetime of the process. No HTTP/CLI flip.
- Suppressing ingestion, `chat_received`, `policy_applied`, or transcript
  writes. The listen invariant requires all of these.

## Design Overview

### Activation

Single environment variable: `WORMBASE_SILENT_MODE`.

- Truthy set: `{"1", "true", "yes", "on"}`, case-insensitive,
  whitespace-stripped.
- Any other non-empty value: logged WARN at boot
  (`WORMBASE_SILENT_MODE='<value>' — not recognized, treating as off`) and
  treated as off. Garbage values must not crash the process; default is
  "talking" because mis-parsing into silence would be a silent failure
  mode of its own.
- Unset / empty: off.
- Read once at process start by each app and cached. `os.environ`
  mutations mid-process do not change behavior.

### Shared module

`packages/wormbase-core/src/wormbase_core/silent_mode.py` exposes:

- `is_silent_mode_enabled() -> bool` — cached on first call.
- `record_suppressed(ledger, *, surface, tool, args, channel_id=None,
  tenant_id=None, presence_reason)` — writes the `reply_suppressed`
  ledger entry. Best-effort: on ledger failure, logs ERROR with the full
  payload and returns; never raises into the egress path and never falls
  through to a real send.

### The three egress gates

Approach A — gate at every outbound boundary. Three callsites:

1. **Chat outbound** — `apps/channel-adapter/.../writer.py` at the `send`
   boundary. Covers Slack + WhatsApp, DMs, channel replies, and
   `@mention` replies (the writer is the common funnel).
2. **Voice-agent TTS** — the audio sink in
   `apps/voice-agent/src/wormbase_voice_agent/`. The synthesis call
   itself may run; the sink consuming the utterance is the gate.
3. **MCP write tools** — `apps/worm-core/src/wormbase_core/write_actions.py`
   at the tool-invocation entry point used by the agent-gateway. This
   is the same checkpoint that enforces optional-effect guards today,
   so the silent-mode check sits alongside the existing guard.

Each gate has the shape:

```python
if is_silent_mode_enabled():
    record_suppressed(
        ledger,
        surface="chat",  # or "voice" / "mcp_write"
        tool=<canonical tool name>,
        args=<would-have-been payload>,
        channel_id=<if applicable>,
        tenant_id=<if applicable>,
        presence_reason=<why it would have spoken>,
    )
    return SuppressedResult(ok=True, suppressed=True, ref_id=uuid4())
# else: normal egress
```

`Presence.should_speak()`, `RulesBasedRelevanceGate`, `InterjectionGate`,
per-channel `talkativeness`, and `_ensure_default_policy` are unchanged.
Silent mode is purely an egress concern; decision logic still runs so the
captured `presence_reason` is meaningful.

### Ledger event: `reply_suppressed`

A new event kind written via the existing ledger `write` shape (so it
replays cleanly).

**Payload fields:**

| Field             | Type     | Meaning                                                                                                                                                |
| ----------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `surface`         | enum     | `"chat"` \| `"voice"` \| `"mcp_write"`                                                                                                                 |
| `tool`            | string   | Canonical tool name (e.g. `emit_chat_sent`, `tts_speak`, the MCP tool id)                                                                              |
| `args`            | object   | The payload the egress would have sent — exact shape varies by tool                                                                                    |
| `channel_id`      | string?  | If applicable                                                                                                                                          |
| `tenant_id`       | uuid?    | If applicable                                                                                                                                          |
| `presence_reason` | string   | Why the system reached the egress: `dm_always_respond` \| `mention` \| `talkativeness:<tk>;<event_type>` \| `mcp_invocation` \| `voice_utterance` etc. |
| `silent_mode_source` | string | `"env"` (for now; future runtime sources would extend this)                                                                                            |

### Suppressed return-value shape

The caller must not crash. Egress gates return a typed `SuppressedResult`
(or `SuppressedToolResult` for `write_actions`) with:

- `ok=True` — the operator's intent in silent mode is that the action be
  a no-op, which counts as "completed" from the agent's point of view.
- `suppressed=True` — so any code that wants to differentiate can.
- `ref_id=<uuid4>` — a stable identifier so downstream code expecting an
  id (e.g. for logging or correlation) gets one. The same uuid appears
  in the `reply_suppressed` ledger entry.

## Data Flow

### Path 1 — Inbound chat (Slack/WhatsApp, DM or channel)

```
inbound webhook / log-tail
   ↓
channel-adapter.service ingests event
   ↓
ledger: chat_received written   ← unchanged, always fires
   ↓
Presence.should_speak(event, interp) → e.g. (True, "dm_always_respond")
   ↓
agent forms reply, hands to writer.send(payload)
   ↓
writer.send() — EGRESS GATE
   if is_silent_mode_enabled():
       record_suppressed(surface="chat", tool="emit_chat_sent",
                         args=payload, channel_id=...,
                         presence_reason="dm_always_respond")
       return SuppressedResult(...)
   else: <normal send>
   ↓ (silent path)
ledger: reply_suppressed written
```

`chat_received` and `policy_applied` still land in the ledger. Only the
outbound `execute` entry is replaced by `reply_suppressed`.

### Path 2 — Agent-gateway MCP write tool

```
agent calls MCP tool (e.g. emit_position_review_decision)
   ↓
write_actions.invoke(tool_name, args)
   ↓
EGRESS GATE
   if is_silent_mode_enabled():
       record_suppressed(surface="mcp_write", tool=tool_name,
                         args=args, tenant_id=...,
                         presence_reason="mcp_invocation")
       return SuppressedToolResult(ok=True, suppressed=True,
                                   ref_id=uuid4())
   else: <normal tool dispatch>
```

### Path 3 — Voice-agent utterance

Same shape as Path 1, gating at the TTS sink.
`presence_reason="voice_utterance"`.

## Error Handling

**Env-var parsing**

- Unrecognized truthy values logged WARN, treated as off.
- Default is "talking" — failing safe to silence would create a different
  silent failure mode.
- Cached at first read.

**Boot-time announcement**

- One INFO log per app at startup: `silent_mode=on surface=<chat|voice|mcp_write>`.
- Apps exposing `/healthz` (channel-adapter does) include `silent_mode`
  in the JSON.

**Ledger write failure recording a suppressed trigger**

- Log ERROR with the full payload. Do **not** raise. Do **not** fall
  through to a real send. The invariant "no outbound" trumps
  trigger-capture completeness; the log line is the recovery artifact.

**Concurrency / ordering**

- `reply_suppressed` writes are async like other ledger entries; no
  ordering guarantee beyond what the ledger provides. Tooling sorts by
  `ts`.

**Partial-coverage risk** — the real failure mode of approach A

- A future outbound surface added without going through one of the three
  gates would leak.
- Mitigations:
  - Per-app unit test `test_silent_mode_blocks_outbound` invokes the
    highest-level service entry with the env var set and asserts zero
    outbound side-effects (mocked transport sees no calls).
  - `scripts/check_silent_mode_coverage.sh` — CI grep guard that fails
    if a new file matching `apps/channel-adapter/src/.../writer*.py`,
    `apps/voice-agent/src/.../sink*.py`, or
    `apps/worm-core/src/.../write_actions*.py` is added without
    referencing `is_silent_mode_enabled`. False positives are silenced
    with a `# silent-mode: not-an-egress` magic comment, documented in
    `DEVELOPERS.md`.

**Interaction with per-channel `lurker` policy**

- Independent. A `proactive` channel under silent mode: `should_speak`
  returns `True`, the agent forms a reply, the writer gate suppresses
  it, the ledger entry records
  `presence_reason="talkativeness:proactive;<event_type>"`.

**DMs and `@mentions`**

- The "DMs always respond" / "`@mentions` always respond" rules live in
  `Presence`, not in the writer. Silent mode overrides at the egress
  boundary — both paths hit the gate.

**Voice-agent mid-utterance**

- The gate sits at the sink consuming the utterance stream. Boot-time
  flag means it is set before any utterance starts; no need to interrupt
  a frame in flight.

## Testing Strategy

**Unit tests (per gate)**

- `packages/wormbase-core/tests/test_silent_mode.py` — env-var parsing
  matrix: truthy on, falsey/unset/garbage off, garbage logs WARN, value
  is cached.
- `apps/channel-adapter/tests/test_writer_silent_mode.py` — call
  `writer.send(payload)` with the flag on; assert (a) no call to the
  underlying Slack/WhatsApp client, (b) a `reply_suppressed` ledger
  entry with the right `surface`, `tool`, `args`, `presence_reason`,
  `channel_id`. Repeat for DM payload and `@mention`-reply payload to
  lock the "no escape hatches" invariant.
- `apps/voice-agent/tests/test_sink_silent_mode.py` — same shape against
  the TTS sink; assert no audio frames produced + ledger entry written.
- `apps/worm-core/tests/test_write_actions_silent_mode.py` — invoke a
  representative MCP write tool; assert the external mutation never
  fires and the returned `SuppressedToolResult` has `ok=True`,
  `suppressed=True`, `ref_id=<uuid>`. Smoke-test one caller in the
  agent loop to confirm it handles the result without crashing.

**Integration test (the leak-prevention guard)**

- `tests/test_silent_mode_end_to_end.py` — boot a minimal stack with
  `WORMBASE_SILENT_MODE=1`, fire one synthetic inbound event of each
  kind (Slack DM, Slack channel mention, WhatsApp message, voice
  utterance, MCP-tool-invoking event). Assert:
  - Outbound transports (mocked) received zero calls across all
    surfaces.
  - For each event there is exactly one corresponding
    `reply_suppressed` ledger entry (or zero, if `Presence` would have
    stayed quiet anyway — that's correct behavior, not a leak).
  - `chat_received` / ingestion entries are present.

This is the single test that, if green, lets operators trust silent
mode.

**Suppression-record schema test**

- `packages/wormbase-core/tests/test_silent_mode_record_schema.py` —
  round-trip a `reply_suppressed` payload through the ledger reader and
  assert all expected fields are present and typed. Locks the schema
  for downstream analytics.

**Failure-path test**

- `test_silent_mode_record_failure_does_not_send` — inject a ledger that
  raises on write; assert no outbound side-effect (invariant survives
  ledger failure) and the error is logged with the payload.

**Explicitly not tested**

- Per-tenant scoping (out of scope).
- Runtime toggle (boot-time only).
- Mid-process env-var mutation effects (cache invariant tested at unit
  level; system-level "doesn't happen").

## Open Questions

None at design time. Risks (partial coverage, ledger-write failure
during capture) are addressed in Error Handling.

## Rollout

1. Land the shared module + ledger event + schema test first (no
   behavior change).
2. Land each gate in its own commit with its unit test, so coverage
   grows monotonically.
3. Land the end-to-end integration test and the CI grep guard last;
   document in `DEVELOPERS.md`.
4. Default off everywhere. Operators opt in by setting
   `WORMBASE_SILENT_MODE=1` in the environment of the processes they
   want silenced (typically: all of them at once).
