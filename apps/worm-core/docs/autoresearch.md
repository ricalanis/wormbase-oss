# Step 5 — Per-user Karpathy autoresearch loop

This document covers the implementation of **Step 5 (SELF-IMPROVE PER USER)** from the [canonical product arc](../../../docs/superpowers/specs/2026-04-26-wormbase-product-arc.md). The loop maps directly onto Andrej Karpathy's autoresearch script (see the *autoresearch* anchor in `.claude/CLAUDE.md` — "modify code → train → evaluate → keep/discard").

## Why per-user?

A general LLM gives the same answer to everyone. WormBase gives **Carol's-CFO answer** to Carol — pre-computed, hash-receipted, with the metrics SHE cares about ticking up over time. The CFO and the data engineer share the same worm but get different value because the autoresearch loop is parameterised by **position**.

This is also how the worm scales: adding a new user is "create person + assign position." The loop picks them up automatically. No human-in-the-loop config.

## The mapping (Karpathy → WormBase)

| Karpathy (autoresearch paper) | WormBase Step 5 |
|---|---|
| modify code | pick an `ImprovementCandidate` for the user's position |
| train | `emit_experiment_run` (mocked execution log) |
| evaluate metric | read the user's headline metric (per their position) |
| keep-or-discard | `emit_experiment_resolved` with `observed_delta` + `rationale` |
| overnight run | the loop runs continuously; the worm reports cumulative wins per user weekly |

Speed from the loop, trust from the gates — **fast experimentation WITH governance**, because governance is code (the gates) not process (a binder).

## Code map

```
apps/worm-core/src/wormbase_core/
├── positions.py              # Canonical Position registry (9 seed positions)
└── autoresearch_loop.py      # AutoresearchLoop driver + autoresearch_loop_runner
```

### `positions.py`

A static registry of canonical positions, each with:

* **metric set** — what they care about. Drives the per-user headline metric.
* **question patterns** — how they tend to phrase questions.
* **improvement candidates** — archetype experiments the worm should propose for them.

The registry is **extensible**: ledger payloads accept any string position id, so customers can add positions at runtime without a schema migration. The seed list (CFO, CMO, data engineer, marketing lead, ops manager, customer success, founder, admin, product manager) is the day-one set the demo + onboarding wizard exercise.

### `autoresearch_loop.py`

`AutoresearchLoop.run_once(now=...)`:

1. Walk `emit_person_registered` + `emit_position_assigned` entries, latest position wins.
2. For each registered `(person × position)` pair:
   1. Compute recent activity (last 24h of `chat_received` rows where they were the sender).
   2. Sample the position's headline metric (`emit_metric_observed`).
   3. Pick an `ImprovementCandidate` round-robin by `(person_id, cycle_count)`.
   4. Emit `experiment_proposed` → `experiment_run` → `experiment_resolved` (collapsed into the same poll cycle for the demo arc).

Autoresearch is now driven by the W5a `ReactivityRunner` (registered via `wire_research_for_install`), which fires the four research Reactivities on ledger triggers alongside `chat_received_reactivity_poller` and the process Reactivities (`wire_process_for_install`).

## Determinism

Every step of the loop is deterministic by design (Triad C2):

* **Person × Position discovery** — sorted by `(person_id, position_id)` so replay reproduces the same iteration order.
* **Candidate pick** — `idx = sha256(f"{person_id}:{cycle_count}").digest()[…] mod len(candidates)`. Same inputs ⇒ same candidate.
* **Experiment id** — `uuid5(_EXPERIMENT_NAMESPACE, f"{person_id}:{cycle_count}:{candidate_id}")`. Replay reproduces the same id.
* **Outcome resolution** — `hash(experiment_id) % 5 < 3` ⇒ keep (60% rate). Wins land 90% of the expected delta; losses regress slightly. **Never random.**
* **Headline metric value** — anchored on a per-metric baseline, nudged by `cycle_count` and recent activity counts.

## Demo expectations

* The autoresearch loop runs every 30s in dev (`WORMBASE_DEV=1`) and every 10 min in prod. Demo runs operate in dev mode.
* Within the first cycle after onboarding (≤ 30s), the installer's `(person × position)` pair has a propose+run+resolve triple plus a metric_observed sample.
* After ~3 cycles (~90s), the `/research` tab shows ≥ 3 experiments per registered user, with ≥ 1 win.
* The per-user sparkline grows by one point per cycle.
* Top movers populate within ~2 cycles of the first kept experiment.

## Why we collapse propose + run + resolve into one cycle

The Karpathy paper ran ~700 experiments overnight. WormBase's autoresearch operates on org-metric experiments (process tweaks, classifier rules, KPI definitions), not GPU training jobs — runtimes are seconds, not minutes. For the demo arc we want the audience to see the full PEVR cycle land within seconds of opening `/research`, so each cycle emits all three entries in sequence (synthetic 60-second gap between started_at and finished_at preserves the temporal shape).

When real (non-mocked) experiments land in V2, the run will be a real async job and the resolve will land separately. The ledger schema already supports that — `experiment_run` and `experiment_resolved` carry their own timestamps.

## Governance

Every entry passes through the canonical PEVR primitive (`propose → execute → verify → resolve`), so:

* Hash-chained — replay the ledger to timestamp T to get the same state.
* Auditable — every action is evidenced. Click the receipt → land on `/trace`.
* Gated — the same gates that govern other writes apply here. `confidential` proposals would be auto-flagged for review (when policy gates are wired).

## See also

* Canonical product-arc spec: [`docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`](../../../docs/superpowers/specs/2026-04-26-wormbase-product-arc.md), Step 5.
* Karpathy autoresearch anchor: see `.claude/CLAUDE.md` Triad — "Motion / autoresearch".
* a16z "Institutional AI" framing: see `.claude/CLAUDE.md` Triad — "Surface".
