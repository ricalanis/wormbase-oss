# ADR-0009: Autoresearch loop as W5a Reactivities

**Status:** Accepted
**Date:** 2026-05-03

## Context

The autoresearch loop is WormBase's instantiation of the institutional-AI
"motion" axis: time-boxed propose/execute/verify/resolve cycles, scoped per
Person / Team / Company, that compound into experiment lessons feeding the
next cycle. Before this decision, the loop lived as `AutoresearchLoop` +
`TeamAutoresearchLoop` + `CompanyAutoresearchLoop` inside
`apps/worm-core/src/wormbase_core/autoresearch_loop.py` (~1,580 LOC),
`autoresearch_learn.py` (~650 LOC, P9 lesson extraction and application),
and `keep_rate_publisher.py` (~230 LOC, daily keep-rate publishing — but
**unwired** in production: no boot-time task starts it).

The codebase also carried `heuristic_loop.py` (~220 LOC), a pre-autoresearch
artifact that emitted three entry kinds (`heuristic_experiment`,
`heuristic_loop_started`, `heuristic_loop_completed`) but was referenced
only in its own test and a single re-export.

The architectural opportunity beyond the package-shape win was composition:
W5b's phenomenon-gap detectors (`KpiReferenceWithoutKpiReactivity` and
siblings in `phenomenon_gaps.py`) emit `phenomenon_gap_detected` entries
that no autoresearch path read. Wiring gap-detected to experiment-proposed
would make "the worm builds the rules it runs on" wired end-to-end at the
predicate level.

## Decision

WormBase ships **`packages/wormbase-research-loop`** with three Reactivities
plus one recommended extras-class, all registered with the existing W5a
`ReactivityRegistry`:

- **`ExperimentTriggerReactivity`** — combines propose, run, and scope
  arbitration in one fire body. Predicate is a compound OR over
  `phenomenon_gap_detected | metric_observed | experiment_lesson |
  experiment_resolved` (gap-driven, cycle-driven, learn-driven,
  follow-on-driven). Condition is `NotRecentlyFired(novelty_key=f"trigger_{scope}",
  hours=poll_hours) & DailyBudget(per_tenant=budget_for_scope)`. Per-scope
  instances (Person, Team, Company) are constructed at factory time from
  env-var-driven poll intervals and budgets.
- **`ExperimentResolveReactivity`** — predicate `EntryKind("experiment_run")`.
  Fire body runs scope arbitration (`_check_higher_scope_conflict`) and
  keep-notebook publishing when outcome is keep.
- **`LessonExtractionReactivity`** — P9 lift. Predicate
  `EntryKind("experiment_resolved") & ResolvedKept()` (one small new
  predicate). Fire body extracts and persists experiment lessons.
- **`KeepRatePublishReactivity`** — recommended addition that closes a live
  unwired-feature gap. The existing `keep_rate_publisher.py` is unwired in
  production; extracting it as a Reactivity both moves it out of the hub
  and makes it run.

Boot-time, `wire_research_for_install` constructs ~9-12 Reactivity
instances (3 scopes × 3 classes + optional 3 keep-rate publishers per
scope), passes the per-scope env-var cadences and budgets into them, and
registers them with the existing registry. The custom runners
(`autoresearch_loop_runner`, `team_loop_runner`, `company_loop_runner`)
and their per-runner `asyncio.sleep` cycles are deleted — ~250 LOC of
orchestration code goes away, replaced by the W5a `ReactivityRunner`.

`heuristic_loop.py` is **deleted** in the same wave, along with its test
and re-export. The class predates `AutoresearchLoop` and is superseded by
it; lifting dead code into a new package would widen the substrate's
apparent surface for no benefit. The three `heuristic_*` entry kinds become
retired-not-deleted under the schema-evolution doctrine.

The notebook publisher (`data_product_actions.NotebookPublisher`) is
**injected via DI** into the Reactivity constructors at
`wire_research_for_install` time, rather than lazy-imported inside fire
bodies. DI makes the dependency explicit and testable; lazy-import is the
right pattern for best-effort gap detectors but the wrong pattern for
load-bearing keep-notebook publishing.

Composition with W5b is at the **predicate level, not via a new Protocol**.
`ExperimentTriggerReactivity.predicate` includes
`EntryKind("phenomenon_gap_detected")`. When a gap is detected (e.g. chat
references a metric that has no KPI node), the trigger fires an experiment
proposal whose `proposed_change` dict carries the gap's `ref_id` (additive
field; no schema migration). The experiment's resolve flows back to
gap-resolution visibility in the First-Knowings projection.

## Consequences

**Positive:**

- ~520 LOC of dead/runner code dies in the same wave that ships the
  package. Net codebase reduction.
- No new entry kinds, no new Protocols, no new orchestrator loop. The W5a
  substrate handles all dispatch; the wave is purely a re-shape of
  existing surface plus the always-on factory/lifecycle tax.
- "The worm builds the rules it runs on" becomes wired end-to-end:
  chat → gap detected → experiment proposed → experiment resolved → lesson
  extracted → next experiment biased by lesson. The plumbing is purely
  entry-kind-mediated.
- `KeepRatePublishReactivity` closes a live unwired-feature gap. Daily
  keep-rate publishing now runs in production for the first time.
- Per-scope cadence and budget remain operator-tunable via the same env
  vars (`WORM_CORE_AUTORESEARCH_INTERVAL_S` and siblings) that worked
  before — the operator surface is preserved.

**Negative:**

- The "30s in dev / 600s in prod" cadence dial moves from a runner-level
  sleep to a Reactivity condition's `NotRecentlyFired.hours` field. Same
  semantic; different plumbing layer. The env vars feed the dataclass at
  construction time.
- `ExperimentTriggerReactivity`'s compound-trigger predicate must include
  a kind that fires often enough to drive the loop. `metric_observed`
  works but is self-emitted (circular but safe); cleaner is layering onto
  the same coarse trigger set lake-maintainer uses (`chat_received` etc.)
  plus the gap kinds.
- In-process budget state on the registry is fine for v1 but breaks if
  multi-process dispatch ever ships. Same constraint already documented
  for P10's `_TENANT_HISTORIES`.

**Neutral:**

- Three `heuristic_*` entry kinds become retired-not-deleted under the
  doctrine. Forwarder is "drop" — no replacement projection consumes them.
  Replay remains graceful.
- P12 First-Knowing surface stays in worm-core's `projections/`. It folds
  `phenomenon_gap_detected` (W5b-emitted) plus raw proposes — neither is
  research-emitted. The projection is hub-shaped.
- W5b's phenomenon-gap detectors stay in `packages/reactivities`. They are
  not part of research-loop's package; composition is at the ledger layer.

## Cross-references

- Related ADRs: ADR-0003 (lake-maintainer's Reactivity composition is the
  template); ADR-0006 (the hub's four-wire boot includes
  `wire_research_for_install`); ADR-0008 (process-extractor follows the
  same retire-the-poller pattern).
- Architecture: `ARCHITECTURE.md` §2 lists `wormbase-research-loop` in the
  package layout.
