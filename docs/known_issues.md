# Lecciones aprendidas y errores conocidos

> Memoria institucional: errores pasados, su causa raíz y cómo evitarlos.
> Consultar SIEMPRE antes de tocar áreas sensibles del codebase.

## Cómo usar este archivo

Cada entrada documenta un error o malentendido, no una bug abierta del producto (esas van en el tracker formal). El objetivo es que un futuro tú (o Claude) no vuelva a tropezar con la misma piedra.

Formato por entrada:

```
### YYYY-MM-DD — <título corto del error>

**Contexto:** Qué se intentaba hacer.
**Qué pasó:** El síntoma observado.
**Causa raíz:** Por qué pasó (no el síntoma).
**Cómo evitarlo:** Regla concreta para el futuro. Si aplica, enlazar a `decisions.md`.
```

Antes de empezar trabajo no trivial, ojear esta lista y filtrar por área tocada.

---

<!-- Entradas más recientes arriba -->

### 2026-05-21 — Gate-6 stripping rompió emisión de `chat_received` (audit-trail regression)

**Contexto:** Gate-6 commits 9f27128 + f45c9b0 cerraron el outbound reply path bajo silent mode (verificado live: cero "Missing API key" replies después del fix `api.on` + `allowConversationAccess`). Pero un DM de prueba mostró que `chat_received` ya no aterriza en el ledger bajo silent mode.
**Qué pasó:** El entrypoint.sh, bajo `WORMBASE_SILENT_MODE=1`, estaba:
- emptiying `bindings: []`
- pop'ing `agents` y `models` del rendered config
- `rm -rf /root/.openclaw/agents` para que openclaw no resucitara el agent main desde estado persistido

Eso defeated el openclaw default agent (gpt-5.5 fallback) — pero también destruyó el lifecycle que el channel-adapter usa para emitir `chat_received`. El channel-adapter tiene dos paths de inbound:
1. `whatsapp_envelope_watcher` — espera `subsystem: gateway/channels/whatsapp/inbound` (openclaw 2026.5.6+ ahora usa `module: web-inbound` — regex desactualizada, gap separado)
2. Session-JSONL tailer — depende de que el agente procese el mensaje y escriba a `/root/.openclaw/agents/main/sessions/*.jsonl`

Sin agent → sin session → sin chat_received. Violation explícita del spec: "Listen-everything still works: ingestion, ledger writes, presence/relevance decisions all run normally."
**Causa raíz:** Over-engineering del gate. El plugin `wormbase-silent-mode` (instalado via `openclaw plugins install --link`) registra el hook `before_agent_reply` via `api.on` (typed-hook registry) y claims con `{handled:true}`. `runClaimingHook` honra el claim — el LLM call nunca pasa, sin reply outbound, sin error. El config-side stripping era redundante una vez que el plugin funcionaba.
**Cómo evitarlo:** Mantener el openclaw config completo bajo silent mode (agents + models + bindings). El plugin es el único gate necesario. `channels.whatsapp.actions.sendMessage: false` queda como defensa en profundidad. Si el plugin alguna vez no claima (e.g. crash on register), el agente correrá y producirá un reply LLM real — riesgo aceptado a cambio de mantener el audit trail. Fix: revertir el stripping en `infra/openclaw/entrypoint.sh`, dejar el render full bajo silent mode, plugin hace el trabajo.

### 2026-05-20 — Silent-mode merge: `_result_payload` no maneja `SuppressedToolResult` → HTTP 500 en todos los writes

**Contexto:** Después de habilitar silent mode (`WORMBASE_SILENT_MODE=1`) en el stack vivo, el seed persona falló con `propose_person alice returned HTTP 500: 500 Internal Server Error - Server got itself in trouble`.
**Qué pasó:** Bajo silent mode, `write_actions._pevr` devuelve `SuppressedToolResult` (sin atributo `entry_ids`). Pero `apps/worm-core/src/wormbase_core/http_api.py` hace `[str(eid) for eid in write_result.entry_ids]` directamente en 12 endpoints (más una llamada al helper `_result_payload`). Todas crashean `AttributeError: 'SuppressedToolResult' object has no attribute 'entry_ids'` → HTTP 500. Endpoints rotos: `/api/v1/people`, `/api/v1/kpis/propose`, `/api/v1/notebooks/replay`, varios bajo `/api/v1/data-products/*`, etc.
**Causa raíz:** El silent-mode merge (5a70563) gated `_pevr` pero no actualizó los 12 sitios del wrapper HTTP que destructuran `write_result.entry_ids` inline. Los tests del merge usaban `InMemoryLedger` directamente vía `write_actions._pevr`, no a través del HTTP API, así que el gap no se vió.
**Cómo evitarlo:** (1) Helper único `_entry_ids_of(write_result)` que maneja ambos tipos, usado por todos los call sites — la refactor cierra la clase de bug entera. (2) Test `test_post_people_under_silent_mode_returns_suppressed_shape` valida el contrato del response shape bajo silent mode (200, `suppressed: true`, `entry_ids: []`, `ref_id`). (3) Test cold-start `H8` lo verifica contra el stack vivo. (4) Considerar agregar un grep guard al script `check_silent_mode_coverage.sh` que falle si `*.entry_ids]` aparece fuera del helper.

