# Demo-Day PRD — 2026-04-30 (v2 — Value-Showcase Edition)

**Status:** Authoritative for the 24-hour pre-demo window. Supersedes v1.
**Authored:** 2026-04-29.
**Inputs:** Council session 012 (full board) + autonomous-status (`docs/superpowers/notes/2026-04-28-autonomous-status.md`) + canonical commitments (`CLAUDE.md`) + canonical framework (`/Users/ricalanis/Dev/agentic_datasci/.claude/CLAUDE.md` § Triad).
**Supersedes:** v1 of this PRD. Extends `2026-04-26-wormbase-product-arc.md` and `2026-04-26-production-dashboard-and-identity.md`.

This is the value-showcase edition. v1 closed the council's gaps; v2 expands the arc so every Triad criterion (C1–C8) lands on stage and every council voice has a load-bearing item. Scope grows; capacity per the project's empirical calibration is ~100–200× scope, so the additions are dispatchable in two parallel waves of ~30 min each.

If this PRD conflicts with a prior PRD, this one wins for the 24-hour window. After demo day, fold accepted decisions back into the prior specs and retire this file.

---

## 1. Why this PRD exists

The substrate is shipped. v0.4.0-resilient is tagged: 2,725 tests, 9-beat install arc, Reactivity Protocol, Statement-to-Owner, phenomenon-gap detectors, autoresearch at Person/Team/Company scopes, full Connector + ChannelAdapter contracts, multi-tenant identity model with three role facets, MCP-native bidirectional surface across all features, ledger-projected dashboard with 70+ pages, voice agent with graceful degradation, demo orchestrator with per-beat auto-recovery.

The council's convergent finding is that **the substrate has outrun the user**. v1 of this PRD closed five gaps. v2 closes them all and adds the items that turn each gap-closure into a visible stage moment so the demo *showcases the value of the worm*, not just its plumbing.

The worm's value rests on eight Triad criteria (C1–C8 in `CLAUDE.md`). Each must be visible on stage in <30 seconds. v2 ensures every criterion has at least one P-item that produces a stage moment.

| Triad criterion | Stage moment | Owning P-items |
|---|---|---|
| C1 — Unprompted action | Statement-to-Owner DM fires without being asked (Beat 9) | P3, P12, P15-as-seed |
| C2 — Deterministic output | Two tenants, same JSONL replay, byte-identical hash on stage | P14, P8 |
| C3 — Compounding state | Three ramp gauges tick visibly during install arc | P2, P10 |
| C4 — Near-zero maintenance | Reactivity-as-data: admin confirms a worm-proposed Reactivity from chatter | P9, P10 (process map auto-emerges) |
| C5 — Metric-governed self-improvement | `composite_score` curve descends across Beats 1–9; per-scope keep-rate published | P1, P9 |
| C6 — Auditable governance | Beat 9 audit trail proves `proposed_by=worm`, `confirmed_by=human Person`; identity merge audit-complete | P6, P11 (MCP audit log mirror) |
| C7 — Domain specialization | Cursed CSV survives bronze→silver→gold; Snowflake column tags pass through to ledger classification | P4, P7 |
| C8 — Unprompted surface, prompted depth | Voice "Ask the worm" floater answers a KPI question with a citation | P13 |

And the Karpathy autoresearch loop must be visibly *applied to itself*: a proposed Reactivity confirmed live, plus a `experiment_lesson` ledger entry produced from a kept experiment. P9 + P15-as-seed.

---

## 2. Strategic frame — the value-showcase map

Every P-item is justified by (a) the council voice that asked for it, (b) the Triad criterion it makes visible, and (c) the demo-arc beat or act where it lands.

| # | Item | Council voice | Triad | Arc placement |
|---|---|---|---|---|
| P0 | Founder product walk | McKinney | meta | pre-wave |
| P1 | `composite_score` + per-scope keep-rate on `/research` | Karpathy + LeCun | C5 | F1 Beat 7, F2 A2 |
| P2 | Knowledge-ramp gauges wired to ledger projections | Murati | C3 | F1 Beats 1–9 |
| P3 | Stranger install-arc recording | Altman | C1, C8 | demo opener |
| P4 | `fixtures/cursed_finance_export.csv` in default cascade | Patil | C7 | F1 Beat 2 |
| P5 | `examples/connectors/parquet_local.py` + `CONTRIBUTING-A-CONNECTOR.md` + pip-installable conformance harness | Wang | C7 | F3 E1 |
| P6 | Identity merge property test | Amodei | C6 | F1 Beat 9 audit, F2 A4 |
| P7 | Snowflake governance-passthrough (column tags + masked-query refusal) | Ghodsi | C6, C7 | F2 A4 |
| P8 | OSS audit replay (`wormbase-tools replay` against frozen ledger reproduces KPI bit-for-bit) | Ghodsi | C2, C6 | F2 A5 |
| P9 | `experiment_lesson` ledger entry + learn step + per-scope lessons card | Karpathy | C4, C5 | F1 Beat 7, F2 A2 |
| P10 | Conversation→Process map (gold from chatter) on `/system-map` | Patil + canonical | C3, C4 | F1 Beat 5, F2 A3 |
| P11 | MCP external client live beat (Claude Desktop → worm via MCP) | Ghodsi | C6, C7, C8 | F2 A4 |
| P12 | First-knowing surface on `/research` | Altman | C1, C5 | F2 A2 |
| P13 | Voice "Ask the worm" live beat with cited ledger entry | Murati | C8 | F2 A3 |
| P14 | Wire-replay two-tenant determinism stage demo | McKinney | C2 | F2 A1 |

Plus seed-config additions (not P-items, but explicit prep):

- **Seed-S1.** Cursed-CSV chatter sequence on the seed Slack workspace — pre-scripted personas referencing "Q3 Rev" with the literal column name from the CSV, ensuring the phenomenon-gap detector fires at Beat 6 with concrete chatter to point at.
- **Seed-S2.** Recurring-action chatter sequence — seeded conversations of the form "every Friday we run X" repeating across days, ensuring `RecurringActionWithoutReactivityReactivity` fires at Beat 6.5 and proposes a Reactivity for admin confirmation. This is the meta-loop visible on stage.
- **Seed-S3.** Domain-touched chatter — pre-scripted messages in the finance channel that match Statement-to-Owner's predicate, ensuring Beat 9 fires with a real owner DM.
- **Seed-S4.** Repeating (asker, askee, topic) tuples across N≥3 days that trip the `RecurringQuestionProcessMapper` reactivity from P10, producing a process_map proposal at Beat 5.

Every seed sequence is checked into `tests/fixtures/install_arc_seed/*.jsonl` and replayed through wire-replay during the install arc. No flow-bypass — wire-replay is the only deterministic backstop, and the seed is the source of variation.

---

## 3. Scope — fifteen P-items, all load-bearing

