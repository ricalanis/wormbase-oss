# wormbase-worm-core

Python service implementing the reactivity triad (infrastructure → semantic → relevance), source-building primitive (6 flows), conversation contract, knowledge ramp computation, and autoresearch loop. Depends on `wormbase-ledger` for writes, `wormbase-inference-router` for classification, and `wormbase-governance` for gates; every operation is scoped by `company_id`. Run with `uv run python -m wormbase_core` once Phase 3 implements the service entry point.

## Step 2 — Grow the Lake

This package realises **Step 2 (GROW THE LAKE)** of the canonical product arc — see [`docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`](../../docs/superpowers/specs/2026-04-26-wormbase-product-arc.md). Every source flowing into WormBase is run through a uniform medallion pipeline:

```
RAW BYTES   →   BRONZE PROFILED   →   SILVER TYPED + ENRICHED   →   GOLD BUSINESS-READY
                emit_source_bronzed   emit_source_silvered          emit_source_golded
                                                                    emit_kpi_proposed (when applicable)
```

Six source-building flows feed the cascade, each writing into the same hash-chained ledger:

| Flow | Module | Trigger |
|---|---|---|
| `drop_and_profile` | `wormbase_core.flows.DropAndProfileFlow` | File dropped in a channel |
| `credential_offered_in_dm` | `wormbase_core.flows.CredentialInDmFlow` | Token / connection string in a DM |
| `mentioned_in_conversation` | `wormbase_core.flows.MentionedInConversationFlow` | Repeated archetype mention in chat |
| `dashboard_form` | `wormbase_core.flows.DashboardFormFlow` | Manual add via UI |
| `kpi_gap_triggered` | `wormbase_core.flows.KpiGapTriggeredFlow` | Worm observes a KPI tree gap |
| `lake_discovery` (NEW) | `wormbase_core.flows.LakeDiscoveryFlow` | Existing-lake catalog walked at install time |

The medallion cascade lives in `wormbase_core.medallion.MedallionCascade`. Each layer fires through the canonical PEVR primitive (propose → execute → verify → resolve) so replay reproduces the same hashes (Triad C2 — deterministic output).

### `discover-lake` CLI

```
wormbase-worm-core discover-lake --uri snowflake://demo/wh/analytics
wormbase-worm-core discover-lake --uri postgres://host/db
wormbase-worm-core discover-lake --uri s3://bucket/prefix
```

Mocks the catalog walk (deterministic, offline). Writes one `source_proposed` per discovered table plus a single `lake_discovered` summary entry. The medallion cascade fires for each discovered source.

## Step 3c — Process Retrieval

This package also realises **Step 3c (BUILD CONCURRENTLY · process retrieval)** of the canonical product arc. The worm reads its own conversation lake (every `channel_adapter.emit_chat_received` ledger entry) and promotes structured artefacts back into the ledger:

| Output kind | Tool name | Trigger |
|---|---|---|
| Decision record | `emit_decision_recorded` | "we decided X", "approved", "agreed" |
| Process map | `emit_process_map_proposed` | Ordered actor → action sequences |
| System map node | `emit_system_map_node` | Running tally of who-mentions-whom + channel topics |
| Recurring question | `emit_recurring_question` | Normalized question observed ≥ 2× |

Implementation lives in `packages/wormbase-process-extractor` as four W5a Reactivities (`topic_synthesis`, `recurring_question_process_mapper`, `decision_record`, `system_map_node`), registered into the worm-core boot path via `wire_process_for_install` alongside the other lifecycle wires. Reactivities fire on ledger entries; there is no polling loop.

The extractor is hybrid: pre-filter heuristics catch the obvious cases deterministically; Kimi (via `OLLAMA_API_KEY` + the same Ollama Cloud endpoint as `OllamaCloudClassifier`) widens coverage when reachable. When the cloud is offline the heuristic path produces the demo evidence, so this subsystem never goes silent.

The dashboard surfaces three new live-only tabs that read these entries:

* `/decisions` — table of decisions with channel filter + recurring questions sidebar.
* `/processes` — one swimlane diagram per process map (SVG, no graph library).
* `/system-map` — concentric-ring force-suggested SVG of persons, channels, and weighted edges.

See [`docs/process-retrieval.md`](./docs/process-retrieval.md) for the full pipeline write-up (prompts, heuristics, on-thesis criteria).

