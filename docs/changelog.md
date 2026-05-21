# Changelog de sesiones

> Registro breve de progresos y cambios completados por sesión de trabajo con Claude Code.
> Para el registro formal de releases/shipments, ver `DELIVERY_LOG.md`.

## Cómo usar este archivo

- Una entrada por tarea/sesión significativa.
- Formato: `### YYYY-MM-DD — <título corto>` seguido de 1-3 bullets de qué cambió.
- No duplicar contenido de `DELIVERY_LOG.md`: aquí va el "qué hice esta sesión", allá el "qué shippeó la fase".
- Si la sesión generó lecciones, enlazar a la entrada correspondiente en `known_issues.md`.

---

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
