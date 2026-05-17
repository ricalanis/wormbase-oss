# sim-harness scenarios

Scripted Slack-channel scenarios that drive the demo. Each scenario is a
sequence of beats (`at`, `persona`, `say` | `drop`) defined in YAML. The
harness posts each beat to a real Slack workspace; OpenClaw + the
channel-adapter capture the events into the ledger. Pacing modes:

- `--pace wall` — real-time, for live demos
- `--pace virtual` — instant, for fast dashboard replays + tests

## Canonical product arc

Every scenario in this directory maps onto the canonical 5-step product
arc defined in
[`docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`](../../../docs/superpowers/specs/2026-04-26-wormbase-product-arc.md):

```
1. CONNECT          Install. Worm joins ANY chat platform.
2. GROW THE LAKE    Medallion (bronze → silver → gold) across all
                    six source-building flows.
3. BUILD CONCURRENTLY    KPI tree + governance + process retrieval
                    grow together from one ledger.
4. PRODUCE + CONVERSE    Data products + text/voice with receipts.
5. SELF-IMPROVE PER USER Per-position autoresearch (Karpathy-style).
```

## Scenario catalog

| Scenario | Wall-clock | Beats | Steps covered | On-thesis criteria | Use |
|---|---:|---:|---|---|---|
| [`warmup`](warmup.yml) | ~15s | 3 | (none — health check) | — | Pre-demo health ping; ops only. Do not run on stage. |
| [`demo-c-plus-b`](demo-c-plus-b.yml) | ~115s | 14 | **1, 2, 3, 4a, 4b, 5** | C1, C2, C3, C5, C6, C7, C8 | Canonical investor demo. 5 acts mapping 1:1 onto the product arc, including multitenancy + voice cue + per-user research log. |
| [`extended-replay`](extended-replay.yml) | ~3.5 min wall, 5d virtual | 32 | **1, 2, 3, 4a, 4b, 5** | C1, C2, C3, C5, C6, C7, C8 | Virtual-mode fictional-week run with 4 personas (incl. data engineer Dave). Compounding state visible: KPI tree thickens, process map thickens, per-position autoresearch wins accumulate for both CFO + DE. |
| [`proactivity-demo`](proactivity-demo.yml) | ~60s | 6 | **2** (mentioned_in_conv'n + credential_offered_in_dm), **4a, 4b** | C1, C2, C3, C6, C7, C8 | Focused hero beat for the source-proactivity flow. Use as 60s elevator-pitch fallback or partner walkthrough. |

## Demo-arc mapping (which scenario uses which act)

| Step | Demo Act | demo-c-plus-b | extended-replay | proactivity-demo |
|---|---|:---:|:---:|:---:|
| 1. CONNECT | I | yes (lurk-in) | yes (Carol+Dave register) | implicit |
| 2. GROW THE LAKE | II | yes (drop + Stripe mention) | yes (5 drops + 2 mentions + lake_discovery) | yes (Stripe end-to-end) |
| 3. BUILD CONCURRENTLY | III | yes (Q3 question + retention) | yes (KPI Qs Mon-Fri, decision extracted Wed) | partial (cited answer) |
| 4a. DATA PRODUCTS | III/IV | yes (board artifact) | yes (board artifact Thu) | partial |
| 4b. CONVERSE | IV | yes (multitenancy + voice cue) | partial | partial |
| 5. SELF-IMPROVE | V | yes (CFO research log) | yes (CFO + DE wins, different positions) | no |

## On-thesis criteria reference

From [`/Users/ricalanis/Dev/agentic_datasci/.claude/CLAUDE.md`](../../../../.claude/CLAUDE.md)
(The On-Thesis Rubric):

- **C1** unprompted action
- **C2** deterministic output
- **C3** compounding state
- **C4** near-zero maintenance cost
- **C5** metric-governed self-improvement
- **C6** auditable governance
- **C7** domain specialization
- **C8** unprompted surface, prompted depth

Every scenario shipped here hits ≥ 4 criteria (per the rubric: any demo
must visibly instantiate ≥ 4).

## Personas

Defined in [`../personas.yml`](../personas.yml). The harness uses
`chat:write.customize` to post as each persona from a single bot.

| id | display_name | role | voice_hint |
|---|---|---|---|
| `alice` | Alice Chen | Marketing Lead | data-driven, friendly, growth/retention questions |
| `bob` | Bob Martin | Data Engineer | terse, technical, drops files, schema-aware |
| `carol` | Carol Reyes | CFO | concise, revenue/unit-economics, actuals vs forecast |
| `dave` | Dave Park | Data Engineer | infra-minded, pipeline-latency / schema-drift / cost |

Note: `bob` and `dave` are both engineers but with distinct voices —
Bob is the in-team operator who drops files; Dave is the platform/infra
lens who asks p95-shaped questions. They exist to demonstrate that
**Step 5's per-position autoresearch** produces different wins for
different people in the same role tag.

## Fixtures

In [`../fixtures/`](../fixtures/):

- `sales-q3.csv` — 20 rows, Q3 sales by region+product
- `q3-revenue-actuals.csv` — Q3 monthly plan/expansion/churn/net
- `customers-active.csv` — 15 active customer rows
- `churn-events.csv` — Q3 churn events (reason, MRR lost, paying)
- `retention-cohorts.csv` — cohort retention by signup month
- `stripe-payouts.csv` — 10 Stripe payouts (gateway-fee + net)
  for the proactivity scenario

## Run

```bash
# List scenarios
uv run --package wormbase-sim-harness wormbase demo scenarios

# Validate without posting
uv run python -c "from wormbase_sim_harness.scenario import Scenario; \
  Scenario.from_yaml('apps/sim-harness/scenarios/demo-c-plus-b.yml')"

# Live runs
uv run --package wormbase-sim-harness wormbase demo run \
  --scenario demo-c-plus-b --pace wall
uv run --package wormbase-sim-harness wormbase demo run \
  --scenario extended-replay --pace virtual --skip-acceptance
uv run --package wormbase-sim-harness wormbase demo run \
  --scenario proactivity-demo --pace wall
```

## Conventions

- All `at` values must be monotonic non-decreasing.
- All `persona` references must exist in `../personas.yml`.
- All `drop.file` references must exist in `../fixtures/`.
- Scenario header comments include the canonical-arc mapping and
  narrator runbook notes; keep them runbook-quotable.
- Add new scenarios as content-only changes; do NOT modify the
  scenario engine code unless you also update `scenario.py` and tests.

## Open questions for the runbook author (W3.G)

- DM beats are narrated in comments because the `Beat` schema does not
  yet have a `channel: dm` field. If we want the harness to drive DMs
  on stage, extend `Beat` and the engine to accept a `channel` override
  (per-beat) and wire it into `slack_poster.post_message`.
- The voice modality cue in `demo-c-plus-b` Act IV depends on whether
  ElevenLabs is provisioned for the run. Runbook should ship both a
  live-call branch and a screencap branch.
- The `lake_discovery` flow in `extended-replay` Day 1 is referenced via
  narrator comment; if we want it visible in the dashboard, run
  `wormbase-worm-core discover-lake --uri snowflake://demo/wh/analytics`
  in a side panel before the scenario starts.
