# OpenClaw → Hermes Agent: channel-platform gateway migration

**Status:** **DEFERRED — H1 spike returned empirical NO-GO 2026-04-27.** See `docs/superpowers/notes/2026-04-27-hermes-h1-spike.md` for the full GO/NO-GO data and recommendation. The remainder of this document remains as the research record + a future revisit anchor.
**Date:** 2026-04-27 (research) → 2026-04-27 (NO-GO)
**Author:** research subagent (parent: WormBase orchestrator) → finished by parent after H1 spike
**Reads:** `Projects/wormbase/CLAUDE.md` §3, `2026-04-26-wormbase-product-arc.md` Step 1, `2026-04-26-production-dashboard-and-identity.md` §3, `apps/channel-adapter/`, `packages/channel-adapters/`, `infra/openclaw/`, **`docs/superpowers/notes/2026-04-27-hermes-h1-spike.md` (the deciding empirical data)**

This spec evaluates swapping the OpenClaw gateway for **NousResearch Hermes Agent** as
WormBase's channel-platform layer. After H1 spike: NO-GO. The migration is deferred.
OpenClaw remains the gateway. **Future revisit triggers:** Hermes ships an `inbound_message`
file-based hook event upstream, OR WormBase's needs evolve away from passive lurker capture.

> **TL;DR for picking this back up later:** Hermes v0.11.0's file-based hook system fires
> only on agent-engagement events (mention / DM / target channel). WormBase's lurker mines
> every message in connected channels regardless of bot-engagement. Architectural mismatch.
> See note §3 for the empirical evidence (5 sim-harness messages → 0 hook firings, even
> with `GATEWAY_ALLOW_ALL_USERS=true`).

---

## §0. Identifying the right "Hermes"

The user's prior memory note `feedback_no_claude_max.md` mentions `hermes_local + MiniMax`
for Paperclip orchestration agents. **That note is about a Paperclip LLM-runtime
adapter (the NousResearch Hermes-3 / Nomos model family), not a chat-platform
gateway.** It is unrelated to this migration.

The "Hermes agent" intended for the OpenClaw replacement is:

> **NousResearch / hermes-agent** — open-source autonomous AI agent + multi-platform
> messaging gateway, MIT-licensed, written in Python.  
> Repo: <https://github.com/NousResearch/hermes-agent>  
> Docs: <https://hermes-agent.nousresearch.com/docs/>  
> Latest: v0.11.0, released 2026-04-23.

This is the same project ecosystem as the LLM-runtime "Hermes" — Nous Research ships
both — but the **gateway** is a separate component (`hermes claw migrate` is a
first-class command; the OpenClaw migration path is on the docs index). It is
explicitly positioned as an OpenClaw replacement on its own Railway deploy
template page ("Open Source, OpenClaw Alternative on Railway").

Confidence: **high.** No second plausible candidate surfaced in
chat-gateway-replacement search context. Evidence:

- Native `hermes claw migrate` command targeting OpenClaw config files
- A community migration tool repo (`0xNyk/openclaw-to-hermes`)
- Multiple comparison articles ("Hermes Agent vs OpenClaw")
- Twitter/X discussion of production migrations
- Railway deploy template positioning Hermes as the OpenClaw alternative

**RESOLVED 2026-04-27:** the user confirmed Hermes = NousResearch/hermes-agent.
Q1 closed.

**Migration timing — RESOLVED 2026-04-27:** the user directed migration **NOW**,
overriding the research agent's "post-demo" recommendation. Risk acknowledged:
the Phase 0 spike (H1) is the GO/NO-GO gate. wire-replay (Block C C5) is
gateway-agnostic and remains the deterministic demo backstop even mid-cutover.
If H1 fails, revert to OpenClaw with no code lost. See §5 Phase 0 + §7 Q5.

---

## §1. Why migrate

### Concrete OpenClaw pain points present in this repo today

These are grep-findable in current code — not speculation:

1. **The bonjour mDNS crash.** `infra/docker-compose.yml:73` carries a permanent
   `NODE_OPTIONS: "--unhandled-rejections=none"` workaround for OpenClaw's bonjour
   plugin throwing `CIAO PROBING CANCELLED` on container networks that can't run
   mDNS. We mask Node-level unhandled rejections globally to keep the gateway
   alive — a known smell.
