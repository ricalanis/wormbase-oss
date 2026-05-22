# Changelog de sesiones

> Registro breve de progresos y cambios completados por sesión de trabajo con Claude Code.
> Para el registro formal de releases/shipments, ver `DELIVERY_LOG.md`.

## Cómo usar este archivo

- Una entrada por tarea/sesión significativa.
- Formato: `### YYYY-MM-DD — <título corto>` seguido de 1-3 bullets de qué cambió.
- No duplicar contenido de `DELIVERY_LOG.md`: aquí va el "qué hice esta sesión", allá el "qué shippeó la fase".
- Si la sesión generó lecciones, enlazar a la entrada correspondiente en `known_issues.md`.

---

### 2026-05-21 — Hermes migration Phase 4: OpenClaw retirement (branch `feat/hermes-migration`)

- Deleted: `infra/openclaw/{Dockerfile, entrypoint.sh, SLACK_MANIFEST.md, UPGRADE.md, silent-mode-plugin/}`, `infra/openclaw-config/config.json5`, `apps/channel-adapter/src/wormbase_channel_adapter/openclaw_log_tail.py`, `apps/channel-adapter/tests/test_openclaw_log_tail.py`. Compose service `openclaw` and `channel-adapter-hermes-spike` removed; volumes `openclaw-state`/`openclaw-tmp` dropped; `hermes` service un-profiled (now default-up).
- Renamed `infra/openclaw/WHATSAPP_PAIRING.md` → `infra/hermes/WHATSAPP_PAIRING.md` with OpenClaw→Hermes substitutions. Baileys session files remain portable between gateways; operators don't re-pair.
- Makefile: dropped Phase 2 `gateway-hermes`/`gateway-openclaw`/`gateway-status` selector targets; `up:` simplified to `$(COMPOSE) up -d`, `down:` to `$(COMPOSE) down`.
- `service.py` OpenClaw-log-tail dispatch block dead-coded behind `if False and …` (kept for rollback ergonomics — re-derive cost is non-trivial). `log_tail_active = False` constant disables the dedup gate, so session-JSONL parser becomes the canonical Slack `chat_received` emitter alongside Hermes wire-tap. `gateway_kind` default flipped `"openclaw"` → `"hermes"` in both `cli.py` and `service.py`.
- Preserved on purpose: `OPENCLAW_LOG_DIR` + `OPENCLAW_SESSIONS_PATH` env (still consumed by WhatsApp envelope watcher + session-JSONL tailer for `chat_sent`); `WORMBASE_GATEWAY` env (default `hermes`, `openclaw` branch dead but selectable).
- Gate 6 (silent-mode) plugin deleted outright: Hermes' upstream config disables embedded-agent reply natively (`agents.[name].respond_to_inbound: false`) — a stronger invariant than a per-tenant plugin claim.
- Tests: 152 pass, 1 skipped (live-Hermes integration, gated on H1 upstream resolution). Burn-down detail in `docs/superpowers/notes/2026-05-21-openclaw-retirement.md`.
- Merge gate: branch does NOT merge to main until Phase 3 live verification clears. H1 NO-GO (Hermes v0.11.0 hook only fires on agent-engaged inbound) + WhatsApp shadow throttle on test SIM both block live runs as of today.

### 2026-05-21 — Hermes migration Phase 1 (branch `feat/hermes-migration`)