### 2026-05-20 — Silent-mode merge no agregó `wormbase-worm-core` como dep de voice-agent + channel-adapter

**Contexto:** Después del rebuild post-pull (commit 5a70563 silent-mode merge), `voice-agent` y `channel-adapter` quedan en restart loop con `ModuleNotFoundError: No module named 'wormbase_core'`.
**Qué pasó:** Los commits del merge (0616a5c boot log, 9e49f8b dm.send gate, 60e9104 voice-agent /webhook gate) agregaron `from wormbase_core import silent_mode` en:
- `apps/channel-adapter/src/wormbase_channel_adapter/cli.py:97`
- `apps/channel-adapter/src/wormbase_channel_adapter/dm.py:203`
- `apps/voice-agent/src/wormbase_voice_agent/app.py:80`

…pero ninguno de esos PRs agregó `wormbase-worm-core` al `[project.dependencies]` de `apps/voice-agent/pyproject.toml` ni de `apps/channel-adapter/pyproject.toml`. Los Dockerfiles instalan en producción con `uv sync --package <app> --no-dev --frozen` — sólo lo declarado.
**Causa raíz:** Idéntica al patrón del bug "worm-core deps drift" anterior. CI corrió con uv sync de TODOS los packages del workspace (que sí incluye worm-core) entonces ningún test detectó el missing dep. Producción es estricta y rompe.
**Cómo evitarlo:** Mismo check que documentamos en la entrada de worm-core: en CI, agregar un guard que compare `grep "^from wormbase_\|^import wormbase_" apps/<X>/src` contra `[project.dependencies]` y falle si hay imports sin dep declarado. Idealmente refactor: mover `silent_mode.py` a un sub-package liviano (`packages/wormbase-silent-mode/` o dentro de `packages/ledger`) para que sea cheap de importar sin arrastrar todo el árbol de worm-core. Fix corto: agregar `"wormbase-worm-core"` a ambas apps + regenerar `uv.lock`.

### 2026-05-20 — `postgres:16` no incluye pgvector — worm-core en restart loop

**Contexto:** Después de pasar todos los fixes anteriores, el stack levantó pero `worm-core` quedó en `Restarting (1)`. `doctor` reportaba HTTP 000000 en `:8910` (no bind).
**Qué pasó:** En el boot de worm-core, las migraciones del ledger v016 (`projection_query_outcomes`) y v017 (`projection_query_templates`) ejecutan `CREATE EXTENSION IF NOT EXISTS vector` para columnas `Vector(1536)` (pgvector). La imagen `postgres:16` (stock) no trae la extensión, así que la migración falla con `asyncpg.exceptions.FeatureNotSupportedError: extension "vector" is not available`. worm-core no puede arrancar, queda en restart loop, MCP server no se levanta tampoco (depende de worm-core).
**Causa raíz:** El compose file usaba `postgres:16` (stock) pero el codepath requiere pgvector ≥0.6 desde el commit que añadió v016. Mismo patrón que los otros bugs: cambio de codepath sin actualizar la infra.
**Cómo evitarlo:** Usar `pgvector/pgvector:pg16` (imagen oficial, drop-in para postgres:16). Una migración nueva que use `CREATE EXTENSION` debería incluir un test que la corra contra la imagen real del compose, o un linter que escanee `migrations/*.py` por `CREATE EXTENSION` y falle si el compose no usa la imagen correspondiente. Wipe del volumen `postgres-data` requerido al cambiar la imagen porque v016 corrió parcialmente.

### 2026-05-20 — `apps/worm-core/pyproject.toml` drift respecto a imports reales

**Contexto:** Después de fix de la doble-`wormbase` en tutorial.sh, el seed corrió pero falló con `ModuleNotFoundError: No module named 'wormbase_chat_presence'`.
**Qué pasó:** `apps/worm-core/src/wormbase_core/classifier.py` (y 5 archivos más) importan `wormbase_chat_presence`, pero `apps/worm-core/pyproject.toml` no declaraba `wormbase-chat-presence` como dep. Audit completo reveló 4 packages importados sin declarar: `wormbase-chat-presence`, `wormbase-identity-tracker`, `wormbase-process-extractor`, `wormbase-research-loop`.
**Causa raíz:** Los 4 packages se extrajeron de worm-core en algún refactor pero el pyproject.toml de worm-core no se actualizó. uv sync `--package wormbase-worm-core` solo instala lo declarado en el pyproject — los imports a nivel de código rompen en runtime aunque los packages existan en `[tool.uv.workspace]`. Las apps no fallan en build (uv sync se conforma con lo declarado) sino al primer import.
**Cómo evitarlo:** Agregar a CI un check estilo `grep -rh "^from wormbase_\|^import wormbase_" apps/<X>/src` comparado contra los deps declarados en `apps/<X>/pyproject.toml`. La fórmula del audit que usé está abajo en este doc — usable como template. Fix: agregar los 4 deps a `[project.dependencies]` y `[tool.uv.sources]`, luego `uv lock` para regenerar `uv.lock` (que también incluye las nuevas deps editables).