2. **Dual-app architecture for capture determinism.** Because OpenClaw's single
   SocketMode connection load-balances events with any second app, we ship a
   *separate* "WormBase Observer" Slack app (`apps/worm-core` `SLACK_*_OBSERVER_*`
   env vars) plus the main bot, just to get deterministic 100% event capture.
   This is institutional evidence that OpenClaw's event model is unreliable for
   our ingest path.
3. **Path 3 / log-file-tail capture.** The channel-adapter's `openclaw_log_tail.py`
   tails OpenClaw's daily `openclaw-YYYY-MM-DD.log` for `slack: allow channel <CID>`
   lines, then re-fetches the message via Slack's Web API. This is a fragile
   coupling to OpenClaw's log-line text format — any upstream rewording breaks
   us. The fallback layer (regex on a free-form log line) is itself a leak.
4. **File-share events sometimes dropped.** The PRD explicitly hypothesizes
   (`2026-04-26-production-dashboard-and-identity.md:519-524`): *"sim-harness
   uploads succeed but OpenClaw's JSONL log doesn't capture the `file_shared`
   event for them, OR the channel-adapter's log-tail filter drops the event."*
   This is an open bug at the OpenClaw seam.
5. **Bind-mounted entrypoint.** `infra/docker-compose.yml:62-65` mounts
   `entrypoint.sh` as a bind volume "to iterate on config without rebuilding the
   image" — a hackathon workaround that has not been reverted because OpenClaw's
   `config set` schema validator keeps rejecting partial provider blocks (see
   `entrypoint.sh:5-8`).
6. **License + image audit still open.** `infra/docker-compose.yml:8-11` notes a
   PRD E1 gate requiring an OpenClaw license audit before pinning the official
   image. Not yet done; we build from npm-install-at-image-build-time, which is
   itself a slow + flaky path (the Dockerfile carries 5 retries + 10-min
   timeouts to handle OrbStack VM npm fetch issues).

### What Hermes promises

From the NousResearch docs (links inline):

- **Single-process gateway, multiple platforms** — Telegram, Discord, Slack,
  WhatsApp, Signal, Email, Matrix, Mattermost, DingTalk, Feishu, WeCom,
  BlueBubbles, Home Assistant, plus CLI. 15+ platforms, one process.
- **Multi-workspace Slack natively.** Comma-separated `SLACK_BOT_TOKEN` env var,
  OR `~/.hermes/slack_tokens.json` mapping team-id → token bundle. One app-token
  shared, per-workspace bot tokens — *very close* to our `accounts.<companyId>`
  model.
- **Native OpenClaw migration tool** (`hermes claw migrate`).
- **Active maintenance** — v0.11.0 shipped 2026-04-23 (last week), ~8.7k stars,
  142 contributors. Higher activity than OpenClaw at this writing.
- **Python-native** — same language as `apps/channel-adapter/` and worm-core, so
  tighter possible integration if we ever choose to embed rather than sidecar.
- **JSONL command logs by default** at `~/.hermes/logs/command_usage.jsonl`,
  which is the *correct* event shape for our existing log-tail consumer pattern
  (though see §4 for the wire-format gap).

### Honest counterweight

Hermes is not a drop-in equivalent for everything OpenClaw does. Specifics in §2.

---

## §2. Side-by-side comparison