| # | Item | Lens | Wall-clock | Mode | Wave |
|---|---|---|---|---|---|
| P0 | Founder product walk (non-admin, 1h, stopwatch) | McKinney | 60m | human | parallel-A |
| P1 | `composite_score` + keep-rate on `/research` | Karpathy + LeCun | 25m | agent | A |
| P2 | Knowledge-ramp gauges to ledger | Murati | 25m | agent | A |
| P3 | Stranger install-arc recording | Altman | 60m human + 25m agent prep | mixed | post-A |
| P4 | Cursed CSV fixture in default cascade | Patil | 25m | agent | A |
| P5 | Reference connector + conformance harness | Wang | 30m | agent | A |
| P6 | Identity merge property test | Amodei | 25m | agent | A |
| P7 | Snowflake governance-passthrough | Ghodsi | 30m | agent | A |
| P8 | OSS audit replay | Ghodsi | 30m | agent | A |
| P9 | `experiment_lesson` learn step | Karpathy | 30m | agent | A |
| P10 | Conversation→Process map | Patil + canonical | 30m | agent | A |
| P11 | MCP external client live beat | Ghodsi | 25m | agent | B |
| P12 | First-knowing surface | Altman | 25m | agent | B |
| P13 | Voice "Ask the worm" live beat | Murati | 25m | agent | B |
| P14 | Wire-replay two-tenant stage demo | McKinney | 25m | agent | B |
| Seed | S1–S4 fixture seeds for install arc | Patil + canonical | 25m | agent | B |

**Wave A** = P1, P2, P4, P5, P6, P7, P8, P9, P10 — nine parallel agents in one orchestrator message. Wall-clock target: ≤30 min. P0 runs in parallel as a human task.

**Wave B** = P11, P12, P13, P14, Seed-S1–S4 — five parallel agents. Wall-clock target: ≤30 min.

**Sequential after Wave A + B:** P3 (stranger recording) — depends on P4 (cursed CSV wired) and Seed-S1–S4 (chatter wired) being merged.

Total wall-clock from PRD-handoff to demo-ready: ~3–4 hours including review, with Ricardo running P0 in parallel during Wave A and the stranger session timed for ~T+90.

---

## 4. Out of scope

Explicitly out of scope for this 24-hour window:

- New tabs / new pages beyond what P1, P2, P10, P12 add to existing `/research`, `/dashboard`, `/system-map`
- Net-new connectors beyond P5's `parquet_local` reference and P7's Snowflake passthrough extension
- New voice-agent capabilities beyond what P13 wires for the live beat
- Net-new reactivities beyond what P9 (learn-step extractor) and P10 (process_mapper) add
- Retag past v0.4.0-resilient mid-wave — the demo runs on v0.4.0-resilient + this wave's commits + a final `demo-day` tag at sign-off
- Performance optimization (8-min F1 budget is comfortable)
- Refactoring beyond cleanup-checklist enforcement
- Polish-for-polish (visual baselines are already regenerated against rich seed)

If a sub-agent finds itself reaching for something on this list, halt and surface to the orchestrator.

---

## 5. The demo arc — three acts

Total demo runtime: ~20–22 min. Every minute earns its keep against a Triad criterion.

### Act I — F1 install arc (8 min, 9 beats)

Same 9-beat structure as v1, with seed sequences and new surfaces named.

| Beat | t (s) | What happens | Surface alive | Triad |
|---|---|---|---|---|
| 0 | 0–30 | `make tutorial` boot, OAuth handshake, tenant created, installer Person + Install row written | `/login`, `/welcome` | C1 |
| 1 | 30–60 | Worm posted in workspace, first ingest event lands; ramp gauge "conversational" ticks | `/channels`, `/trace`, `/dashboard` | C1, C3 |
| 2 | 60–120 | Default local source connects (cursed CSV); bronze cascade visible; ramp gauge "ontology" begins ticking | `/sources`, `/dashboard` | C7, C3 |
| 3 | 120–180 | First KPI proposed from cursed CSV; first concept emitted; ramp gauge "relational" ticks | `/kpis`, `/dashboard` | C5, C7 |
| 4 | 180–240 | Worm proposes a Person from chatter (Seed-S3 personas); admin confirms | `/people` | C1 |
| 5 | 240–300 | Domain ownership proposed; admin confirms; **process_map proposed from Seed-S4 chatter** (P10) | `/domains`, `/people`, `/system-map` | C3, C4 |
| 6 | 300–360 | Phenomenon-gap detector fires for unknown KPI from Seed-S1 chatter | `/reactivities`, `/kpis` | C5 |
| 6.5 | 360–380 | **Meta-Reactivity:** `RecurringActionWithoutReactivityReactivity` fires from Seed-S2 chatter; admin confirms a worm-proposed Reactivity | `/reactivities` | C4 |
| 7 | 380–420 | Autoresearch fires at Person scope; experiment proposed; **`composite_score` curve ticks down on `/research`** (P1); **first `experiment_lesson` extracted** (P9) | `/research` (Mine tab), `/research` Lessons card | C5 |
| 8 | 420–450 | Reactivity fires the Statement-to-Owner DM (real DM in real Slack workspace) | `/people/[id]` Resource Conversations card, channel DM | C1 |
| 9 | 450–480 | Capstone — admin sees full audit trail end-to-end on `/trace`; ramp gauges have all moved | `/trace`, `/dashboard` | C2, C6 |

### Act II — F2 live answers (6 min, 5 stage moments)

This act answers Q1, Q2, Q4, Q5, Q9 from the council — the demo's intellectual climax.