## Source proactivity (`mentioned_in_conversation`)

Step 2 of the canonical product arc — see [`docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`](../../docs/superpowers/specs/2026-04-26-wormbase-product-arc.md).

The relevance gate now detects bare data-source mentions in channel messages (no `@worm` required). The keyword list lives in [`wormbase_core.relevance._DATA_SOURCE_KEYWORDS`](src/wormbase_core/relevance.py) and is intentionally aligned with the recognized remote archetypes used by [`wormbase_core.flows.propose_remote_archetype`](src/wormbase_core/flows.py) and `recognized_remote_archetypes` (see W2.B's [`flows.py`](src/wormbase_core/flows.py) helpers — `_REMOTE_ARCHETYPE_URIS`).

Demo arc:

1. Bob: "we should pull from Stripe."
2. Relevance gate fires `should_react=True`, `suggested_flow="mentioned_in_conversation"` (confidence ≥ 0.6).
3. Dispatcher calls `MentionedInConversationFlow.on_proactive_mention(event)`, which writes:
   * `emit_source_proposed` (added_via_flow=`mentioned_in_conversation`)
   * `emit_proactive_offer` (the worm's speech act with `offer_text`)
4. Worm posts the offer in-channel: "I noticed you mentioned Stripe — want me to wire that up?"
5. Bob DMs the API key.
6. `CredentialInDmFlow` runs; `link_credential_to_proactive_offer` finds the recent offer and writes `proactive_offer_credential_link` so the dashboard can render the full mention → offer → credential → cascade trail.
7. `MedallionCascade.run(source_id)` fires bronze → silver → gold for the new source.

Wiring lives in [`make_flow_dispatcher_with_proactivity`](src/wormbase_core/service.py).

## Step 5 — Self-Improve Per User

This package realises **Step 5 (SELF-IMPROVE PER USER)** of the canonical product arc. For every `(person × position)` pair the tenant has registered, the worm runs a continuous Karpathy autoresearch loop:

```
modify code  →  pick an ImprovementCandidate for the user's position
train        →  emit_experiment_run (mocked execution log)
evaluate     →  read the user's headline metric (per their position)
keep|discard →  emit_experiment_resolved with observed_delta + rationale
```

Eight new ledger payloads (see `packages/ledger/src/wormbase_ledger/entries.py`):

| Payload | Tool | Purpose |
|---|---|---|
| `person_registered` | `emit_person_registered` | Onboarded person + role |
| `position_assigned` | `emit_position_assigned` | Person ↔ position mapping |
| `position_metric_added` | `emit_position_metric_added` | Extending a position's metric set |
| `position_question_pattern` | `emit_position_question_pattern` | Observed question pattern for a position |
| `experiment_proposed` | `emit_experiment_proposed` | Autoresearch step 3 |
| `experiment_run` | `emit_experiment_run` | Autoresearch step 4 (mock log) |
| `experiment_resolved` | `emit_experiment_resolved` | Autoresearch step 5 (keep / discard) |
| `metric_observed` | `emit_metric_observed` | Headline-metric sample (sparkline source) |

Implementation:

* `wormbase_core.positions` — canonical position registry (CFO, CMO, data engineer, marketing lead, ops manager, customer success, founder, admin, product manager) with metrics + question patterns + improvement candidates.
* `wormbase_core.autoresearch_loop.AutoresearchLoop` — per-tenant driver that walks `(person × position)` pairs and emits the propose → run → resolve cycle for each.
* `service.autoresearch_loop_runner` / `cli._run_async` — periodic background task. Default interval 30s in dev (`WORMBASE_DEV=1`) / 600s in prod; explicit override via `WORM_CORE_AUTORESEARCH_INTERVAL_S`.

Outcomes are deterministic: `hash(experiment_id) % 5 < 3` ⇒ keep (60% rate). Wins land 90% of the expected delta, losses regress slightly — replayable, never random.

Dashboard surfaces:

* `/research` — per-tenant overview (totals + win rate + top movers) + per-user view (sparkline + experiments queue with approve / discard).
* Tier-1 onboarding wizard captures installer name + position; writes `emit_person_registered` + `emit_position_assigned` so the autoresearch loop has someone to seed Step 5 with from minute one.

See [`docs/autoresearch.md`](./docs/autoresearch.md) for the full Karpathy mapping + demo expectations.