| Axis | OpenClaw (current) | Hermes Agent (candidate) |
|---|---|---|
| **License** | MIT | MIT |
| **Language / runtime** | Node.js (24-alpine container) | Python |
| **Latest release** | (npm `latest` at image build) | v0.11.0 (2026-04-23) |
| **Platform coverage claim** | "23+ channels" (npm page); 50+ in CLAUDE.md framing | 15+ platforms documented; Slack, Discord, Teams, WhatsApp, Signal, Matrix, Mattermost, DingTalk, Feishu, WeCom, BlueBubbles, Home Assistant, Telegram, Email, CLI |
| **Slack scopes** | Full set in `infra/openclaw/SLACK_MANIFEST.md` (28 scopes incl. `pins:*`, `reactions:*`, `mpim:*`, `assistant:write`) | 11 scopes documented (`chat:write`, `app_mentions:read`, `channels:history`, `channels:read`, `groups:history`, `im:history`, `im:read`, `im:write`, `users:read`, `files:read`, `files:write`); reactions + pins + mpim **not listed** |
| **Slack connection mode** | Socket mode | Socket mode (Slack Bolt SDK) |
| **Multi-tenancy (Slack)** | `channels.slack.accounts.<companyId>` config blocks; per-tenant `appToken`+`botToken` | Comma-separated `SLACK_BOT_TOKEN`, single `SLACK_APP_TOKEN`, OR JSON map at `~/.hermes/slack_tokens.json` (team-id → token bundle) |
| **Wire/event format consumed by external services** | (a) per-session JSONL files in `agents/main/sessions/`, (b) daily global log `openclaw-YYYY-MM-DD.log` with `slack: allow channel <CID>` lines | **No external event-emit path documented.** Hooks are in-process Python (`pre_gateway_dispatch`, `post_llm_call`) or shell-subprocess. Webhooks are *receive-only* from external services into Hermes. JSONL `command_usage.jsonl` exists but is command-only, not message-stream |
| **DM / channel / file_upload / reactions** | All four | DM ✓, channel ✓, file_upload ✓ (scopes only — API version not documented), reactions: **not mentioned in Slack adapter docs** |
| **Outbound rate-limit handling** | (delegated to OpenClaw internal) | Not documented |
| **OAuth grant storage** | Env-var-bound `appToken` / `botToken` per tenant | `~/.hermes/.env` + `~/.hermes/auth.json` + `~/.hermes/slack_tokens.json` |
| **Deployment shape** | Single Node container, port 18789, persistent state in `openclaw-state` volume | Single Python long-running process; Daytona/Modal/SSH/local/Docker all documented; serverless-friendly ("hibernate when idle") |
| **Active maintenance** | OpenClaw upstream still active (npm `@latest` works) | Higher: 8.7k stars, 142 contributors, v0.11.0 last week |
| **OpenClaw migration tool** | n/a | `hermes claw migrate` first-class, plus community `0xNyk/openclaw-to-hermes` |
| **Operational complexity** | Bonjour-crash workaround + dual-app for capture + log-tail regex | Cleaner agent surface; **but no documented event-stream out** |
| **Cost** | Open source / self-host | Open source / self-host |

### The showstopper to flag clearly

**Hermes does not document an external event-emit / wire-format path** equivalent
to OpenClaw's session JSONL or daily global log file.

The current channel-adapter's entire purpose is to be a **passive consumer** of
OpenClaw's wire output — it tails files, normalizes, and writes ledger entries.
The PRD §1 commitment is *"channel-adapter is the only writer of flow-driven
ledger entries."* That contract presumes the gateway emits events the adapter
can subscribe to without being embedded in the gateway's process.

Hermes's hook model is **in-process Python** — a hook handler runs *inside* the
Hermes process. To get equivalent OpenClaw-style externality, we need one of:

- **(A)** Write a shell-hook that POSTs to a local channel-adapter HTTP endpoint
  on every `pre_gateway_dispatch` (and a parallel hook on the outbound side).
  Channel-adapter becomes an HTTP server. **Cleaner than log-tail.**
- **(B)** Write a gateway-side Python plugin that emits JSONL to a tail-friendly
  file Hermes-side, and keep the existing tail-consumer pattern. **Shape-similar
  to OpenClaw, but we own the JSONL writer.**
- **(C)** Embed the channel-adapter as a Hermes plugin and drop the
  process-separation entirely. **Tightest, hardest to roll back, breaks the
  current "gateway as separate process" architectural commitment.**

§5 commits to (A) as the default with (B) as a fallback if hook latency or
delivery semantics surprise us.

---

## §3. What stays the same

The migration is a **swap of the gateway implementation**, not the architecture.
Per CLAUDE.md §3, the abstraction wall is the `ChannelAdapter` Protocol in
`packages/channel-adapters/src/wormbase_channel_adapters/base.py`. Everything
above that wall is unaffected:

- `ChannelAdapter` Protocol contract (Block B B5)
- `InfraEvent` / `OutMessage` / `MessageRef` / `ChannelRef` types
- `SlackChannelAdapter` (B6) — the underlying Slack Web API calls remain via
  `slack_sdk.AsyncWebClient`; Hermes uses the same SDK upstream, so we can keep
  our adapter unchanged for outbound `chat.postMessage` / `files.upload` / etc.
- The PEVR ledger write primitive in `apps/channel-adapter/service.py`
  (`GlobalLogCapture._emit_chat_received`, `_emit_file_received`)
- Wire-record / wire-replay tooling in
  `apps/channel-adapter/src/wormbase_channel_adapter/wire_replay.py` — see §4