| Moment | Time | Action | Surface | Triad | P-item |
|---|---|---|---|---|---|
| A1 — Determinism on stage | 1 min | Spin two fresh tenants; replay the same `install_arc.jsonl` JSONL into both via `wormbase-tools wire-replay`; diff terminal ledger hashes — must match byte-for-byte | terminal + `/trace` on both tenants | C2 | P14 |
| A2 — What the worm knew first | 1 min | Open `/research` First-Knowing tab; click any un-confirmed phenomenon; land on the InfraEvent that triggered it; show the chatter context | `/research` First-Knowing | C1, C5 | P12, P1 |
| A3 — Voice + cited answer | 1 min | Use voice floater: "What's the current value of Q3 net revenue?" Worm answers; click the cited ledger entry; land on the projection trace | floater + `/trace` | C8 | P13 |
| A4 — MCP external client | 2 min | In Claude Desktop (with worm's MCP server installed via `wormbase-tools mcp connect`), query "show KPIs and owners in finance domain"; then mutate "propose a KPI named 2026 Q4 ARR target"; watch dashboard `/kpis` update; show audit trail confirms `proposed_by=mcp_client`, `confirmed_by` empty until human acts; then test masked-column refusal via Snowflake passthrough (P7) | Claude Desktop + `/kpis` + `/trace` | C6, C7, C8 | P11, P7, P6 |
| A5 — OSS audit replay | 1 min | From a clean venv outside the running stack, `pip install wormbase-tools && wormbase-tools replay snapshot.jsonl --to kpi_q3_revenue`; output matches the live tenant's KPI bit-for-bit | terminal + `/kpis` | C2, C6 | P8 |

### Act III — F3 ecosystem (5–7 min, live coding)

This act answers Q7. Live extensibility — the OSS surface invites contribution, not just claims to.

| Moment | Time | Action | Surface | Triad | P-item |
|---|---|---|---|---|---|
| E1 — Live connector | 5 min | Clone `wormbase-tools` checkout; copy `examples/connectors/parquet_local.py` to `examples/connectors/hackernews.py`; modify ~20 lines to hit Hacker News firehose API; run `pytest --plugins wormbase_tools_test --connector examples.connectors.hackernews:HackerNewsConnector`; conformance harness green | terminal + connector registry | C7 | P5 |
| E2 — New connector lands | 1 min | Register in dashboard via `/sources/new`; ingest one row; show on `/trace` | `/sources/new`, `/trace` | C7 | P5 |

### Closing — sign-off (1 min)

Tag `demo-day` on stage. Recite the closing line: *"The substrate is shipped, the loop is measured, the audit is reproducible, the contributor is welcomed. WormBase is institutional AI for the data function."*

---

## 6. Acceptance criteria — the nine live questions

Each Q maps to a specific Act/beat. The demo passes if and only if all nine can be answered live, on stage, without a developer at the keyboard.

| # | Council voice | Question | Pass condition | Arc placement |
|---|---|---|---|---|
| Q1 | Altman | "What does the worm know that the org's CDO doesn't, with the ledger entry where it knew it first?" | First-Knowing tab on `/research` shows ≥3 un-confirmed phenomena from the install arc, each clickable to its source InfraEvent | F2 A2 |
| Q2 | LeCun | "Run the same wire twice — show byte-identical ledger hash AND byte-identical Statement-to-Owner DM." | Two-tenant wire-replay produces matching ledger hashes; recorded DM payloads identical | F2 A1 |
| Q3 | Murati | "Click any pixel on a ramp gauge, end at the InfraEvent in <10s, no developer keyboard." | `/dashboard` gauges → `/trace` filter pre-set → InfraEvent visible in 3 clicks | F1 Beats 1–9 |
| Q4 | Amodei | "Beat 9 audit trail — prove the worm cannot author its own confirmation." | `/trace` filter on Beat 9's DM fire shows `proposed_by=worm`, `confirmed_by=human Person`. Property test (P6) demonstrates merge invariants. | F1 Beat 9, F2 A4 |
| Q5 | Ghodsi | "OSS `wormbase-tools` against a frozen ledger snapshot reproduces yesterday's KPI bit-for-bit." | `wormbase-tools replay snapshot.jsonl --to <kpi_id>` from outside the running stack matches the live KPI value | F2 A5 |
| Q6 | Patil | "Stranger + cursed CSV + Slack — what breaks first?" | Stranger recording (P3) shows install arc completing in ≤8 min on cursed CSV without developer intervention | demo opener |
| Q7 | Wang | "Write a connector to a public API live in 10 min, conformance harness passes, registry picks it up." | Live-coded connector against P5's reference; `pytest -k test_my_connector_conformance` green; new connector registered in dashboard | F3 E1, E2 |
| Q8 | McKinney | "Wire-replay t=0→460s on two clean tenants — show hashes match." | Two fresh tenants, same JSONL replay, same final ledger hash on stage in <2 min total | F2 A1 |
| Q9 | Karpathy | "Show `composite_score` curve over last 100 entries — name the reactivity that moved it most." | `/research` shows the curve; click any inflection → trace of contributing ledger entries; one reactivity surfaces as top contributor; one `experiment_lesson` entry visible per scope | F1 Beat 7, F2 A2 |

If any of Q1–Q9 cannot be answered live by 2026-04-30 09:00, that question is the only thing that matters for the day. Cut everything else.

---

## 7. Per-item PRDs

### P0 — Founder product walk

**Owner:** Ricardo, solo. No agent.
**Why:** McKinney's read is that the orchestrator (you) has been ship-blind. One hour as a non-admin Person, stopwatch in hand, no code, surfaces every chrome-lie, silent-empty-state, and role-leak that would kill a stranger. This is the input for items P2 and P4 and the seed for the cleanup-checklist sweep.

**Constraints:**
- Use a fresh tenant. `make tutorial` from a clean clone.
- Sign in as a `tenancy.member` Person, not `tenancy.admin`. Use `/people` to confirm role view.
- Touch every tab in nav order. Time each one. Note silent panels.
- No keyboard shortcuts, no terminal during the walk.

**Output:** `docs/superpowers/notes/2026-04-29-product-walk-defects.md`. Format: one defect per line, `<page> · <symptom> · <severity {blocker | high | medium}>`.

**Definition of done:** ≥10 defects logged, each scoped to a single tab/page/component, each independently dispatchable as a 25-minute agent task.

---

### P1 — `composite_score` + per-scope keep-rate on `/research`

**Owner:** Single agent.
**Why:** Karpathy and LeCun converge: without a single scalar going monotonically down, the loop is a research project. LeCun specifically asks for **keep-rate per scope per night with a baseline week** — D022 instrument-system instantiated. Both land on `/research`.

**Contract — composite_score:**

New ledger projection: `composite_score(tenant_id, ledger_height) -> float`.

Inputs (all read from the ledger, never derived from anywhere else):

- **Gate-fire precision:** ratio of `gate_fire` entries upheld by subsequent `propose → confirmed` vs `propose → rejected` over the trailing 7-day window per scope.
- **Propose→keep ratio:** for `experiment_proposed` entries, the fraction landing as `experiment_kept` vs `experiment_discarded` in the window.
- **Ramp-gauge delta:** sum of monotonic increments on the three ramp axes (ontology, conversational, relational) in the window.
- **Reactivity confirm rate:** for `reactivity_proposed` entries, fraction reaching `reactivity_confirmed` within the window.

Weights: equal (0.25 each) for v1. Configurable via a `composite_score_weights` ledger entry — admin-emit only.

Composite normalized to `[0, 1]`. Display as loss-style: `1 - normalized_score`. The demo wants it descending across Beats 1–9.

**Contract — per-scope keep-rate:**

New nightly job: `keep_rate_publisher`. Computes keep-rate per scope (Person/Team/Company) over the trailing day. Appends `metrics_keep_rate_published` ledger entry with `{scope, day, kept, total, ratio}`. Idempotent — re-running for the same day is a no-op.

`/research` shows a "Baseline" card per scope with a 7-day chart. If insufficient real data, a synthetic baseline week is generated (transparently tagged "synthetic baseline" — no demo seam, the tag is structural).

**Files:**

- `packages/worm-core/src/wormbase/projections/composite_score.py`
- `packages/worm-core/src/wormbase/projections/__init__.py` — register
- `packages/worm-core/src/wormbase/jobs/keep_rate_publisher.py`
- `packages/worm-core/src/wormbase/ledger/entries/metrics_keep_rate_published.py`
- `apps/dashboard/app/research/components/CompositeScoreCard.tsx`
- `apps/dashboard/app/research/components/KeepRateChart.tsx`
- `apps/dashboard/app/research/page.tsx` — mount both
- `apps/dashboard/app/api/research/composite_score/route.ts`
- `apps/dashboard/app/api/research/keep_rate/route.ts`

**Tests:**

- `tests/worm_core/test_composite_score_projection.py` — replay determinism, ≥3 cases.
- `tests/worm_core/test_keep_rate_publisher.py` — idempotency, replay determinism.
- `tests/dashboard/test_research_metrics.spec.ts` — Playwright: page renders, curve has ≥9 points after install arc, click on point opens trace filter, keep-rate chart renders per scope.

**Definition of done:**
- Composite curve visible on `/research`; ticks live during install arc.
- Keep-rate chart visible per scope; baseline week visibly tagged if synthetic.
- Each composite point clickable; click opens `/trace` filtered to contributing ledger range.
- Top-contributing-reactivity badge visible per point.
- Tests green in CI.

**Out of scope for P1:** the learn step itself ships in P9.

---

### P2 — Knowledge-ramp gauges wired to live ledger projections

**Owner:** Single agent.
**Why:** Murati: the substrate moves but the dashboard's first impression doesn't. A non-technical pilot lands on `/dashboard` and the ramp gauges sit at zero through the whole arc.

**Contract:**

Three gauges minimum on `/dashboard`. Each is an integer count over the ledger:

| Gauge | Ledger source | Increment trigger |
|---|---|---|
| Ontology | `concept_emitted` entries | Worm emits a new concept or definition |
| Conversational | `chat_received` entries | Wire delivers a normalized message |
| Relational | `kpi_node_added` + `kpi_edge_added` entries | KPI tree grows |

Each gauge: integer count + sparkline of last 60 minutes (or 100 entries, whichever shorter).

Click any gauge → `/trace` opens, filter pre-set to that entry kind, scrolled to most recent contributing entry. Time-to-trace must be <10s on a stock laptop. (Q3 acceptance.)

**Files:**

- `packages/worm-core/src/wormbase/projections/knowledge_ramp.py` — three projections
- `apps/dashboard/app/dashboard/components/RampGauge.tsx`
- `apps/dashboard/app/dashboard/page.tsx` — mount three gauges
- `apps/dashboard/app/api/dashboard/ramp/route.ts`

**Tests:**

- `tests/worm_core/test_knowledge_ramp_projection.py` — determinism + empty-state handling
- `tests/dashboard/test_dashboard_ramp_gauge.spec.ts` — Playwright: render, tick during simulated wire input, click-through to trace

**Empty-state rule:** if a projection returns `0`, render `0` honestly. Do not fall back to a fixture. Every gauge carries a visible `0` plus a hint string when empty.

**Definition of done:**
- Three gauges visible, ticking during install arc.
- Click-through to `/trace` works in <10s without developer keyboard.
- N2 placeholder gate green.
- Tests green in CI.

---

### P3 — Stranger install-arc recording

**Owner:** Ricardo + one agent for prep.
**Why:** Altman: 2,725 tests + zero strangers = research project. The recording is the demo opener and the empirical D020 test.

**Constraints:**
- Real Slack workspace, fresh, never-touched-by-WormBase.
- One human who has never run `make tutorial` or seen the dashboard.
- Unedited from `git clone` to Beat 9's Statement-to-Owner DM landing.
- Ricardo is in the room but does not touch the keyboard. The stranger drives.
- Time the run with a stopwatch on screen.

**Agent prep task:** before the human arrives, an agent verifies:
- `make tutorial` runs cleanly on a fresh checkout in the agent's worktree.
- All eleven day-one connectors load without errors (`pytest -k test_connector_init`).
- The cursed CSV (P4) is wired in as the default local source.
- Seed-S1–S4 chatter sequences are wired and ready to fire.
- The voice agent is in graceful-degrade mode (no live API key required for the recording).
- The MCP tunnel URL is reachable.

**Failure modes:**
- Install >8 min: log the bottleneck, fix it, re-record. Do not extend F1 budget.
- Beat fails mid-arc: orchestrator's auto-recovery should retry; if not, log the gap, fix, re-record.
- Stranger gets confused: that screen goes on the P0 defect list. Fix tonight.

**Output:**
- Recording: `docs/superpowers/notes/2026-04-29-stranger-recording.mp4`
- Time-stamped log: `docs/superpowers/notes/2026-04-29-stranger-log.md`. One row per beat with wall-clock and any incident.

**Definition of done:** Clean recording becomes the demo opener; or all incidents logged and fixed for the next attempt.

---

### P4 — `fixtures/cursed_finance_export.csv` in default cascade

**Owner:** Single agent.
**Why:** Patil: D020 demands real messy data. A practicing DS spots a clean fixture in 30 seconds.

**Contract — the file must contain at minimum:**

- Encoding: Windows-1252 (not UTF-8). Connector must detect this.
- Two duplicate header rows at the top (frequent Excel-export sin).
- Column literally named `Q3 Rev (final)(USE THIS)` — parens, parenthetical, capitalization preserved. (Also referenced by Seed-S1 chatter so phenomenon-gap detector matches.)
- One numeric column containing both `#REF!` and `#N/A` strings.
- One missing-value sentinel column where missing is `-9999`.
- One timezone-naïve datetime column adjacent to a tz-aware ISO-8601 column with the same logical meaning.
- One column with PII in the column name (`customer_email`) so classification heuristic flags it.
- ≥200 rows so silver layer has enough mass to surface a KPI proposal.

**Files:**
- `fixtures/cursed_finance_export.csv`
- `fixtures/cursed_finance_export.fixture.json` — metadata: expected classification, KPI proposal, silver normalizations
- `packages/worm-core/src/wormbase/onboarding/default_local_source.py` — wire fixture as default

**Tests:**

- `tests/worm_core/test_cursed_csv_connector.py`:
  - `csv_local` connector profiles file without crashing
  - Encoding detected as Windows-1252
  - Both header rows surfaced; deduplication is silver-layer
  - Sentinel `-9999` flagged in anomaly list
  - PII column flagged in classification_hints

- `tests/integration/test_cursed_csv_pipeline.py`:
  - Full bronze→silver→gold pipeline runs
  - Silver normalizes `Q3 Rev (final)(USE THIS)` to a stable column id
  - Gold proposes KPI using rev column
  - Pipeline survives in <30s

**Definition of done:** File committed; default local source resolves to it; pipeline survives on camera during P3; tests green.

---

### P5 — Reference connector + contributing doc + pip-installable conformance

**Owner:** Single agent.
**Why:** Wang: the Connector Protocol is the right shape, but no Python data person can land in it from a Jupyter cell. The OSS surface is decoration until contributors arrive.

**Contract — three deliverables:**

1. **`examples/connectors/parquet_local.py`** — ~60 LOC, the canonical reference:
   - Implements `Connector` Protocol against local Parquet files
   - Covers all five capabilities (`discover`, `profile`, `sample`, `watch`, `authenticate`)
   - Uses only `pyarrow` + stdlib — no WormBase-internal deps
   - Copy-pasteable into a Jupyter cell and runnable

2. **`examples/CONTRIBUTING-A-CONNECTOR.md`** — literate walkthrough:
   - Tells contributor what each Protocol method is for in plain language
   - Walks them through writing `parquet_local.py` line by line
   - Ends with conformance harness invocation
   - 500–1000 lines is fine if it earns its keep

3. **Pip-installable conformance harness** — `wormbase-tools-test`:
   - New pyproject in `packages/wormbase-tools-test/`
   - Re-exports the 6 conformance invariants from `tests/worm_core/test_connector_conformance.py` (W6.A4) as a public API
   - Installable standalone: `pip install wormbase-tools-test`
   - Usage: `pytest --plugins wormbase_tools_test --connector my_module:MyConnector`

**Tests:**

- `tests/examples/test_parquet_local_connector.py` — reference passes conformance
- `tests/integration/test_pip_installable_harness.py` — `pip install` from a sibling worktree, run conformance against a stub connector, green

**Definition of done:** Three deliverables committed; reference passes conformance; harness `pip install`-able from clean venv outside monorepo; walkthrough reviewed by second agent for "could a Tuesday-morning Python data person follow this?" cold.

---

### P6 — Identity merge property test

**Owner:** Single agent.
**Why:** Amodei: the hash chain is fuzzed, but identity merge — highest-blast-radius admin action — is not. Regulated buyers will look here first.

**Contract:**

Hypothesis-driven property test. For any sequence of `link → unlink → link` operations across N platforms (N ∈ [1, 8]), assert:

1. **Reconstructable confirmation chain.** Resulting `Person.confirmed_by` chain fully reconstructable from ledger by replaying `emit_identity_linked` and `emit_identity_unlinked` entries in order.
2. **No orphan PersonIdentity rows.** Every `PersonIdentity` row references a current `Person` or has a corresponding `emit_identity_unlinked` ledger entry.
3. **Role-grant survival under merge.** `emit_role_assigned`, `emit_domain_role_assigned`, `emit_resource_role_assigned` survive merge with original `granted_by` attribution preserved. Merge does not silently transfer a grant without a `emit_role_reassigned` entry.
4. **Determinism under replay.** Same operation sequence on a fresh tenant yields byte-identical ledger output, identical `PersonIdentity` rows, identical role-grant projections.

**Files:**
- `tests/worm_core/test_identity_merge_property.py` — Hypothesis test, ≥51 trials per invariant (matching W6.A1 cadence)

**Definition of done:** Test runs in <5s, green in CI, added to W6 property suite registry, counterexamples (if any) trigger a fix in the same PR — no `@pytest.mark.skip`.

---

### P7 — Snowflake governance-passthrough (undeferred from v1)

**Owner:** Single agent.
**Why:** Ghodsi: warehouse-native governance interop is the closer for the enterprise CDO room. Without it, the trust layer ends at the WormBase ledger boundary and procurement kills the deal.

**Contract:**

Demo path:
1. Connect Snowflake via OAuth in the connector picker.
2. Ingest a Snowflake table with column tags preserved end-to-end (Snowflake `COLUMN.TAG` → WormBase `Resource.classification` + `column_tags` metadata).
3. One masked-column query refused at the gate, with a `gate_fire` ledger entry showing the policy that refused it and the trace path back to the column tag.
4. One on-screen click: from the refused query in `/trace`, jump to `/sources/<id>` showing the column tag that drove the refusal.

**Files:**
- `packages/connectors/snowflake/governance_passthrough.py` — extension to existing Snowflake connector for tag pass-through
- `packages/worm-core/src/wormbase/policies/masked_column_refusal.py` — the gate
- `tests/connectors/test_snowflake_governance_passthrough.py` — integration test against Snowflake mock (the only mock acceptable in this PRD; documented in test docstring)

**Definition of done:** Demo path runs end-to-end on real Snowflake instance; refusal visible on `/trace` with policy name and column tag; tests green.

---

### P8 — OSS audit replay

**Owner:** Single agent.
**Why:** Ghodsi Q5: an auditor must be able to run `wormbase-tools` against a frozen ledger snapshot and reproduce yesterday's KPI bit-for-bit, **without your hosted plane**. If the OSS adapter can't replay, the trust layer is rented, not owned. This is C2 + C6 simultaneously.

**Contract:**

`wormbase-tools` exposes a CLI: `wormbase-tools replay <snapshot.jsonl> --tenant <id> --to <kpi_id>`.

Behavior:
- Reads a JSONL ledger snapshot file (the same format wire-replay produces).
- Reconstructs all relevant projections in pure Python — no Postgres, no dashboard, no cloudflared, no inference router required.
- Outputs a KPI value byte-identical to the live tenant's value at the snapshot's terminal hash.
- Exits 0 on success with the value on stdout; exits 1 on hash mismatch with the diff on stderr.
- Total runtime ≤10s on stock laptop for a 1000-entry snapshot.

**Files:**

- `packages/wormbase-tools/src/wormbase_tools/replay.py` — CLI command
- `packages/wormbase-tools/src/wormbase_tools/projections/` — pure-Python projection re-imports (vendored from worm-core where necessary, with a clear seam)
- `packages/wormbase-tools/src/wormbase_tools/cli.py` — command registration
- `tests/integration/test_oss_audit_replay.py` — end-to-end: snapshot live tenant → replay externally → KPI matches
- `docs/oss-audit-replay.md` — auditor-facing usage guide

**Tests:**
- Byte-equal KPI value across live and replay (≥3 KPIs).
- Replay completes in <10s on stock laptop.
- Replay refuses to run if snapshot terminal hash is missing or malformed (fail-closed).
- Replay produces a deterministic provenance trail: which ledger entries contributed to which KPI value.

**Definition of done:**
- `pip install wormbase-tools` from a clean venv; `wormbase-tools replay snapshot.jsonl --to kpi_q3_revenue` returns the same number `/kpis` shows on the live tenant.
- Runs without booting Postgres, dashboard, cloudflared, or any hosted service.
- Auditor doc reviewed by second agent for "could a third-party auditor follow this without context?"

---

### P9 — `experiment_lesson` learn step

**Owner:** Single agent.
**Why:** Karpathy: across sessions 009, 011, and 012, the missing learn step is the consistent gap. Without "what did the keep teach the next propose?" the loop is parallel pipelines, not nested optimization. This closes Karpathy's 84% → higher.

**Contract:**

New ledger entry kind: `experiment_lesson` with payload:
```
{
  "prior_keep_id": <experiment_kept entry id>,
  "scope": "person" | "team" | "company",
  "lesson_text": str,                    # human-readable
  "lesson_features": dict[str, str],     # structured: predicates/conditions/topics that drove the keep
  "applied_to_proposer": str,            # which proposer module reads this
  "applied_at": <ledger height>          # when next propose used this lesson
}
```

Mechanism:
1. When `experiment_kept` fires, the harness extracts a lesson — what features (predicate, condition, topic, scope) correlated with the keep vs adjacent discards.
2. Lesson written to ledger as `experiment_lesson`.
3. Next `experiment_proposed` for the same scope reads recent `experiment_lesson` entries (trailing 7 days) and includes them in its rationale string and feature weighting.
4. The `applied_at` field is filled in when the lesson is first used — closes the loop empirically.

`/research` gets a "Lessons" card per scope showing the last 5 `experiment_lesson` entries; click any → trace.

**Files:**

- `packages/worm-core/src/wormbase/ledger/entries/experiment_lesson.py`
- `packages/worm-core/src/wormbase/loop/learn.py` — extraction logic
- `packages/worm-core/src/wormbase/loop/propose.py` — modify to read lessons
- `packages/worm-core/src/wormbase/projections/lessons_per_scope.py`
- `apps/dashboard/app/research/components/LessonsCard.tsx`
- `apps/dashboard/app/api/research/lessons/route.ts`

**Tests:**
- `tests/worm_core/test_experiment_lesson_extraction.py` — kept experiment produces lesson entry; structure matches spec.
- `tests/worm_core/test_lesson_application.py` — next proposer reads recent lessons; applied_at filled in correctly.
- `tests/worm_core/test_lesson_replay_determinism.py` — same ledger → same lessons → same applied_at.
- `tests/dashboard/test_lessons_card.spec.ts` — Playwright: card renders, click-through to trace.

**Definition of done:**
- During install arc Beat 7, an `experiment_lesson` is extracted and visible on `/research`.
- Subsequent `experiment_proposed` shows the lesson in its rationale.
- N2 gate green; tests green.

---

### P10 — Conversation→Process map (gold from chatter)

**Owner:** Single agent.
**Why:** Patil + canonical framework `CLAUDE.md` § "Conversations as a first-class data source": the conversation lake produces gold artifacts (process maps) from minute-one of `@connect`. Currently we have bronze (`chat_received`) and silver (topic threading) but no gold beat in the demo arc.

**Contract:**

New gold artifact type: `process_map` — emitted via `emit_data_product_*` with payload:
```
{
  "nodes": [{ "actor_person_id": ..., "role_in_map": "asker" | "askee" | ... }],
  "edges": [{ "from": person_id, "to": person_id, "topic": str, "frequency": int, "first_seen": ts, "last_seen": ts }],
  "window_start": ts,
  "window_end": ts,
  "confidence": float
}
```

New reactivity: `RecurringQuestionProcessMapper`:
- Predicate: `EntryKind=chat_received & HasTopic & InThread`.
- Condition: same `(asker_person_id, askee_person_id, topic)` recurring ≥3 times in trailing 14 days; threshold cross fires.
- Action: emit `data_product_proposed(kind=process_map, payload=...)` for admin confirm.
- Per-tenant per-day budget: 5.

`/system-map` gets a new "Conversation Process Maps" lens: lists all `process_map` data products, click → graph view.

**Files:**

- `packages/worm-core/src/wormbase/reactivities/process_mapper.py`
- `packages/worm-core/src/wormbase/data_products/process_map.py`
- `packages/worm-core/src/wormbase/projections/process_maps.py`
- `apps/dashboard/app/system-map/components/ConversationProcessMaps.tsx`
- `apps/dashboard/app/api/system-map/process-maps/route.ts`

**Seed dependency:** Seed-S4 chatter sequences must be wired in Wave B to ensure the reactivity fires during install arc Beat 5.

**Tests:**
- `tests/worm_core/test_process_mapper_reactivity.py` — fires on threshold cross; respects budget and recency.
- `tests/integration/test_process_map_e2e.py` — chat_received → topic → process_map_proposed → admin confirms → published as data product → visible on /system-map.
- `tests/dashboard/test_system_map_process_maps.spec.ts` — Playwright: page renders, graph view interactive.

**Definition of done:**
- Beat 5 of install arc produces a `process_map` proposal from Seed-S4 chatter; admin confirms it; `/system-map` shows it.
- N2 gate green; tests green.

---

### P11 — MCP external client live beat

**Owner:** Single agent.
**Why:** Ghodsi: "MCP-native institutional AI" is the headline. Without showing an external MCP client (Claude Desktop, a Python MCP client) talking to the worm, the MCP claim is rhetorical.

**Contract:**

The MCP server must expose at minimum:

- **Read tools:** `list_kpis`, `list_persons`, `list_decisions`, `list_processes`, `list_data_products`, `list_reactivities`, `read_trace`.
- **Write tools (gate-protected):** `propose_kpi`, `propose_decision`, `propose_process`, `confirm_proposal`.
- **Audit tools:** `read_audit_trail(entry_id)` — returns `proposed_by`, `confirmed_by`, `confirmed_at`, contributing ledger range.

Stage script (kept in `docs/superpowers/notes/2026-04-29-mcp-demo-script.md`):
1. In Claude Desktop with WormBase MCP server installed via `wormbase-tools mcp connect <tunnel-url>`:
2. Query: "show KPIs and owners in the finance domain" → MCP returns structured JSON with KPI rows.
3. Mutation: "propose a KPI named 2026 Q4 ARR target" → MCP writes `kpi_proposed` ledger entry.
4. Watch dashboard `/kpis` update in real time (already supports SSE).
5. Audit query: "show audit trail for the KPI you just proposed" → MCP returns `proposed_by=mcp_client(name=Claude Desktop)`, `confirmed_by=null` (until human acts).
6. Test masked-column refusal via Snowflake passthrough (P7): "select customer_email from snowflake.customers" → gate refuses, MCP returns refusal with policy name.

**Files:**
- `apps/mcp-server/` — verify all read+write tools shipped
- `apps/mcp-server/src/tools/audit.ts` (or .py if Python-based) — `read_audit_trail` tool
- `docs/superpowers/notes/2026-04-29-mcp-demo-script.md` — exact phrases to query
- `tests/integration/test_mcp_external_client.py` — automation: spin up MCP server, run sample queries, assert shapes

**Tests:**
- All read tools return correct shapes for a seeded tenant.
- All write tools produce ledger entries with correct `proposed_by` attribution.
- Audit tool returns full attribution chain.
- Refused queries surface policy name + column tag in the error payload.

**Definition of done:**
- MCP server up on tunnel URL during demo.
- Stage script reviewed and rehearsed.
- External Claude Desktop session can complete all six steps in <2 min.

---

### P12 — First-knowing surface on `/research`

**Owner:** Single agent.
**Why:** Altman Q1: "What does the worm know that the org's CDO doesn't, with the ledger entry where it knew it first?" This is the institutional-AI wedge made visible.

**Contract:**

`/research` gets a new "First-Knowing" tab. Lists phenomena the worm has detected that the org has NOT yet confirmed — i.e. `proposed_by=worm` with `confirmed_by IS NULL`.

Each row:
- Phenomenon kind (KPI gap | Domain gap | Process gap | Reactivity gap | Person gap)
- One-line summary
- `first_detected_at` (ledger height + wall-clock)
- Click → opens the InfraEvent that triggered the detection + the chatter context (3 messages of context above and below)

Filter chips: phenomenon-kind, scope (mine/team/company), first_detected_in_last (1h, 24h, 7d).

**Files:**
- `packages/worm-core/src/wormbase/projections/first_knowings.py`
- `apps/dashboard/app/research/components/FirstKnowingsTab.tsx`
- `apps/dashboard/app/research/page.tsx` — mount tab
- `apps/dashboard/app/api/research/first-knowings/route.ts`

**Tests:**
- `tests/worm_core/test_first_knowings_projection.py` — returns un-confirmed proposals; filter logic correct.
- `tests/dashboard/test_first_knowings_tab.spec.ts` — Playwright: tab renders, filter chips work, click-through to InfraEvent + chatter context.

**Definition of done:**
- After install arc, First-Knowing tab shows ≥3 detections from cursed CSV (P4) + Seed-S1/S2/S4 chatter.
- Click-through to source InfraEvent + chatter context works in <10s.
- N2 gate green; tests green.

---

### P13 — Voice "Ask the worm" live beat

**Owner:** Single agent.
**Why:** Murati: voice floater is shipped but graceful-degrade-by-default risks the live beat falling flat. C8 is "unprompted surface, prompted depth" — the worm answers when asked.

**Contract:**

Floater accepts a voice query: "What's the current value of Q3 net revenue?"

Pipeline:
1. Voice → STT (Whisper or platform-equivalent).
2. Text → MCP query routed through worm's MCP server (P11) to `read_kpi(name="q3 net revenue")`.
3. MCP response → response text including the KPI value AND the ledger entry id of the most recent computation.
4. Response text → TTS (or rendered text if API key absent).
5. Citation rendered as a clickable link → opens `/trace` filtered to that ledger entry.

If voice API key is absent on the demo machine, fallback is text input with the same pipeline, with a visible "voice unavailable, text input" banner. No silent degradation.

**Files:**
- `apps/dashboard/app/components/AskTheWorm.tsx` — verify and harden
- `packages/voice-agent/src/asktheworm/pipeline.ts` (or .py)
- `packages/voice-agent/src/asktheworm/citation.ts` — citation rendering
- `tests/integration/test_ask_the_worm_pipeline.py` — STT-stub → MCP → TTS-stub round trip
- `tests/dashboard/test_ask_the_worm_floater.spec.ts` — Playwright: floater renders, text-fallback path works, citation clickable

**Definition of done:**
- On demo machine with API key: ask the worm a KPI question, hear the answer, click the citation, land on the ledger entry.
- On demo machine without API key: text-input fallback works with the same path; banner visible.
- N2 gate green; tests green.

---

### P14 — Wire-replay two-tenant determinism stage demo

**Owner:** Single agent.
**Why:** McKinney Q8: "Wire-replay t=0→460s on two clean tenants — show hashes match on stage." This is the single moment that carries the whole determinism thesis. C2 made tactile.

**Contract:**

A scripted stage demo: `make stage-replay-demo`. Spins up two fresh tenants (in parallel via `docker compose --project-name tenant_a` and `docker compose --project-name tenant_b`), replays the same recorded `install_arc.jsonl` through `wormbase-tools wire-replay` into both, diffs terminal ledger hashes, exits 0 if match.

Output: a single TTY frame showing both terminal hashes side by side, large enough to read from the back row.

**Files:**
- `packages/wormbase-tools/src/wormbase_tools/wire_replay.py` — verify completeness
- `tests/fixtures/install_arc.jsonl` — the canonical recorded arc (sourced from P3 stranger run; if P3 not yet recorded, use synthetic-but-realistic recording from sim-harness)
- `scripts/stage_replay_demo.sh` — one-command stage demo
- `apps/dashboard/app/api/stage-replay/route.ts` — optional dashboard wrapper for slick presentation

**Tests:**
- `tests/integration/test_stage_replay.py` — script runs, two tenants spin, hashes match, exit 0.
- Script runs in <2 min on stock laptop.

**Definition of done:**
- `make stage-replay-demo` works from clean repo on demo machine.
- Stage output is readable from a presentation distance.
- Tests green.

---

### Seed-S1–S4 — Install-arc seed sequences

**Owner:** Single agent (Wave B).
**Why:** The install arc shows variation only if the seed chatter, sources, and persona behavior trigger the right reactivities at the right beats. Without curated seeds, Beat 5 (process map), Beat 6 (phenomenon-gap), Beat 6.5 (meta-Reactivity), and Beat 8 (Statement-to-Owner) won't fire on time.

**Contract:**

Four JSONL seed files in `tests/fixtures/install_arc_seed/`:

- **S1 — `cursed_csv_chatter.jsonl`:** Pre-scripted personas referencing "Q3 Rev" with the literal column name from the cursed CSV. ~10 messages over Beats 5–6, ensuring phenomenon-gap detector fires at Beat 6 with concrete chatter to point at.
- **S2 — `recurring_action_chatter.jsonl`:** Seeded conversations of the form "every Friday we run the revenue close" repeating across 3 simulated days. Triggers `RecurringActionWithoutReactivityReactivity` at Beat 6.5 → admin confirms a worm-proposed Reactivity (the meta-loop visible on stage).
- **S3 — `domain_touched_chatter.jsonl`:** Pre-scripted finance-channel messages matching Statement-to-Owner's predicate. Ensures Beat 8 fires with a real owner DM in real Slack.
- **S4 — `recurring_question_chatter.jsonl`:** Repeating `(asker, askee, topic)` tuples across 3 simulated days that trip `RecurringQuestionProcessMapper` (P10), producing a process_map proposal at Beat 5.

All seed files are replayed through wire-replay during the install arc — no flow-bypass.

**Files:**
- `tests/fixtures/install_arc_seed/cursed_csv_chatter.jsonl`
- `tests/fixtures/install_arc_seed/recurring_action_chatter.jsonl`
- `tests/fixtures/install_arc_seed/domain_touched_chatter.jsonl`
- `tests/fixtures/install_arc_seed/recurring_question_chatter.jsonl`
- `packages/sim-harness/src/sim_harness/seed_loader.py` — load and time-align seed files with the install arc clock
- `tests/integration/test_install_arc_seeds.py` — each seed triggers the expected reactivity at the expected beat

**Tests:**
- Each seed JSONL replays without error.
- Each seed triggers exactly its target reactivity (no noisy collateral fires).
- Beat timing is deterministic ±2s.

**Definition of done:**
- Four JSONL files committed.
- `make install-arc` end-to-end produces all 9+1 beats firing with the expected reactivities at the expected times.
- N2 gate green; tests green.

---

## 8. Project-wide invariants — non-negotiable

Every agent dispatched against this PRD inherits these. They are restatements from `CLAUDE.md` and the prior PRDs.

1. **No flow-bypass.** Dashboard reads ledger truth, sim drives the wire, channel-adapter is the only writer of flow-driven entries. No `simulate-flows`-style helpers, no direct ledger writes from production-read accessors. Wire-replay is the only deterministic backstop. Seeds (S1–S4) replay through wire-replay, not direct emit_*.
2. **Connector-agnostic source flows.** Adding a connector is class + JSON-schema + registry entry. P5 and P7 must not modify core.
3. **Multi-tenant from line one.** Every ledger entry, every projection, every API route carries `company_id`. Cross-tenant accessors forbidden — W6.A2's 52-test sweep enforces this; any new accessor must pass it.
4. **Role-aware rendering.** Every new component renders correctly under installer / admin / member / observer lenses. No role leak.
5. **Production-only onboarding.** OAuth real or disabled-with-config-message. No synthesized grants, no "Unknown · observer" fallback.
6. **Cleanup checklist enforced.** N2 gate at `tests/demo/test_N2_no_placeholders_on_screen.py` runs on every commit. New code must pass it. No `// TODO demo`, no `return <FIXTURE>` from production-read accessors, no self-grant placeholders, no time-pressure prose.
7. **Auditable confirmation.** Every emit_* with a confirmation step writes `proposed_by`, `confirmed_by`, `confirmed_at`. No exceptions, including for new projections and new reactivities. (D019.) Specifically: `metrics_keep_rate_published` (P1), `experiment_lesson` (P9), `data_product_proposed(kind=process_map)` (P10) all carry attribution.
8. **Determinism under replay.** Anything new must replay byte-identically. P1 (composite_score), P2 (ramp gauges), P9 (experiment_lesson), P10 (process_map), P12 (first-knowings) all get a determinism test.
9. **Hosted MCP is bidirectional and full-feature.** Every read accessor visible on the dashboard is also accessible via MCP. P11 verifies this surface is complete; P12 (first-knowings) and P9 (lessons) must expose MCP read tools.
10. **Hermes spike result stands.** No re-litigation of OpenClaw → Hermes migration in this window. Slack ships through OpenClaw + Channel Ledger Adapter.
11. **OSS-replayability is structural.** Every ledger entry kind that contributes to a KPI value must be replayable from `wormbase-tools` (P8). New entry kinds (`metrics_keep_rate_published`, `experiment_lesson`, `data_product_proposed(kind=process_map)`) must register their projection logic in the OSS package, not just core.

---

## 9. Execution model — two parallel waves + human-led track

**Wave A** (T+0 → T+30): Nine parallel agents, one orchestrator message. Ricardo runs P0 in parallel.

| Agent | P-item | Wall-clock |
|---|---|---|
| 1 | P1 — composite_score + keep-rate | 25m |
| 2 | P2 — ramp gauges | 25m |
| 3 | P4 — cursed CSV | 25m |
| 4 | P5 — reference connector + conformance | 30m |
| 5 | P6 — identity merge property test | 25m |
| 6 | P7 — Snowflake passthrough | 30m |
| 7 | P8 — OSS audit replay | 30m |
| 8 | P9 — experiment_lesson learn step | 30m |
| 9 | P10 — conversation process map | 30m |
| (human) | P0 — founder walk | 60m |

Review gate: at T+30, orchestrator runs N2 + W6 property suite + cleanup-checklist sweep across all nine commits. Sequential review, parallel build.

**Wave B** (T+30 → T+60): Five parallel agents.

| Agent | P-item | Wall-clock |
|---|---|---|
| 10 | P11 — MCP external client beat | 25m |
| 11 | P12 — first-knowing surface | 25m |
| 12 | P13 — voice "Ask the worm" live beat | 25m |
| 13 | P14 — wire-replay stage demo | 25m |
| 14 | Seed-S1–S4 — install-arc seed sequences | 25m |

Review gate: at T+60, orchestrator runs full test suite (≥2,725 + new tests; target ≥3,000 with all P0–P14 additions) + N2 + cleanup-checklist + Q1–Q9 smoke test against `make install-arc`.

**Stranger track** (T+60 → T+120): P3 stranger recording. Ricardo + one human + recording rig. If recording is clean, becomes demo opener. Time-box re-records to two attempts.

**Q1–Q9 verification** (T+120 → T+180): Orchestrator runs through all nine acceptance criteria on the demo tenant. Each Q has an acceptance command; pass/fail logged.

**Sign-off** (T+180 → T+240): Tag `demo-day` on `main`. Per McKinney's note: don't tag v0.5 — tag `demo-day` and let seams be visible.

Total wall-clock from PRD-handoff to demo-ready: ~4 hours including review and verification.

---

## 10. Risk log

Risks the demo agent should pre-empt:

- **OrbStack / Docker Desktop wedge** — doctor script handles it; verify before the stranger arrives.
- **Network egress from inside containers** — flaked twice this hackathon. Pre-warm image pulls.
- **Voice agent API key absence on demo machine** — graceful-degrade is shipped; P13 verifies the floater renders the degraded state visibly with a banner.
- **Cursed CSV encoding detection failure** — P4 tests this; verify on demo machine before P3.
- **Composite score curve flat** — if metric doesn't move during install arc, projection is wrong, not loop. Inspect projection before re-running. (LeCun: a flat curve is the finding, naming it is more honest than fudging.)
- **Stranger gets stuck on `/login` OAuth scope screen** — common Slack OAuth UX trap. Pre-check OAuth scopes match runbook screenshots.
- **MCP tunnel URL flake** — cloudflared sidecar can drop. P11 includes a fallback to localhost MCP if tunnel down (with banner).
- **Two-tenant docker-compose collision** — P14's stage demo uses `--project-name` to namespace. Verify port allocation.
- **`experiment_lesson` extraction returning empty string** — P9 must produce non-trivial lessons or the demo's recursive-loop story doesn't land. Seed-S1–S2 chatter must be rich enough.
- **Process map proposal not firing during install arc** — Seed-S4 must produce ≥3 recurring (asker, askee, topic) tuples before Beat 5. Verify timing.

---

## 11. Sign-off — what proves we shipped

The demo agent has shipped this PRD when, on a fresh checkout at the `demo-day` tag, this command sequence succeeds on a stock laptop with a stranger driving:

```
git clone <wormbase-repo>
cd wormbase
cp .env.example .env
make tutorial
# OAuth handshake, install, beats 0–9 fire including 6.5
# wait for Beat 9 Statement-to-Owner DM
# verify on /research that composite_score curve has descended
# verify on /research First-Knowing tab shows ≥3 detections
# verify on /research Lessons card shows ≥1 experiment_lesson per scope
# verify on /dashboard that all three ramp gauges have ticked
# verify on /system-map that ≥1 process_map proposal exists
# click any ramp gauge → /trace opens in <10s
# wire-replay tests/fixtures/install_arc.jsonl on a second tenant
# diff the two final ledger hashes — must match (Q8)
# pip install wormbase-tools && wormbase-tools replay snapshot.jsonl --to <kpi> matches /kpis (Q5)
# ask the worm a KPI question via voice or text fallback; click citation → /trace (C8)
# in Claude Desktop, query worm via MCP; mutation reflected in /kpis (Q4 partial)
# run pytest --plugins wormbase_tools_test --connector examples.connectors.parquet_local:ParquetLocalConnector → green (Q7)
```

If that sequence runs end-to-end without a developer touching the keyboard, the demo is shipped. The worm's value — institutional AI for the data function — is on stage. Everything else is decoration.

---

**End of PRD.** Hand to demo agent.