- `apps/channel-adapter/src/wormbase_channel_adapter/hermes_event_consumer.py` (new, 332 lines): aiohttp HTTP server (POST `/hermes-spike` + GET `/healthz`) that receives wire-tap hook envelopes from NousResearch Hermes Agent and translates `agent:start` events into `ChatReceivedEvent`. Routes through the existing `LedgerWriter` so dedup + ledger PEVR cycle are unchanged. Synthesizes stable `(channel_id, message_id)` from `(session_id, ts, text)` SHA256 when the hook envelope is minimal; honors richer fields (`channel_id`, `message_ts`) when the hook is extended.
- Option A from the migration spec §2 — Hermes has no documented external event-emit path, so the hook posts via HTTP to channel-adapter. The same architectural shape we used to fix the openclaw 2026.5.6+ envelope-watcher (commit `7588fa2`): direct emission, no session-JSONL correlation. Migration design doc this implements: `docs/superpowers/specs/2026-04-27-openclaw-to-hermes-migration.md` §6 Phase 1.
- `apps/channel-adapter/src/wormbase_channel_adapter/service.py` gains `gateway_kind` parameter (default `"openclaw"`); when set to `"hermes"` starts the HermesEventConsumer alongside the OpenClaw log-tailer. Both can run simultaneously during a cutover — writer's `(channel_id, message_id)` dedup absorbs the overlap.
- `apps/channel-adapter/src/wormbase_channel_adapter/cli.py` reads `WORMBASE_GATEWAY` (default `openclaw`) + `WORMBASE_HERMES_CONSUMER_PORT` (default `18790`) from env.
- `apps/channel-adapter/tests/test_hermes_event_consumer.py` (new): 16 tests — happy path, richer-context upgrade, empty-text skip, session-event/unknown-event skip, malformed payloads (non-object, missing event_type, missing context fields), writer-failure 500, deterministic synthetic message_id, ISO8601 fallback to now(), translation-error raising. Full channel-adapter suite green: 155/155.
- Phase 0 spike scaffolding (`infra/hermes/Dockerfile` + entrypoint + `hooks/wire-tap/`) untouched — stays as the GO/NO-GO artifact per spec §6.
- Phase 2 (docker-compose service swap with `WORMBASE_GATEWAY` profile selector), Phase 3 (live end-to-end test against running Hermes), Phase 4 (OpenClaw retirement) deferred — Phase 3 needs a real NousResearch hermes-agent upstream available at the pinned tag, which is not buildable in this session (the spec's `v2026.4.23` git tag may or may not resolve). The receiving end of the migration is fully ready and unit-tested; Phase 2 onwards becomes plumbing the day a real Hermes is reachable.

### 2026-05-21 — Silent-mode gate 6 (openclaw plugin) + WhatsApp shadow-throttle learning

- Cerrado el 6to egress surface del silent-mode design — openclaw embedded agent ya no auto-reply. Implementación final: plugin `wormbase-silent-mode` instalado via `openclaw plugins install --link`, registra hooks `before_agent_reply` + `message_sending` via `api.on` (typed-hook registry — `registerHook` legacy NO claima, descubierto leyendo `dist/loader-CZB9kQVT.js:2241-2316` + `hook-runner-global-D1vhzHUy.js:149/385`). `plugins.entries.wormbase-silent-mode.hooks.allowConversationAccess: true` admite los CONVERSATION_HOOK_NAMES para non-bundled plugins. Verificado live: `HANDLER_FIRING hook=before_agent_reply` + zero outbound.
- Iteración hasta encontrar el set mínimo de hooks correcto: claim de `before_dispatch`/`reply_dispatch`/`before_message_write` rompía la session-JSONL write del agente y por tanto chat_received emission. Sólo `before_agent_reply` + `message_sending` (después de que el inbound ya fue persistido) preservan el audit trail.
- Channel-adapter `whatsapp_envelope_watcher` ahora reconoce el shape nuevo de openclaw 2026.5.6+ (`module: web-inbound` con payload estructurado incluyendo body) y emite `ChatReceivedEvent` directo via callback (`on_inbound=writer.emit`), bypass de la correlación session-JSONL que ya no funciona bajo silent mode. 3 tests nuevos en `test_whatsapp_envelope_watcher.py` (13/13 verde).
- Tenant nuevo `altis` (uuid5 `7f032a92-7036-5126-a957-8d2607126169`) cableado fully containerized + WhatsApp paired al número `+5218114822051`. `infra/openclaw/entrypoint.sh:render_whatsapp_block` ganó emisión de `groupPolicy` + `groupAllowFrom` que estaban silently dropped antes (bug latent — operador setting `WHATSAPP_GROUP_ALLOW_FROM_<TENANT>` no veía efecto). Grupo `120363422164956421@g.us` registrado como Claude↔user command channel — guardado como project memory para futuras sesiones.
- WhatsApp shadow-throttle incident: ~10 admin-CLI outbound messages en 2h desde un número joven gatillaron el soft-throttle (heartbeats firing, `messagesHandled` stuck en 0, `lastInboundAt: null`). Re-pair de la misma SIM NO clear el flag (number-scoped, no session-scoped). Documentado en `infra/openclaw/WHATSAPP_PAIRING.md` con reglas de rate-limit (≤1 admin-CLI message cada 5min sin diálogo activo) y en `docs/known_issues.md` con mecanismo completo + recovery flow.

### 2026-05-21 — Pitch deck + mock demo dashboard para design partner

- Tres artefactos para presentar el producto a un design partner / co-founder con todo en estado *mechanical-turk-as-agent* (humano genera lo que el agente generará).
- `landing/pitch.html` — 11 slides standalone (← / → · `f` fullscreen), buyer/customer lens. Cover · problema · shift · qué es · cómo aterriza (5 pasos en 90s) · ocho loops L1–L8 · qué compone · day-in-the-life (CFO ↔ worm con receipt) · why-now · diferenciador · ask de design partner. Mismo idioma visual que `landing/index.html` (Plex Mono + tan #d4a574).
- `landing/demo-dashboard.html` — mock dashboard con Chart.js (CDN, sin nuevas deps), 4 tabs: conversation · sources & lake · agent loops L1–L8 · compounding knowledge. KPIs, stacks, donuts, sparklines, funnel, tablas de decisions/chains. Datos hardcoded.
- `apps/dashboard/app/demo/page.tsx` + `DemoDashboard.tsx` — versión Field Notebook del mismo dashboard dentro de Next.js (fuera del grupo `(app)/` para no requerir install). Inline SVG para charts, Cards reales de `@wormbase/design`, tokens `--wb-color-*` del design system. Etiquetada **demo · mock data** en el chrome para que sea obvio que no es lectura del ledger.

---

### 2026-05-20 — `make tutorial` green + silent mode end-to-end en fresh clone

- Cold-start path unbreak: cinco regresiones bloqueaban `make tutorial` en un fresh clone — infra/docker-compose.yml openclaw context, 4 Dockerfiles drift respecto a `[tool.uv.workspace]`, double-`wormbase` en tutorial.sh, 4 deps faltantes en worm-core/pyproject.toml, `postgres:16` sin pgvector. Todas documentadas en `known_issues.md` con causa raíz.
- Silent-mode plumbing: `WORMBASE_SILENT_MODE` ahora se forward'a a worm-core/voice-agent/channel-adapter/sim-harness vía compose, documentado en `.env.example`. Default off.
- Silent-mode repair: `apps/worm-core/src/wormbase_core/http_api.py` recibió un helper `_entry_ids_of` que maneja tanto `WriteResult` como `SuppressedToolResult`. 12 endpoints HTTP que crashearon 500 bajo silent mode ahora devuelven 200 con `suppressed: true, entry_ids: [], ref_id`.
- Missing deps en silent-mode merge: `voice-agent` y `channel-adapter` ahora declaran `wormbase-worm-core` (el módulo `silent_mode` vive ahí). uv.lock regenerado.
- Test infrastructure: `tests/integration/test_cold_start_contract.py` — 8 hipótesis sobre el stack vivo (containers up, pgvector instalado, HTTP API responsive, silent_mode field, boot log, vector column, /api/v1/people bajo silent mode). Run con `WORMBASE_LIVE_STACK=1`. `apps/worm-core/tests/test_http_api.py` ganó `test_post_people_under_silent_mode_returns_suppressed_shape`.
- Stack verificado live: `personas_seeded=4 personas_confirmed=4 rich_seed_completed=True` (vs `0/0/False` antes del fix). qa-fast (1188 L1 + 287 L3) verde.

### 2026-05-20 — Bootstrap del workflow de trazabilidad

- Creados `docs/changelog.md`, `docs/known_issues.md`, `docs/decisions.md` en el repo `wormbase-oss` siguiendo el workflow del CLAUDE.md global.
- DELIVERY_LOG.md preservado como registro formal de releases; estos tres archivos cubren el ciclo plan → verify → reflect a nivel de sesión.