- The dashboard, worm-core's reactivity pipeline, the ledger schema, and every
  flow downstream of `chat_received` / `file_received` / `chat_sent`

The 7-beat install-arc scenario (`apps/sim-harness/scenarios/install-arc-7beat.yml`)
drives Slack via slack-sdk **directly** (not via OpenClaw); it survives the swap
unchanged.

The Slack manifest in `infra/openclaw/SLACK_MANIFEST.md` is a Slack-app artifact
unrelated to the gateway choice — it survives the swap (with a possible tweak,
see §3.b below).

---

## §4. What changes

### 4.a Files in `apps/channel-adapter/` and `infra/`

| File | Disposition |
|---|---|
| `infra/openclaw/Dockerfile` | Replaced by `infra/hermes/Dockerfile` (Python `pip install hermes-agent` or `uv pip install`) |
| `infra/openclaw/entrypoint.sh` | Replaced by `infra/hermes/entrypoint.sh` (renders `~/.hermes/config.yaml` + `.env` from container env, similar pattern) |
| `infra/openclaw/SLACK_MANIFEST.md` | Update in place with reduced-scope set Hermes documents (drop `pins:*`, `mpim:*`, `assistant:write`, `commands` if unused). **Open question:** does Hermes Slack actually need `reactions:read/write`? If yes, keep it — if no, drop it. See §6. |
| `infra/openclaw-config/config.json5` | Replaced by `infra/hermes-config/config.yaml` (rendered by entrypoint) |
| `infra/docker-compose.yml` `openclaw:` service | Replaced by `hermes:` service block. Volume `openclaw-state` → `hermes-state`. Port 18789 may change (Hermes default not yet confirmed; see §6). Bonjour `NODE_OPTIONS` workaround is gone — no Node, no bonjour. Dual-mount entrypoint pattern preserved for hackathon iteration speed. |
| `apps/channel-adapter/src/wormbase_channel_adapter/openclaw_log_tail.py` | **Retired.** Replaced by `hermes_event_consumer.py` — an aiohttp HTTP server (or websocket consumer) that receives event POSTs from a Hermes shell-hook, normalizes them through the same `GlobalLogCapture` path, and produces `InfraEvent`s. Same downstream shape, different inbound transport. |
| `apps/channel-adapter/src/wormbase_channel_adapter/service.py` | Edited: replace `OpenClawLogTailer` instantiation with `HermesEventConsumer`. The bot-id self-echo guard, dedup state, file-fan-out, and ledger-write paths are unchanged. The `WORMBASE_DISABLE_LURKER_SOCKET` flag becomes architecturally unnecessary IF Hermes's single-process multi-workspace model gives us the deterministic capture we needed dual-app for; see §6 risk. |
| `apps/channel-adapter/tests/test_openclaw_log_tail.py` | Replaced by `test_hermes_event_consumer.py`. Same fixture pattern (synthesized inbound events), different transport (HTTP POST instead of file append). |
| `apps/channel-adapter/tests/test_parser.py` + `test_writer.py` | Survive: they test the JSONL → `ParsedEvent` mapping, which is the OpenClaw session-JSONL path. **If we keep that path** for backward compat during the rollback window (see §5 Phase 2), the tests stay literal. **If we delete the session-JSONL path entirely**, these tests are deleted alongside it. Decision deferred to Phase 4. |
| `apps/channel-adapter/tests/conftest.py` | Edited: the "golden session JSONL captured from a real OpenClaw run" fixture is renamed and possibly replaced with a Hermes-emitted equivalent. |
| `apps/channel-adapter/tests/test_writer.py:129` | `payload.attribution["source"] == "openclaw"` → `"hermes"`. One-line edit. |

### 4.b Hermes plugin / hook (new, lives in this repo)

A small Hermes shell-hook in `infra/hermes/hooks/wire_tap.sh` (or the Python
equivalent in `infra/hermes/hooks/wire_tap/handler.py`) that fires on
`pre_gateway_dispatch` (inbound) and `post_llm_call` (outbound), and POSTs the
event payload to the channel-adapter at `http://channel-adapter:8911/events`.

Payload shape: a small JSON envelope wrapping Hermes's `MessageEvent` plus
WormBase tenant routing fields (`company_id` resolved by Hermes-side env or by
team-id-to-tenant mapping). The exact schema is finalized during Phase 1.

