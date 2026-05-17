# `/research` — User guide

## What it does

The Research tab surfaces the **per-user autoresearch loop** — Karpathy-style
self-improvement parameterized by each Person's role and position. The
loop runs continuously: per (Person × position) it proposes experiments,
runs them against the lake, evaluates against the user's headline metrics,
and resolves with `keep` or `discard`. Wins compound; losses are
discarded; cumulative improvements update the user's headline metric over
time.

Two views in one tab:

- **Per-tenant overview** — total experiments run, win rate, top movers
  (positions whose headline metric improved most this week), latest 10
  experiments.
- **Per-user view** — filter by selected viewer (defaults to current
  Person); their headline metrics over time (sparkline), their
  experiments queue, their wins, what the worm wants to try next (with
  approve / reject buttons).

Live-polling every 10s via `/api/research/refresh`; the autoresearch loop
runs at 30s in dev so new entries land within one cycle.

This is **the C5 institutional-AI close** — daily for every role.

## First action

1. Open `/research`. The default view is the per-tenant overview.
2. Click your name in the per-user dropdown (or the Person chip in the
   header) to filter to your view.
3. The view renders: headline metrics sparkline, experiments queue
   (proposed / running / kept / discarded), pending-approval section.
4. Click any pending experiment. The detail panel shows: the proposed
   change, expected delta, headline metric, methodology.
5. Click **Approve** to run it. Writes `emit_experiment_resolved` with
   `outcome=keep` after the run resolves. Click **Reject** to skip;
   writes `outcome=discard`.

To see a kept experiment's trail:

1. Click any kept experiment in the wins section.
2. The drawer shows: `emit_experiment_proposed → emit_experiment_run →
   emit_experiment_resolved {outcome: keep, observed_delta: X%}`.
3. Click **Open notebook** — every keep publishes a notebook artifact
   (see [`/notebooks`](notebooks.md)).

## Advanced

- **Switch position** — open `/people/{me}` and change your position.
  Writes `emit_position_confirmed`. Within one autoresearch cycle (~30s
  in dev, longer in prod) the loop re-parameterizes against the new
  metrics.
- **Disable a metric** — open a metric in the sparkline panel → **Mute**.
  Writes `emit_position_metric_muted`. The loop stops proposing
  experiments against this metric for you (other Persons unaffected).
- **Tune frequency** — admin-only. `/settings/research` lets you set the
  experiment cadence per position (default: 1 cycle / 30s in dev,
  1 cycle / 6h in prod).
- **Approve in batch** — the per-user view has a "approve all pending"
  bulk action for trusted experiment classes (e.g. cache-tuning that
  can't break anything).
- **See the worm's reasoning** — every experiment carries a `rationale`
  field. Click to expand. The worm explains why it proposed this change
  for this Person at this time.
- **Override mock execution** — by default, experiments run as **mocked
  execution + ledger writes** (the loop runs on org-metric experiments —
  process tweaks, classifier rules, KPI definitions, cache parameters —
  not on model training). Admins can enable real execution for safe
  classes via `/settings/research`.

## Behind the scenes

Reads from `projection_experiments` + `projection_position_metrics`, folds
of:

```
emit_experiment_proposed     (loop proposed a change)
emit_experiment_run          (loop executed the experiment)
emit_experiment_resolved     (outcome: keep | discard | rate_limited)
emit_position_assigned       (when Person's position is set)
emit_position_metric_added   (per-position metric weight)
emit_position_metric_muted   (Person silenced a metric)
emit_position_question_pattern  (chat-asked questions feed into proposals)
```

The autoresearch loop lives at
`apps/worm-core/src/wormbase_core/autoresearch.py`. Each cycle:

1. **Read recent activity** — questions asked, KPIs viewed, decisions
   participated in (from the conversation lake + dashboard activity).
2. **Track headline metrics** (defined by position; CFO sees revenue +
   runway, data engineer sees pipeline-latency-p95).
3. **Propose experiments** specific to this user — cache tunings, query
   reformulations, KPI definition tweaks, daily-snapshot proposals.
4. **Run** (mock or real) and compare observed delta against expected.
5. **Resolve** — keep if delta ≥ expected and within tolerance; discard
   otherwise. Writes `emit_experiment_resolved`.
6. **Publish notebook** for keeps — `emit_notebook_published` with
   `owner_person_id=<person>`, version stamped.

Direct mapping to the autoresearch paper:

| Karpathy autoresearch | WormBase autoresearch |
|---|---|
| modify code | modify [process / classifier rule / KPI cache / pipeline parameter / answer cadence] |
| train | run [classification / process extraction / query / cache warm] on fresh data |
| evaluate metric | check the user's headline metric (per their position) |
| keep-or-discard | ledger entries; wins keep, losses discard |
| overnight run | the loop runs continuously; reports cumulative wins per user weekly |

## Why this is institutional AI

A general LLM gives the same answer to everyone. WormBase gives **Carol's
CFO answer** to Carol — pre-computed, hash-receipted, with the metrics
SHE cares about ticking up over time. The CFO and the data engineer share
the same worm but get different value because the autoresearch is
per-position. This is also how the worm **scales**: adding a new user is
"create person + assign position." The loop picks them up automatically.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Empty per-user view | Person has no position assigned | Confirm position via `/people/{me}` |
| Headline metric flat | Loop hasn't completed its first cycle | Wait one cycle; or trigger manually via `/settings/research` |
| Approve button silent | Current Person lacks the grant on the metric's domain | Ask domain owner |
| Loop crashed silently | Inference router timeout | `make worm-logs \| grep autoresearch`; restart |
| All experiments resolve to discard | Threshold too tight or signal too noisy | Tune via `/settings/research`; raise tolerance |
