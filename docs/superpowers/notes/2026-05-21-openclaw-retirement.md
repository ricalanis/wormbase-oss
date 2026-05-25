# 2026-05-21 — OpenClaw retirement burn-down (Phase 4 of openclaw→hermes migration)

Branch: `feat/hermes-migration` (not merged to main yet — gated on live
Hermes verification per §6 Phase 3 of the migration spec).

Spec: `docs/superpowers/specs/2026-04-27-openclaw-to-hermes-migration.md`
§6 Phase 4. This note records *what was deleted, what was preserved,
and what was preserved-but-dead-coded* so a follow-up phase (or
rollback) doesn't have to re-derive the surface from `git log`.

## 1. What was deleted

### Files / directories (`git rm`)

- `infra/openclaw/Dockerfile`
- `infra/openclaw/entrypoint.sh`
- `infra/openclaw/SLACK_MANIFEST.md`
- `infra/openclaw/UPGRADE.md`
- `infra/openclaw/silent-mode-plugin/` (entire plugin, including
  `dist/index.js`, `openclaw.plugin.json`, `package.json`)
- `infra/openclaw-config/config.json5`
- `apps/channel-adapter/src/wormbase_channel_adapter/openclaw_log_tail.py`
- `apps/channel-adapter/tests/test_openclaw_log_tail.py`

### Compose service blocks

- `infra/docker-compose.yml`: removed the `openclaw` service (lines
  ~57-184 of the pre-Phase-4 file) and the `channel-adapter-hermes-spike`
  scaffold (lines ~166-198). Also dropped the `openclaw-state` and
  `openclaw-tmp` named volumes.
- The `hermes` service is now un-profiled (was `profiles: [hermes]`
  during Phase 2). It is brought up by plain `make up`.

### Makefile

- Dropped `gateway-hermes`, `gateway-openclaw`, `gateway-status` targets
  (the Phase 2 cutover helpers).
- Simplified `up:` → `$(COMPOSE) up -d`, `down:` → `$(COMPOSE) down`.
  Profiles are no longer in play.

### Renamed / sed-substituted

- `infra/openclaw/WHATSAPP_PAIRING.md` → `infra/hermes/WHATSAPP_PAIRING.md`
  with `OpenClaw` → `Hermes` substitutions throughout. The pairing
  procedure is identical at the Baileys layer; only the surrounding
  container name changes.

## 2. What was preserved (intentionally)

These are *not* leftovers — they exist on purpose:

### Env-var surface