### 4.c Dashboard / worm-core touchpoints

Worm-core has direct Slack-token env vars (`SLACK_*_OBSERVER_*` and
`SLACK_*_BASEWORM`) for the lurker. Whether to retire the Observer app entirely
depends on whether Hermes's deterministic capture eliminates the need for it —
see §6 risk.

The dashboard's `/channels` tab references "OpenClaw" prose in some
copy/comments (grep `apps/dashboard` for "openclaw" before merge); these become
"Hermes" or "the gateway" as part of the migration commit.

### 4.d Setup docs

`docs/setup/slack-oauth.md` (current, Slack-only) becomes
`docs/setup/connect-channel.md` covering Slack + Discord + Teams + WhatsApp +
Signal install steps under a unified `@connect <platform>` framing — already
the language CLAUDE.md uses, but under-realized in current docs because
OpenClaw's setup ergonomics encouraged Slack-first. Hermes's per-platform
adapter pages (`/docs/user-guide/messaging/<platform>/`) are linked.

### 4.e Makefile

`make openclaw-build / openclaw-restart / openclaw-logs / openclaw-status`
become `make hermes-build / hermes-restart / hermes-logs / hermes-status`.
Mechanically identical pattern.

---

## §5. Compatibility surface

### 5.a wire-record / wire-replay tooling (Block C C4 + C5)

**Survives the migration unchanged.** Verified by reading
`apps/channel-adapter/src/wormbase_channel_adapter/wire_replay.py`:

- It consumes JSONL records produced by `wormbase demo wire-record`
- The record format is `channel_adapter.emit_chat_received` /
  `channel_adapter.emit_chat_sent` / `channel_adapter.emit_file_received`
  ledger-execute payloads — **our format, not OpenClaw's**
- The record is captured **after** the gateway-side normalization, so any
  upstream gateway swap is invisible to wire-replay

This is the architectural payoff of the `ChannelAdapter` Protocol. The
deterministic-replay backstop survives because it sits above the abstraction
wall, not below it.

### 5.b 7-beat install-arc scenario

`apps/sim-harness/scenarios/install-arc-7beat.yml` and the scenario engine in
`apps/sim-harness/src/wormbase_sim_harness/engine.py` drive Slack via
`slack_sdk.AsyncWebClient` directly (with bot tokens loaded from env). They do
NOT call OpenClaw. They survive the swap unchanged.

### 5.c Tests referencing OpenClaw directly

From `grep -l openclaw`:

- `apps/channel-adapter/tests/test_openclaw_log_tail.py` — replace
- `apps/channel-adapter/tests/test_parser.py` — survives if session-JSONL
  parser path is kept; otherwise delete
- `apps/channel-adapter/tests/test_writer.py:129` — one-line attribution string
  edit
- `apps/channel-adapter/tests/test_service_global_log_capture.py` — rename to
  `test_service_event_capture.py`; the capture object's contract is unchanged,
  the input shape changes
- `apps/channel-adapter/tests/conftest.py` — fixture rename + payload reshape

No tests outside `apps/channel-adapter/tests/` reference OpenClaw directly. The
demo gates (`tests/demo/test_F3_slack_oauth_under_15s.py`,
`tests/demo/test_Q2_worm_reply_under_5s.py`) test SLAs at the Slack-app level,
not the gateway level. They survive.

### 5.d N2 placeholder gate

`tests/demo/test_N2_no_placeholders_on_screen.py` enforces no demo-seam strings
on screen. Adding "hermes" to the allowlist is a one-line change; removing
"openclaw" mentions where they're stale prose is part of the migration
commit's normal cleanup pass.

---

## §6. Phased migration plan

This is a sketch — the parent will turn it into a Block H plan with concrete
task LOC + acceptance gates per task.

### Phase 0 — Spike (≤ 1 day wall-clock)

**Goal:** prove Hermes can post in our real Slack workspace + produce one
end-to-end captured event into the ledger via a temporary in-process hook.

- Stand up `infra/hermes/` Dockerfile + entrypoint that renders a minimal
  `~/.hermes/config.yaml` for one tenant only (`baseworm`), Slack-only
- Run alongside the existing `openclaw` service on a different port
- Manually exercise: post in `#wormbase-test`, confirm a `chat_received`
  ledger entry appears via a temporary Hermes Python plugin that calls
  `wormbase-ledger.write` directly
