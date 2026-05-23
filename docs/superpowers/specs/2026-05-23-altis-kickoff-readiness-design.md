# Altis Kickoff Readiness — Sprint 1 Design

**Status:** in-flight (kickoff Monday 2026-05-25)
**Owner:** Ricardo Alanis
**Customer:** Altis (Poncho Garciga, Ruben Madiedo) — design partner #1

## Context

Per the call recorded 2026-05-22 (`Altis-Wormbase-72b96c65-7eaf.srt`), Ricardo
committed to:

1. **Internal WhatsApp group** Monday — Poncho + Ruben + Ricardo + WormBase bot.
2. **Bot silent in client channels** — Altis invites the bot to their
   customer-facing WhatsApp groups; bot listens, never replies.
3. **Mechanical-turk operation** — Ricardo personally generates the analyses
   and weekly reports that the agent will eventually generate. Bot is a
   listener + report-delivery channel for week 1+.
4. **Ingest meeting transcripts** — Altis uses Read.AI / Fireflies; their
   meeting transcripts are a first-class data source for the lake.
5. **Configure data sources progressively** — as Poncho/Ruben mention sources
   in conversation, Ricardo wires connectors.
6. **Zero cost, open source, data portability on exit.**

The bot's per-channel `talkativeness` config + DM-nudge feature were
explicitly framed as **roadmap**, not Monday.

## Insight from the call

> "...va a estar silencioso en esos canales..." (the bot will be silent in
> those channels)

The bot is **silent everywhere** for week 1. This matches the current
deployed state (OpenClaw silent-mode plugin suppressing all outbound) and
the mechanical-turk positioning Ricardo pitched. No new silent-mode work
is required for Monday. What is required is the **operator tooling to
run the mechanical-turk phase**.

## Goals (Sprint 1 — by Sunday EOD)

1. **Verify** the altis tenant deployment is healthy enough to demo.
2. **Operator visibility**: Ricardo can list recent ledger activity per
   tenant from a CLI, so he can show Altis what's been ingested.
3. **SRT ingestion**: Ricardo can ingest a meeting transcript (.srt) into
   the altis tenant's data lake as `chat_received` entries with
   `modality=transcript`. The Altis call SRT itself is dogfood #1.

## Non-Goals (explicitly deferred)

- Per-tenant `WORMBASE_SILENT_MODE_<TENANT>` override (no need — bot is
  silent everywhere)
- Dashboard surface for managing tenants
- Per-surface silent flags
- DM-nudge mechanism (Altis roadmap, weeks 2-4)
- Talkativeness configuration UI
- Fireflies/Read.AI API polling (week 1 is SRT-file-upload only; API
  polling is week 2+ if Altis wants it)
- Self-service onboarding for design partners 4+
- A new `report_generated` ledger event kind — week 1 reports go through
  the existing `record_decision` PEVR primitive with
  `category="weekly_report"`; revisit if the shape needs evolution

## Architecture

Three parallel tracks, each landing as its own commit:

### Track A — Pre-flight verification (read-only)

Confirm the altis-tenant deployment is in a state Ricardo can demo:

- Silent-mode plugin firing (test outbound suppressed; `reply_suppressed`
  ledger entry written)
- `chat_received` emits via the new openclaw 2026.5.6+ `web-inbound` log
  path
- Per-tenant data isolation (altis entries tagged with
  `7f032a92-7036-5126-a957-8d2607126169`)
- `/healthz` (voice-agent) and `/api/v1/health` (worm-core) report
  `silent_mode: true`
- Shadow-throttle status: can the bot still receive inbound?

Output: status report + any blockers Ricardo must fix manually before
Monday.

### Track C — `wormbase-ledger-recent` CLI

New file: `apps/worm-core/src/wormbase_core/scripts/ledger_recent.py`
New entry point in `apps/worm-core/pyproject.toml`.

```
$ uv run wormbase-ledger-recent --tenant altis --limit 50
seq   ts                  kind            tool                    summary
1234  2026-05-25 09:01    propose         emit_chat_received      whatsapp inbound from +52181... ("hello team")
1235  2026-05-25 09:01    execute         channel_adapter.emit_chat_received  (200 chars)
...
```

Flags:
- `--tenant <slug>` (required) — resolves slug → company_id via `uuid5`
- `--limit N` (default 50)
- `--kind <kind>[,<kind>...]` (optional filter)

### Track D — `wormbase-ingest-transcript` CLI

New file: `apps/worm-core/src/wormbase_core/scripts/ingest_transcript.py`
New entry point in `apps/worm-core/pyproject.toml`.

```
$ uv run wormbase-ingest-transcript \
    --tenant altis \
    --meeting-id altis-wormbase-kickoff-prep \
    --srt /path/to/Altis-Wormbase-72b96c65-7eaf.srt \
    --speakers "Ricardo Alanís,Poncho Garciga,Ruben Madiedo"
ingested 135 turns, range 2026-05-22 23:00:00 .. 23:10:35
ledger seq range 4567..4836
session_id: meeting-altis-wormbase-kickoff-prep
```

Behavior:
- Parse SRT into per-cue (speaker, text, ts) tuples
- Group consecutive cues by speaker into a single `chat_received` turn
  (matches how the agent treats spoken turns)
- Map each turn to a `chat_received` ledger entry with payload:
  - `modality="transcript"`
  - `source_meeting_id=<--meeting-id>`
  - `caller_id=<speaker name>`
  - `text=<turn text>`
  - `platform="meeting"` (synthetic platform string)
- One synthetic session_id per meeting (`meeting-<meeting-id>`)

## Track B — WhatsApp group provisioning (manual, user)

NOT a subagent task. User does Monday morning before kickoff:

1. Create new WhatsApp group: "WormBase × Altis (Kickoff)" — add Poncho,
   Ruben, and the WormBase bot.
2. Capture the group JID from OpenClaw logs (or
   `make openclaw-logs | grep <name>`).
3. Add JID to `WHATSAPP_GROUP_ALLOW_FROM_ALTIS` in
   `.env` / docker-compose env.
4. Restart channel-adapter: `make adapter-restart`.
5. Send a test message; confirm `chat_received` lands in the altis
   ledger (verify via Track C CLI: `wormbase-ledger-recent --tenant altis`).

The bot will **not respond** — that's by design. The mechanical-turk
phase means Ricardo personally reads + responds (as Ricardo, not as
bot) for week 1.

## Success criteria

### Monday (kickoff)

- Bot in the internal WhatsApp group; silent; ingesting.
- Ricardo can run `wormbase-ledger-recent --tenant altis` and show
  Altis what's been ingested.
- The Altis-Wormbase call transcript is already ingested as a
  `chat_received` series tagged `modality=transcript`. Ricardo demos
  this as proof the listener works.

### End of Week 1 (2026-05-30)

- At least one Altis client channel added; bot listening; chat_received
  entries flowing.
- First weekly report delivered to Altis (via `record_decision` with
  `category="weekly_report"`).
- Friction log updated in `docs/known_issues.md`.

## Rollout

Each track ships as its own commit on `main`. No worktree (time pressure;
each commit is independently revertable). Sprint 2 (week 1) is operational
and driven by what Altis actually asks for — no new code planned upfront.

Sprint 3 (weeks 2-4) is the deferred roadmap (per-tenant flag, dashboard
surface, possible per-surface flags). Re-evaluate after Sprint 2 reveals
the real demand.
