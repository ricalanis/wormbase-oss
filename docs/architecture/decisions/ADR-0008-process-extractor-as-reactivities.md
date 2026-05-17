# ADR-0008: Process extraction as W5a Reactivities

**Status:** Accepted
**Date:** 2026-05-03

## Context

Process extraction in WormBase turns raw chat into durable organizational
knowledge: decision records, process maps from recurring questions, and
system-map nodes capturing cross-domain interaction patterns. Before this
decision, all of this lived inside `apps/worm-core/src/wormbase_core/process_extractor.py`
as a single ~970-LOC polling class that batch-processed up to 500 chat
rows per cycle through a fused
"extract_decisions / extract_process_maps / update_system_map / emit_recurring"
pipeline. The class was driven by a custom `process_extractor_loop` in
`service.py`, scheduled from `cli.py` at boot. It was the fourth of the
existing reactivity loops that the W5a substrate was designed to replace.

A separate concern was the relationship to two other modules in scope of
the wave: `topic_extractor.py` (a 424-LOC chat-message → resource resolver,
named misleadingly) and `data_product_actions.py` (a 621-LOC module of
pure PEVR emission helpers). The original framing implied both needed to
move or split as part of process extraction; the empirical reality was
different.

## Decision

WormBase ships **`packages/wormbase-process-extractor`** as three working
Reactivities plus one stub, all registered with the existing W5a
`ReactivityRegistry`:

- **`RecurringQuestionReactivity`** — lifts intact from the already-shipped
  P10 `RecurringQuestionProcessMapperReactivity`. Predicate
  `EntryKind("chat_received") & HasTopic() & InThread()`; condition
  `DailyBudget(per_tenant=5) & NotRecentlyFired("process_map", 24h) &
  DomainEnabled`; fire body counts triplets and emits `data_product_proposed`
  of kind `process_map`. Zero refactor required; only registration in
  process-extractor's factory.
- **`DecisionRecordReactivity`** — extracts from `_extract_decisions` in
  the polling extractor. Predicate `EntryKind("chat_received") &
  MatchesDecisionPattern()` (one new `_ArgsPredicate` subclass holding the
  regex constants). Fire body runs heuristic-or-Kimi extraction and emits
  `decision_recorded`.
- **`SystemMapNodeReactivity`** — extracts from `_update_system_map` +
  `_flush_system_map`. Per-tenant module-level accumulator (same shape as
  P10's `_TENANT_HISTORIES`); flush cadence shifts from "every N batches"
  to "every N fires per tenant"; emits one `system_map_node` per flush in
  priority order.
- **`TopicSynthesisReactivity`** — ships as a stub for v1
  (`fired=False` always). Real cluster emission and the question of whether
  to add a new `silver_topic_cluster_emitted` entry kind are deferred to a
  follow-up phase, deliberately avoiding new entry kinds under the
  kinds-are-forever doctrine without a real consumer.

The polling `ProcessExtractor` class and `process_extractor_loop` are
**deleted** in the same wave. The wave's signature outcome is a net
negative LOC delta: ~973 LOC of polling code removed, plus ~50 LOC of
orchestration; ~600 LOC of new Reactivities; balance ~-400 LOC.

What this decision explicitly does **not** do:

- It does **not** lift `topic_extractor.py` to the process-extractor
  package. The module is a chat-message → resource resolver consumed by
  `owner_lookup.py` and `cli.py` — a chat-worm responsibility, not
  process-extractor's. Process-extractor's "topic synthesis" is genuinely
  net-new work (the `TopicSynthesisReactivity` stub).
- It does **not** split `data_product_actions.py`. That module is pure
  PEVR-cycle emission helpers; there is no synthesis logic inside it. The
  synthesis decision lives in the call site (`process_extractor.py:876`
  chooses to call `propose_data_product` for recurring questions). The
  call sites lift to process-extractor Reactivities; the emission module
  stays in worm-core, depended on via lazy import inside Reactivity `fire`
  bodies.
- It does **not** introduce any new entry kinds. All four Reactivities
  emit existing kinds (`decision_recorded`, `process_map_proposed`,
  `system_map_node`, `data_product_proposed` of kind=process_map).
- It does **not** move `phenomenon_gaps.py` (W5b's gap detectors) into
  process-extractor. The gap detectors stay sibling to research-worm and
  co-emit `process_map_proposed` to the ledger. Composition is via the
  ledger, not via direct package-to-package calls.

## Consequences

**Positive:**

- A 970-LOC polling class collapses into four Reactivity instances
  totaling ~290 LOC of new code (with ~720 LOC lifted). The net LOC
  delta is negative — the wave reduces total codebase size.
- The fourth existing reactivity loop is retired. The W5a substrate is now
  the dispatch path for every process-extraction signal, with no parallel
  poller running.
- Cross-worm composition is clean: `phenomenon_gaps.py` (research-shaped)
  and `RecurringQuestionReactivity` (process-shaped) co-emit
  `process_map_proposed` to the ledger; the dashboard /processes view
  aggregates both. No direct package-to-package calls.
- Per-Reactivity testing is trivial — each one is a small dataclass with a
  predicate, condition, and async fire body, exercised against
  `InMemoryLedger`.

**Negative:**

- The flush-cadence semantic shift (SystemMap) drifts slightly: nodes
  emit one at a time in priority order instead of in a burst at batch
  boundaries. Acceptable under the graceful-evolution rule, but tests need
  to assert the new shape.
- In-process accumulator state (`_TENANT_HISTORIES`, `_SYSTEM_MAP_ACCUMULATORS`)
  is intrinsic to the design. Cross-process dispatch would require
  projection-backed state — a future wave's concern, explicitly out of
  scope here.
- `TopicSynthesisReactivity` ships as a stub. Anyone expecting working
  topic clusters in v1 will be disappointed; the deferral is deliberate
  to honor the entry-kind permanence rule.

**Neutral:**

- P10's existing class lives at `packages/reactivities/src/wormbase_reactivities/process_mapper.py`
  and stays there (it shares predicates with W5b's gap detectors).
  Process-extractor's factory re-exports it. Same convention
  lake-maintainer uses: Reactivity classes live where their imports
  cluster; factories assemble across packages.
- Process-extractor depends on `data_product_actions` via lazy import
  inside Reactivity `fire` bodies, mirroring the pattern
  `phenomenon_gaps.py` established. The dependency is explicit but not
  load-bearing for the package's tests.

## Cross-references

- Related ADRs: ADR-0003 (lake-maintainer's Reactivity composition is the
  template); ADR-0006 (the hub redefinition pins
  `wire_process_for_install` as one of the four boot wires); ADR-0009
  (research-loop composes with process-extractor at the ledger layer).
- Architecture: `ARCHITECTURE.md` §2 lists `wormbase-process-extractor`
  in the package layout.