- Decision gate: GO if Hermes's `pre_gateway_dispatch` hook fires reliably
  for every Slack message in our workspace. NO-GO if any message is dropped
  or order is non-deterministic.

### Phase 1 — `HermesChannelAdapter` (the long pole)

**Goal:** an alternative `ChannelAdapter` Protocol implementation in
`packages/channel-adapters/src/wormbase_channel_adapters/hermes_slack.py`
that runs against Hermes instead of OpenClaw.

The key insight: the **adapter's role hasn't changed.** It still calls
`slack_sdk.AsyncWebClient` for outbound + workspace member listing. The
*difference* is in `listen()` — yielding `InfraEvent`s. Two valid
implementations:

- **Option A** (default): the Hermes shell-hook POSTs to a local HTTP
  endpoint exposed by the channel-adapter; `listen()` is an async-iterator
  over events received on that HTTP endpoint
- **Option B** (fallback): a Hermes plugin tails JSONL written by Hermes-side
  hook to a shared volume, mirroring the OpenClaw pattern

Tests: existing protocol-conformance tests (`tests/test_*` for
`SlackChannelAdapter`) get parametrized to run against both adapters.

### Phase 2 — Docker service swap with rollback flag

**Goal:** replace the `openclaw` service with `hermes` in `docker-compose.yml`,
gated behind `WORMBASE_GATEWAY=hermes|openclaw` env var. Default `hermes`
during the cutover window; rollback is one env var + `make restart`.

- Both gateway services build but only one starts (compose profiles)
- Channel-adapter reads `WORMBASE_GATEWAY` and switches between
  `OpenClawLogTailer` (legacy, still in repo) and `HermesEventConsumer` (new)
- The legacy OpenClaw path stays in-tree until Phase 4

### Phase 3 — Live end-to-end test

**Goal:** run the existing 7-beat install-arc scenario against the Hermes
gateway and verify every demo gate passes.

- `make demo` end-to-end with `WORMBASE_GATEWAY=hermes`
- Hash-stability check: the headline ledger rows should be identical between
  an OpenClaw run and a Hermes run of the same scenario (modulo the gateway
  attribution string in `payload.attribution["source"]`)
- Capture a wire-record from this run; replay it; verify `make wire-replay`
  produces equivalent ledger projections

### Phase 4 — Retire OpenClaw

**Goal:** remove OpenClaw from the repo entirely.

- Delete `infra/openclaw/` and `infra/openclaw-config/`
- Delete the `openclaw` service block in `docker-compose.yml`
- Delete `WORMBASE_DISABLE_LURKER_SOCKET` env var (and the dual-app pattern
  in worm-core) **iff** Phase 1 confirmed Hermes's single-process capture is
  deterministic. Otherwise keep it as a legacy fallback toggle.
- Delete `OpenClawLogTailer` and `openclaw_log_tail.py` + tests
- Delete OpenClaw mentions in `Makefile` (renamed to `hermes-*` in Phase 2;
  remaining cruft drops)
- Update `docs/superpowers/specs/2026-04-26-wormbase-product-arc.md` Step 1
  prose ("OpenClaw" → "the gateway" or "Hermes")
- Update `docs/superpowers/specs/2026-04-26-production-dashboard-and-identity.md`
  §3 channel-abstraction prose
- Update `Projects/wormbase/CLAUDE.md` §3 prose: "Channel layer: OpenClaw +
  Channel Ledger Adapter" → "Channel layer: Hermes Agent gateway + Channel
  Ledger Adapter"
- Burn-down note in `docs/superpowers/notes/`

---

## §7. Risks + open questions

These are the things the parent should resolve before dispatching Block H.

### Risks

1. **No external event-emit path is documented for Hermes.** §2's showstopper.
   We design around it via shell-hook + HTTP, but this is *our* engineering, not
   a documented Hermes integration surface. If Hermes upstream changes its
   hook API, we break.
2. **Reaction events absent from Slack adapter docs.** OpenClaw exposes
   `reaction_added` / `reaction_removed`. Hermes's Slack docs don't mention
   reactions. If our gold-conversation pipeline depends on reactions (it does —
   `InfraEvent.source` includes `"reaction_added"`), we may need to add reaction
   support to our Hermes plugin layer ourselves.
3. **MPIM / pins not in Hermes's documented Slack scopes.** Group-DM and
   pinning surfaces may quietly degrade.
