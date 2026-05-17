# wormbase-channel-adapter

Python service that tails OpenClaw session JSONL files and writes
`chat_received` / `chat_sent` ledger entries via `wormbase-ledger`.

## How it works

* OpenClaw writes one JSONL file per chat session under
  `~/.openclaw/agents/main/sessions/<uuid>.jsonl`. Every Slack inbound
  message and every assistant reply gets appended as one JSON line.
* This service polls that directory at 500 ms, seeks each file to the
  last byte offset it has consumed, and parses new lines.
* Slack inbound (user message with `Slack message in #...` marker and
  embedded JSON metadata block) → `chat_received` ledger entry.
* Assistant final text reply (`role=assistant`, `stopReason=stop`, no
  `toolCall` blocks) → `chat_sent` ledger entry.
* Tool calls, tool results, model-change events, and the synthetic
  bootstrap prompt are ignored.

Each chat event becomes a 4-step propose / execute / verify / resolve
ledger cycle, all in `quadrant=active_probabilistic`. The execute row's
`payload.args` matches the canonical Pydantic model
(`ChatReceivedPayload` / `ChatSentPayload`) so downstream projectors
can `model_validate(args)` with no schema drift.

## Run

In docker-compose (the demo path):

```bash
make up
make adapter-logs       # follow the adapter
make adapter-inspect    # list recent chat ledger entries
```

Standalone (against a local Postgres or SQLite DSN):

```bash
WORMBASE_LEDGER_DSN=sqlite+aiosqlite:///./dev.sqlite \
OPENCLAW_SESSIONS_PATH=/path/to/sessions \
WORMBASE_ADAPTER_STATE_PATH=./state.json \
uv run --package wormbase-channel-adapter wormbase-channel-adapter run
```

## Test

```bash
make adapter-test
```

Forty-one unit / integration tests cover:
* parser (slack inbound metadata extraction, assistant text
  classification, tool-call / tool-result / header skipping)
* tenant slug → stable UUIDv5
* file-backed offset state with crash-resume
* tailer (incremental reads, partial-line buffering, offset resume)
* writer against `InMemoryLedger` (PEVR cycle, hash chain, schema match)

## Public API for downstream services

Worm-core and the dashboard read chat history via
`wormbase_ledger.Ledger.fetch(company_id)` and filter for
`kind == "execute"` rows whose `payload["tool"]` starts with
`channel_adapter.emit_`. The `payload["args"]` field validates as
`ChatReceivedPayload` or `ChatSentPayload`. See
`wormbase_channel_adapter.cli.inspect_cmd` for a worked example.

For the demo tenant the company UUID is
`tenant_to_company_uuid("baseworm")` (stable across restarts).

## Conversation Provenance

Each `chat_received` entry carries three additive provenance fields on its
`ChatReceivedPayload`. Every wire-driven write stamps them; the writer plumbs
them straight from the `ChatReceivedEvent` into the on-ledger payload.

| Field | Type | Meaning |
|---|---|---|
| `delivery_mode` | `"push"` \| `"history_sync"` | `"push"` for steady-state live delivery; `"history_sync"` for bulk replay (Baileys reconnect, channel-join backfill). Defaults to `"push"` for back-compat. |
| `platform_ts` | `datetime \| None` | Platform-clock authorship time. Distinct from the ledger's `entry.ts` (which is the ingest time). `None` when the platform did not surface the value. |
| `history_sync_id` | `str \| None` | When `delivery_mode == "history_sync"`, the str-UUID of the parent `conversation_sync` entry's `sync_id`. `None` for live deliveries. |

Defaults preserve back-compat: an older entry without these fields parses
fine via `ChatReceivedPayload.model_validate(args)` and reads as a live push
with unknown timestamp — exactly the pre-provenance semantics.

### `conversation_sync` lineage entry

A `conversation_sync` ledger entry is written per **session** — per reconnect,
per initial-connect, per channel-join — at session END. It records the
session's bounds and status:

- `sync_id: UUID` — the session's stable id; `chat_received` entries from this
  session carry this value (str-UUID form) in `history_sync_id`.
- `platform: str`, `install_id: str | None`, `channels: list[str]`,
  `trigger: "initial_connect" | "reconnect" | "channel_join"`.
- `started_at: datetime`, `completed_at: datetime | None`,
  `message_count: int`, `earliest_ts`, `latest_ts`.
- `status: "in_progress" | "completed" | "interrupted"` — interrupted on
  mid-sync `connection_drop`; completed on quiet-window or
  `messaging-history.set`.

Quadrant: `passive_deterministic`. The full PEVR cycle (propose / execute /
verify / resolve) writes via `LedgerWriter.emit_conversation_sync`. The
WhatsApp adapter is the first emitter; the same writer surface accepts any
adapter that opts in.

Sample query — replay one session's messages:

```python
sync_id_str = str(session_uuid)
replay = [
    r for r in await ledger.fetch(company_id)
    if r["kind"] == "execute"
    and r["payload"].get("tool") == "channel_adapter.emit_chat_received"
    and r["payload"]["args"].get("history_sync_id") == sync_id_str
]
```

### Dedup on `(channel_id, message_id)`

`LedgerWriter._emit_chat_received` enforces idempotency at the substrate
level: the same `(channel_id, message_id)` seen twice returns `None` on the
second arrival (no ledger write). LRU-bounded at 1024 distinct keys. This
absorbs Baileys-style replay floods and Slack reconnect duplicates without
poisoning the chain. Per-process state — survives session restart only via
the dedup keys re-entering the LRU on next live arrival.

### Wire-replay round-trips provenance unchanged

Replay reads recorded JSONL `InfraEvent`s and feeds them through the same
production code path. `delivery_mode`, `platform_ts`, and `history_sync_id`
flow through unchanged — replay does not synthesize fresh values. A recorded
`history_sync` event remains `history_sync`; a recorded `push` event with a
5-second-old `platform_ts` remains live.

The freshness window (used by `LiveOnly`) is computed against the recorded
`entry.ts`, **not** wall-clock at replay time. This is load-bearing: wall-clock
at replay is a dev-machine clock long after the original event; using it would
mark every replayed entry stale. Using the recorded `entry.ts` preserves the
original liveness verdict on replay.

### Slack stale-fetch latent fix

Slack's reconnect cycle had a window where a re-fetched message could be
delivered to F1/F2/F4 long after authorship. Pre-provenance code had no
signal to suppress this. Once the SlackChannelAdapter upgrade lands provenance
stamping (out of scope here), `LiveOnly` closes the window without further
code changes: `platform_ts=t_orig, delivery_mode="push"` re-arriving at
`entry.ts >> t_orig + 60s` fails `LiveOnly`, and the speak-path does not fire.

This is a substrate fix, not a Slack-specific patch. Every adapter that opts
into provenance gets the protection.

### Architecture spec

The full provenance + lineage architecture is documented at
`docs/superpowers/specs/2026-05-05-conversation-provenance-architecture.md`.
End-to-end behavior is pinned by
`tests/integration/test_whatsapp_provenance_e2e.py`.
