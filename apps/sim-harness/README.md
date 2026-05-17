# wormbase-sim-harness

Scenario-driven driver that posts to Slack as multiple personas from a
single bot account, exercising every Path 3 capture path (silent message,
@mention, file drop). Two pacing modes:

- `--pace wall` (default) — real-time pacing for live demos.
- `--pace virtual` — instant pacing for fast dashboard replays + tests.

The harness writes nothing to the ledger directly; it drives Slack and
lets OpenClaw + the channel-adapter capture deterministically. After
the run it reads the ledger and checks the four Path 3 invariants
(`chat_received`, `file_received`, `source_proposed`, `chat_sent`).

## Files

- `personas.yml` — three personas (Alice, Bob, Carol) with display
  name, icon emoji, role, and voice hint.
- `scenarios/demo-c-plus-b.yml` — the canonical C+B arc (autonomous
  discovery + reproducibility).
- `fixtures/sales-q3.csv` — sample CSV that beats can `drop`.

## Run

Provision the `WormBase Sim` Slack app once from
`docs/slack-sim-manifest.json`, install it to the workspace, copy the
bot token into `.env` as `SLACK_BOT_TOKEN_SIM_BASEWORM`, then:

```bash
make demo            # wall-clock pacing
make demo-virtual    # virtual pacing
```

Or directly:

```bash
uv run --package wormbase-sim-harness wormbase demo personas
uv run --package wormbase-sim-harness wormbase demo scenarios
uv run --package wormbase-sim-harness wormbase demo run --pace wall
uv run --package wormbase-sim-harness wormbase demo run --pace virtual --skip-acceptance
```

## Slack scopes

The Sim bot needs `chat:write`, `chat:write.customize` (REQUIRED for
per-post username + icon overrides), `files:write`, `channels:read`,
`groups:read`. No event subscriptions, no SocketMode.

## File-upload attribution

Slack's API does not let third-party callers attribute uploads to a
non-bot user. Files appear under the bot account; the surrounding
scripted `say` posts (which DO carry persona overrides) preserve the
conversational illusion.

## Improvisation

Beats can declare `improv: true` to ask the LLM (`kimi-k2.6:cloud` via
Ollama) to riff on the seed line in-character. Without `OLLAMA_API_KEY`
the harness silently degrades to the literal `say` text — the demo
still runs.