4. **Multi-tenant Slack model is shape-different.** Hermes uses
   comma-separated bot tokens + a single app token; OpenClaw uses
   `accounts.<companyId>` blocks. Both work for many tenants, but the
   tenant-id ↔ team-id mapping moves from gateway-config to channel-adapter.
   We need a `team_id` ↔ `company_id` resolver in the channel-adapter.
5. **Phase 0 spike could fail.** If `pre_gateway_dispatch` doesn't fire on
   *every* inbound message — e.g. if Hermes routes through some auth/pairing
   gate that drops events without hooking them — the migration is dead at
   Phase 0. The dual-app workaround we have today is institutional evidence
   that the equivalent OpenClaw guarantee is fragile; Hermes's hook may have
   the same problem in different form.
6. **Outbound rate-limit handling unknown.** OpenClaw handles Slack rate
   limits internally. Hermes's docs don't describe this. Worst case, we hit
   `slack_sdk.errors.SlackApiError(429)` more often and add backoff to
   `SlackChannelAdapter.send()` ourselves — modest.
7. **Hermes's persistent memory + skills systems overlap with worm-core's
   own memory.** We don't want Hermes silently writing its own memory file at
   `~/.hermes/MEMORY.md` based on workspace chatter — that is *exactly* the
   kind of state we want under our ledger, not under Hermes. Phase 0 must
   verify we can disable Hermes's memory system entirely (or scope it to a
   throwaway volume).

### Open questions for the parent / user

- **Q1.** Did the user actually mean NousResearch hermes-agent, or a different
  "Hermes"? Confidence is high but not 100%.
- **Q2.** Is the loss of OpenClaw's session-JSONL format acceptable? It carries
  rich Slack metadata (sender_id, conversation_label, attribution) that we use
  in `apps/channel-adapter/src/wormbase_channel_adapter/parser.py`. The
  shell-hook envelope must reconstitute equivalent fields.
- **Q3.** Do we want to keep the dual-capture path (session-JSONL **+**
  global-log-tail) as two independent paths under Hermes for capture-determinism
  defense in depth, or simplify to a single shell-hook path? Default
  recommendation: **single path**, since the dual-path was a workaround for
  OpenClaw's flakiness, not an architectural commitment.
- **Q4.** Does the user want to retire the WormBase-Observer Slack app
  alongside this migration (one fewer Slack app to manage), or keep it as
  defense-in-depth?