### 2026-05-20 — `scripts/tutorial.sh` invoca el CLI con `wormbase` duplicado

**Contexto:** Después de fix de los Dockerfiles, la build completó y el stack levantó. La step 4 (seed baseworm) falló con `Error: No such command 'wormbase'`.
**Qué pasó:** El ENTRYPOINT del contenedor `sim-harness` es `["uv", "run", "--package", "wormbase-sim-harness", "wormbase"]`. `tutorial.sh` llamaba `$COMPOSE run --rm sim-harness wormbase demo seed ...` — eso resulta en `wormbase wormbase demo seed ...` y el Click group no tiene un subcomando llamado `wormbase` (sólo `demo`).
**Causa raíz:** `scripts/demo-setup.sh` (que estaba bien) llama `... sim-harness demo seed --reset-first ...` sin el prefijo `wormbase`. `tutorial.sh` se escribió con el patrón equivocado en 3 lugares (líneas 122, 132, 142).
**Cómo evitarlo:** Al pasar args a un contenedor con ENTRYPOINT prefijado, no repetir el binario. Regla práctica: si el ENTRYPOINT del Dockerfile termina en el binario, el caller pasa directamente los subcommands. Verificar haciendo `docker compose run --rm <svc> --help` — si responde el CLI bien, los args van directos. Fix: replace_all `sim-harness wormbase demo seed` → `sim-harness demo seed`.

### 2026-05-20 — Dockerfiles de apps drift respecto a `[tool.uv.workspace]`

**Contexto:** Después de fix del bug del openclaw context, `docker compose build` fallaba con `failed to calculate checksum of ref ...: "/packages/connectors/pyproject.toml": not found`.
**Qué pasó:** El commit `53469f3` (rename `connectors` → `lake-surfaces`) actualizó código y root `pyproject.toml` pero no los 4 Dockerfiles de apps (worm-core, voice-agent, sim-harness, channel-adapter) que todavía hacían `COPY packages/connectors/...`. Adicional: las listas de `COPY packages/<X>/pyproject.toml` también estaban desactualizadas — el root `[tool.uv.workspace]` tiene 16 packages, voice-agent/sim-harness sólo copiaban 7, channel-adapter sólo 14 (faltaban `wormbase-agent-gateway` y `wormbase-catalog-mirror`).
**Causa raíz:** Patrón frágil. Cada vez que se agrega un workspace member o se renombra uno, hay que actualizar manualmente N Dockerfiles. `uv sync --frozen` exige que TODOS los miembros de `[tool.uv.workspace]` sean descubribles en build time, y un missing pyproject.toml rompe el solver antes incluso de intentar `--package <name>`.
**Cómo evitarlo:** Los 4 Dockerfiles ahora hacen `COPY packages /workspace/packages` + `COPY apps /workspace/apps` en lugar de enumerar package por package. Esto elimina la clase entera de bug (Dockerfile drift respecto al workspace block) a cambio de un poco menos de granularidad de layer-caching. Si en el futuro se quiere recuperar caching fino, hay que asegurarse de que CI tenga un linter que falle si la lista del Dockerfile difiere de `[tool.uv.workspace].members`. Considerar también añadir un `.dockerignore` para evitar arrastrar `tests/`, `__pycache__/`, etc. al contexto.

### 2026-05-20 — `make tutorial` falla con `path "/.../openclaw" not found`

**Contexto:** Cold-start vía `make tutorial` en un fresh clone del repo.
**Qué pasó:** `docker compose up` falló 3 veces con `unable to prepare context: path "/home/ricardo/wormbase/wormbase-oss/openclaw" not found`. Tutorial.sh reportó "make up failed after 3 attempts" y abortó.
**Causa raíz:** `infra/docker-compose.yml` línea 59 usaba `context: ./openclaw`. El resto del archivo usa contextos relativos al project root (`.` o `./infra/<svc>`) porque `scripts/tutorial.sh` invoca compose con `--project-directory .`. El path `./openclaw` se resolvía contra `wormbase-oss/`, no existe — el dir real es `wormbase-oss/infra/openclaw/`. El comentario de línea 55 ya documentaba la intención correcta ("Built from `infra/openclaw/Dockerfile`"), pero la línea 59 estaba mal desde el commit inicial (`55e8c1a`).
**Cómo evitarlo:** Cuando se invoca `docker compose` con `--project-directory`, todos los `build.context` se resuelven contra ese dir, no contra el dir del compose file. Auditar build contexts en cada PR que toque `infra/docker-compose.yml` o `scripts/tutorial.sh`. Fix: `context: ./openclaw` → `context: ./infra/openclaw`.