- `OPENCLAW_LOG_DIR` is still read by the channel-adapter's `cli.py`
  via the `--openclaw-log-dir` CLI option. The variable is now a no-op
  for the gateway-inbound path (Hermes doesn't write to it), but the
  WhatsApp **envelope watcher** still uses it to locate the OpenClaw
  daily-log file when the operator points the channel-adapter at an
  external OpenClaw container (e.g., during a hybrid cutover window or
  on an air-gapped deployment that hasn't completed migration).
- `OPENCLAW_SESSIONS_PATH` is still the default for `--sessions-path`.
  The session-JSONL tailer remains the canonical source for `chat_sent`
  ledger entries (the agent's own outbound replies), since Hermes' wire
  tap currently only fires on `agent:start` (inbound). When Hermes
  upstream adds an `agent:end` hook with outbound text, this path can be
  retired in a Phase 5.

### `WORMBASE_GATEWAY` env-var

Still honored in `cli.py` and `service.py`, but its **default is now
`"hermes"`** (was `"openclaw"` during Phase 2). The legacy
`"openclaw"` branch in `service.py` is dead-coded via `if False and …`
rather than deleted outright — see §3 below.

### Tenant pairing flow

The runbook at `infra/hermes/WHATSAPP_PAIRING.md` is verbatim the
OpenClaw procedure with the container name changed. Operators who
paired tenants on OpenClaw don't need to re-pair; the Baileys session
files (`auth_info_*.json`) are portable between gateways.

## 3. What was dead-coded (not deleted)

### `service.py` OpenClaw log-tailer branch

Lines ~840-952 of `apps/channel-adapter/src/wormbase_channel_adapter/service.py`
contain the platform-dispatch + admit-handler wiring that used to drive
the `GlobalLogCapture` (Slack) and `WhatsAppLogCapture` paths off the
OpenClawLogTailer's `<platform>: allow channel <id>` lines.

This block is guarded by `if False and openclaw_log_dir and slack_bot_token:`
— the `False` short-circuits the entire branch. The body is preserved
because:

1. **Rollback ergonomics.** A two-phase rollback (re-add the tailer +
   drop `if False`) is meaningfully simpler than reconstructing the
   dispatch table + LRU + adapter-loading-from-registry sequence from
   `git log`. The dispatch table in particular is non-trivial.
2. **Symmetry with envelope-watcher.** The envelope-watcher path
   continues to live in the same file under the active branch; deleting
   only the dead half would make the surviving structure less
   self-documenting.

The `log_tail_active = False` constant immediately below makes the
dedup gate (which would otherwise suppress Slack-shaped chat_received
events emitted by the session-JSONL parser) inert — so the session
JSONL path becomes the canonical Slack chat_received emitter under
Phase 4, alongside the Hermes wire-tap consumer.

### Gate-6 silent-mode plugin

The plugin (`infra/openclaw/silent-mode-plugin/`) is **deleted** — not
dead-coded — because Hermes' upstream config disables embedded-agent
auto-reply natively (via `agents.[name].respond_to_inbound: false`).
The plugin's two hooks (`before_agent_reply`, `message_sending`) have
no analogue in Hermes; the equivalent guarantee is enforced by the
gateway's own config, which is a stronger invariant than a per-tenant
plugin claim could provide.

Coverage of the silent-mode contract under Hermes is provided by:

- The `WORMBASE_SILENT_MODE` env-var flowing into `worm-core` and
  `voice-agent` exactly as before (gates 1-5 of the silent-mode design
  are unchanged).
- Hermes' agent disabled at the gateway level (gate 6 replacement).
- `apps/channel-adapter/tests/test_hermes_event_consumer.py` (16 tests)
  asserting the consumer never emits outbound — it only writes to the
  ledger.

## 4. What still works after Phase 4

- WhatsApp ingest via the envelope watcher (the path we hardened in
  the silent-mode-merge session, commit `7588fa2` and follow-ups). The
  watcher still listens to the OpenClaw daily log when one is mounted
  — operators running an *external* OpenClaw alongside Hermes during a
  hybrid window continue to get full WhatsApp inbound coverage.
- Session-JSONL tailing for `chat_sent` (bot outbound replies). The
  worm-core's HTTP API → Hermes outbound path emits `chat_sent`
  ledger entries via the writer; the JSONL tailer remains the fallback
  capture surface for agent-engaged sessions.
- Hermes wire-tap → `ChatReceivedEvent` via the HermesEventConsumer
  HTTP server (Phase 1 work, commit `7d2a0ab`).
- All 152 channel-adapter tests pass (the deleted
  `test_openclaw_log_tail.py` is the test for the deleted module; the
  remaining suite covers parser, writer, envelope watcher, Hermes
  consumer, wire replay, and gateway parity).

## 5. Known blockers (carried into Phase 5 / live verification)

1. **H1 NO-GO (spec §6 Phase 0 outcome, 2026-04-27):** Hermes v0.11.0's
   `agent:start` hook fires only on agent-engaged messages — not on
   *every* inbound. The channel-adapter's lurker contract requires
   ingest of every inbound regardless of agent engagement. Live
   verification (spec §6 Phase 3 — re-run the install-arc 7-beat
   scenario against a live Hermes and compare ledger hashes) is
   blocked until upstream Hermes ships a hook that fires on every
   inbound. The structural parity tests
   (`apps/channel-adapter/tests/test_gateway_parity.py`) cover the
   deterministic half of the gate.
2. **WhatsApp shadow throttle:** the test SIM
   (`+5218114822051`, tenant `altis`) is under a shadow throttle as of
   2026-05-21 from rapid admin-CLI outbound during gate-6 debugging.
   Re-pair on same SIM does **not** clear it (number-scoped, not
   session-scoped). Recovery: wait 1-24h or use a fresh SIM. See
   `docs/known_issues.md` for the full mechanism + recovery flow.

## 6. Merge gate

This branch does NOT merge to main until Phase 3 (live end-to-end
verification) clears. Until then `feat/hermes-migration` represents
the final-state shape; main keeps the OpenClaw setup operational for
day-to-day tenant work.