- **Q5. RESOLVED 2026-04-27 (twice):** initial call: migrate NOW (vs research
  agent's "post-demo" recommendation). H1 spike then returned empirical NO-GO
  (Hermes hooks are responder-shaped; 0/5 messages captured). Final call:
  **migration deferred indefinitely.** Stay on OpenClaw. Revisit if Hermes
  ships an `inbound_message` hook upstream OR if WormBase's needs evolve away
  from passive lurker capture. See `docs/superpowers/notes/2026-04-27-hermes-h1-spike.md`.
- **Q6.** Hermes's docs mention `hermes claw migrate` will fail on Slack
  tokens (they don't auto-extract from OpenClaw config). Are we OK doing the
  one-shot manual token copy?
- **Q7.** Hermes ships its own LLM-routing layer (any-OpenAI-compatible
  endpoint). We currently route LLM calls through worm-core, not the gateway.
  Do we want Hermes to be a *dumb gateway* (no LLM routing, no agent
  behavior — just wire normalization), or do we want to absorb our LLM
  routing into Hermes's surface? Recommendation: **dumb gateway**, to keep
  the principle "channel-adapter is the only writer" intact.

---

## §8. Documentation deltas (DO NOT modify in this commit — flagged for parent)

If migration proceeds, these durable docs need parent-driven updates:

- **`Projects/wormbase/CLAUDE.md` §3** — "Channel layer: OpenClaw + Channel
  Ledger Adapter" → "Channel layer: Hermes Agent gateway + Channel Ledger
  Adapter (the latter being the only wire-protocol code we maintain)."
- **`docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`:38** —
  "Customer connects a chat platform via the OpenClaw `@connect <platform>`
  UX..." → "...via the Hermes Agent `@connect <platform>` UX..."
- **`docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`:240, :246** —
  table entries.
- **`docs/superpowers/specs/2026-04-26-production-dashboard-and-identity.md`
  §3** — same scoped substitution.
- **`apps/channel-adapter/README.md`** — full rewrite of the "what this
  service consumes" section.
- **`docs/superpowers/notes/2026-04-22-openclaw-license.md`** — supersede with
  a Hermes equivalent (license is the same MIT, but we should re-do the audit).

These are NOT modified by this research subagent. Parent integrates.

---

## §9. Out of scope

- LLM-routing changes (worm-core stays the LLM-router)
- Voice agent (`docs/superpowers/specs/2026-04-26-voice-agent-design.md`) —
  separate workstream, not channel-platform-gateway scoped
- Connector layer (data sources) — fully decoupled from this migration
- Dashboard production rewrite (Block W7) — independent
- Hermes's persistent-memory feature — explicitly disabled under WormBase
  (state belongs in the ledger, not in Hermes)

---

## §10. Block H workstream sketch (parent expands into formal plan)

Six tasks, ~30 min wall-clock each per the agentic_datasci CLAUDE.md
calibration (100-175 LOC/min sustained, plan-quality is the rate limiter):

| ID | Title | One-line scope |
|---|---|---|
| **H1** | Hermes spike + GO/NO-GO gate | Stand up `infra/hermes/` + minimal config.yaml; verify `pre_gateway_dispatch` fires for every inbound Slack message in `baseworm`; produce a 1-page GO/NO-GO note in `docs/superpowers/notes/`. |
| **H2** | `HermesEventConsumer` + shell-hook | New `apps/channel-adapter/src/wormbase_channel_adapter/hermes_event_consumer.py` (aiohttp server) + `infra/hermes/hooks/wire_tap/handler.py` (Python hook posting to it). Tests for both. |
| **H3** | `HermesChannelAdapter` Protocol implementation | New `packages/channel-adapters/src/wormbase_channel_adapters/hermes_slack.py` implementing `ChannelAdapter`. Reuses `SlackChannelAdapter`'s outbound code via composition. Protocol-conformance tests pass. |
| **H4** | docker-compose swap with `WORMBASE_GATEWAY` toggle | `infra/hermes/Dockerfile` + entrypoint; `docker-compose.yml` `hermes:` service; channel-adapter env-toggles consumer. Both paths work; `make demo` green under either. |
| **H5** | Live 7-beat run + hash-stability gate | Run `make demo` with `WORMBASE_GATEWAY=hermes`; capture wire-record; assert headline rows match the OpenClaw-run baseline modulo attribution string; replay via `make wire-replay`. |
| **H6** | Retire OpenClaw + docs sweep | Delete `infra/openclaw/`, `openclaw_log_tail.py`, related tests. Update `CLAUDE.md` §3, product-arc Step 1, PRD §3. Drop `WORMBASE_DISABLE_LURKER_SOCKET` if H1 confirmed deterministic capture. Final commit. |

Optional H7 if any §7 risk fires: **reactions + mpim + pins parity gap** —
add a Hermes-side plugin that subscribes to the missing Slack event types and
forwards them through the same shell-hook envelope.

Estimated total wall-clock with one parallel agent on H2/H3 and a serial
H1 → H4 → H5 → H6: **~3 hours** under current calibration. With the spike
result driving the rest, it's a single afternoon's work for the orchestrator.

---

## Sources

- NousResearch/hermes-agent (GitHub): <https://github.com/NousResearch/hermes-agent>
- Hermes Agent docs (homepage): <https://hermes-agent.nousresearch.com/docs/>
- Hermes Agent — Multi-Platform Gateway: <https://hermes-agent.ai/features/multi-platform>
- Hermes Agent — Messaging: <https://hermes-agent.nousresearch.com/docs/user-guide/messaging>
- Hermes Agent — Slack adapter: <https://hermes-agent.nousresearch.com/docs/user-guide/messaging/slack/>
- Hermes Agent — Webhooks: <https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks/>
- Hermes Agent — Hooks: <https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks>
- Hermes Agent — Configuration: <https://hermes-agent.nousresearch.com/docs/user-guide/configuration/>
- Hermes Agent — Migrate from OpenClaw: <https://hermes-agent.nousresearch.com/docs/guides/migrate-from-openclaw>
- Community migration tool (0xNyk): <https://github.com/0xNyk/openclaw-to-hermes>
- Comparison article (knightli): <https://www.knightli.com/en/2026/04/12/hermes-agent-intro-guide-vs-openclaw/>
- Railway deploy template: positions Hermes as "Open Source, OpenClaw Alternative on Railway"
