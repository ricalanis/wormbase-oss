# Hermes spike (Block H Task H1)

Stands up [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
v0.11.0 alongside the running OpenClaw service. The goal is the GO/NO-GO
gate from
`docs/superpowers/specs/2026-04-27-openclaw-to-hermes-migration.md` §5
Phase 0: confirm the inbound-message hook fires deterministically for
every Slack message.

## What's here

```
infra/hermes/
├── Dockerfile                 # python:3.12-slim + uv pip install hermes-agent (git tag v0.11.0)
├── entrypoint.sh              # renders ~/.hermes/cli-config.yaml + .env from container env, installs the wire-tap hook, exec's `hermes gateway run`
├── hooks/wire-tap/            # spike hook (HOOK.yaml + handler.py) — POSTs every agent:start to the channel-adapter spike endpoint
└── README.md                  # this file
```

## Env vars

Hermes is added to the existing docker-compose alongside OpenClaw, so
it picks up these vars from the project root `.env`:

| Var | Purpose |
|---|---|
| `SLACK_BOT_TOKEN_BASEWORM` | Per-workspace Slack bot token |
| `SLACK_APP_TOKEN_BASEWORM` | Slack app-level token (Socket Mode) |
| `WORMBASE_HERMES_SPIKE_ENDPOINT` | Where the hook POSTs (default: `http://channel-adapter:18790/hermes-spike`) |
| `WORMBASE_TENANT_ID` | Tenant slug, defaults to `baseworm` |

## Bring up

The image is added to `infra/docker-compose.yml` as a `hermes` service.
Build + boot via the existing wormbase compose tooling:

```bash
docker compose --project-directory . -f infra/docker-compose.yml build hermes channel-adapter
docker compose --project-directory . -f infra/docker-compose.yml up -d hermes channel-adapter
```

OpenClaw stays up. Hermes runs in parallel, with its hook POSTing to a
NEW spike subcommand on the channel-adapter (`wormbase-channel-adapter
hermes-spike`), independent of the OpenClaw consumer (`run`).

## Verify the hook fires

```bash
# Tail Hermes startup and look for the wire-tap registration.
docker compose --project-directory . -f infra/docker-compose.yml logs hermes --tail=80 \
  | grep -E "Loaded hook|wire-tap|wormbase"

# Tail the spike endpoint's JSONL.
docker compose --project-directory . -f infra/docker-compose.yml exec channel-adapter \
  tail -f /var/log/wormbase/hermes-spike.jsonl
```

Then trigger a message — either by posting in `#todo-baseworm` directly
or by running the spike scenario:

```bash
docker compose --project-directory . -f infra/docker-compose.yml run --rm sim-harness \
  wormbase demo run \
    --script /workspace/apps/sim-harness/scenarios/hermes-spike.yml \
    --pace virtual
```

Each post should produce a JSONL line on the spike endpoint within
~100ms of the Slack delivery.

## GO / NO-GO

The spike PASSES if every inbound message in
`apps/sim-harness/scenarios/hermes-spike.yml` (5 messages) lands one
JSONL line on the spike endpoint AND the line carries enough fields
to reconstruct an `InfraEvent`. The full GO/NO-GO write-up lands at
`docs/notes/2026-04-27-hermes-h1-spike.md` after the spike runs.

## Roll back

The Hermes service is additive. To roll back:

```bash
docker compose --project-directory . -f infra/docker-compose.yml stop hermes
```

OpenClaw + the production channel-adapter `run` command are unaffected.

## Pointers into upstream Hermes

* Hooks system: `gateway/hooks.py` — registry walks `~/.hermes/hooks/`
* Event emission: `gateway/run.py:4894` (`agent:start`)
* Available events: `gateway:startup`, `session:start`, `session:end`,
  `session:reset`, `agent:start`, `agent:step`, `agent:end`, `command:*`
* Hook context for `agent:start`:
  `{platform, user_id, session_id, message}`
* Slack adapter: `gateway/platforms/slack.py`
