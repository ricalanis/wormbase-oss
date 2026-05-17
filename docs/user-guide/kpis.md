# `/kpis` — User guide

## What it does

The KPIs tab renders the tenant's KPI tree as an **interactive React Flow
graph**. Nodes are metrics (Q3 net revenue, monthly retention, CAC payback);
edges are derivation relationships (gross revenue = sum of plan revenue +
expansion - churn). Each node carries: name, formula, owner domain,
maintainer Person, last computed value, freshness badge, and a Receipt
chip linking to the gold-layer aggregate that produced it.

The view client-polls `/api/kpi-tree/refresh` every 5 seconds, so the
audience watches nodes appear, statuses flip from `proposed` to
`confirmed`, and confidence move as the worm reasons live.

This is the CFO and CMO daily surface.

## First action

If the tenant is brand-new and the tree is empty:

1. Click **Propose first KPI** in the empty state. The
   `ProposeKpiModal` opens.
2. Enter the name (e.g. "Q3 net revenue"), the formula in plain English
   ("sum of plan revenue + expansion - churn for Q3"), and pick the owner
   domain (defaults to `finance` if the SaaS pack is installed).
3. Submit. Writes `emit_kpi_proposed`. The node appears at the top of the
   tree with `status=proposed`.

If the tree is populated:

1. Click any node to open its lineage drawer. The drawer shows the full
   derivation chain back to bronze bytes, every source hash pinned.
2. Click the **Confirm** button on a `proposed` node to ratify the
   definition. Writes `emit_kpi_confirmed`. The node transitions to
   `status=confirmed` and starts re-evaluating against fresh source data.

## Advanced

- **Filter by domain** — the `KpiDomainFilter` chip in the header narrows
  the visible tree to one domain. URL-driven (`?domain=finance`), so the
  view is shareable.
- **Re-evaluate** — admin-only. Click **Recompute** on any node. Writes
  `emit_kpi_recompute_requested`; the projection runner re-folds against
  the latest source bytes and updates the value within ~5s.
- **Retire a KPI** — owner-only. Writes `emit_kpi_retired`. The node greys
  out but stays visible (replayable).
- **Drill to lineage** — click any node, then the **Lineage** chip in the
  drawer. Opens `/trace?kpi_id=<id>` filtered to every entry that touched
  this KPI. Useful for "why did the number change?" audits.
- **Per-role visibility** — members see only KPIs in domains they're a
  contributor to; observers see everything but can't propose or confirm.
  The `MemberAccessBanner` renders if the current Person has no domain
  grants overlapping the tree.
- **Auto-proposal from chat** — when a KPI question fires in chat (Carol:
  "what's our Q3 net?") and the worm doesn't have a KPI definition that
  matches, it proposes one and DMs Carol for confirmation. Writes
  `emit_kpi_proposed` with `proposed_by=worm`.

## Behind the scenes

Reads from `projection_kpi_tree`, a fold of these ledger entries:

```
emit_kpi_proposed          (chat / autoresearch / form / KPI gap)
emit_kpi_confirmed         (admin or domain owner click)
emit_kpi_retired
emit_kpi_recompute_requested
emit_kpi_query             (chat — "what's our Q3 net?")
```

The tree projection ships as a React Flow graph; the polling endpoint
returns the full tree on every call (no incremental updates yet — the
tree is small enough). The freshness badge derives from the most-recent
`emit_kpi_evaluated` for each node.

The KPI gap detection runs in worm-core's KPI-tree subsystem
(`apps/worm-core/src/wormbase_core/kpi_tree.py`). When a chat-based KPI
query fires for a metric the worm doesn't have a definition for, it writes
`emit_kpi_query` (unanswered) and triggers the `kpi_gap_triggered` source
flow — proposing a connection to whatever upstream data is needed.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Empty tree after install | Default lake hasn't yet produced a gold KPI | Wait ~30s; or drop a CSV in a connected channel to trigger cascade |
| Node values stuck on stale | Projection runner not running | `make worm-restart`; check `projection_runner` in logs |
| `Propose first KPI` button silent | `WORMBASE_LEDGER_API_TOKEN` mismatch | Re-set the token; `make dashboard-restart` |
| Lineage drawer 404s on a hash | Source bytes archived in error | Restore the source via `wormbase ledger restore --resource <source_id>` |
| Domain filter empty | Current Person has no domain grants | Ask an admin for a `domain.contributor` grant on the relevant domain |
