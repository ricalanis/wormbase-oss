# `/trace` — User guide

## What it does

The Trace tab is the **raw ledger viewer** — every entry, in
chronological order, filterable by quadrant (propose / execute / verify /
resolve), kind, person, channel, and time-range. Each row is a single
ledger entry with: timestamp, kind, quadrant, actor, payload preview,
chain hash, classification badge.

This is the **observer / auditor** daily surface. It's also where every
deep-link receipt from `/kpis`, `/decisions`, `/data-products`, `/mcp`
ends up — the universal escape hatch into the substrate.

## First action

Land on a specific entry from a receipt:

1. From a Slack chat-receipt link in any channel, the URL is
   `http://localhost:3000/trace?entry_id=<uuid>`.
2. Open it. The Trace tab loads with the row highlighted; the chain
   hash + payload + parent_entry_id are all visible.
3. Click the parent_entry_id chip to walk back the PEVR chain — verify
   → execute → propose. Each step is one row.
4. Click any payload field (e.g. a `source_id` or `kpi_id`) to filter
   by it.

To browse by kind:

1. Open `/trace`. Default view is the last 100 entries.
2. Use the **TraceFilterBar** in the header — filter by quadrant
   (propose / execute / verify / resolve), kind (e.g.
   `emit_kpi_proposed`), person, channel, time-range.
3. URL-driven — every filter combo produces a shareable link.

## Advanced

- **Search by chain hash** — paste a hash in the search box; the row
  jumps to that entry. Useful for "I have a hash from a screenshot, show
  me what produced it" audits.
- **Walk the chain** — every row has a "Show chain" chip. Click to
  expand the full PEVR chain inline (same chain hash root). The view
  collapses by default to keep the page scannable.
- **Export** — admin-only. **Export filtered** writes a JSONL of every
  entry matching the current filter. Used post-demo to archive trace
  evidence.
- **Replay** — admin-only. **Replay filtered** triggers `wire-replay`
  against the matching `InfraEvent`s — the deterministic backstop for
  testing changes against historical data.
- **Verify hash chain** — open the **Verify** chip in the header.
  Triggers `make verify` against the current tenant's slice; displays
  green if every chain hash is reproducible, red with the offending row
  otherwise. The hash chain is the integrity primitive — a break is a
  P0 bug.

## Filters

| Filter | Values | Notes |
|---|---|---|
| `quadrant` | propose / execute / verify / resolve | Multi-select |
| `kind` | every `emit_*` entry type | Type-ahead |
| `person_id` | any Person UUID | Filter to that Person's actions |
| `channel_id` | any channel UUID | Slack / Discord / Teams |
| `since` | ISO 8601 timestamp | Inclusive lower bound |
| `until` | ISO 8601 timestamp | Inclusive upper bound |
| `classification` | public / internal / confidential / pii / regulated | Multi-select |
| `domain_id` | any Domain UUID | Filter by domain scope |

All filters compose via URL params (`?quadrant=propose&kind=emit_kpi_proposed`).

## Behind the scenes

Reads from `ledger_entries` directly — this is the only tab that does so
(every other tab reads a projection). The query is bounded to the current
tenant's `company_id` and applies role-aware filtering before rendering.

The TraceFilterBar fires URL changes; the page is `dynamic = "force-dynamic"`
so the server re-queries on every URL change. Pagination via cursor on
`(seq, entry_id)`.

The classification badge is computed at render time:
- public → green
- internal → grey
- confidential → amber
- pii → red
- regulated → red with lock icon

If the current Person lacks the grant for a classification level, the
payload is rendered as `<redacted>` with a lock icon. The row itself stays
visible (existence is not redacted at this fidelity — that's a v3 nuance).

## Receipt-linking pattern

Every receipt-bearing surface in the dashboard generates URLs of the form:

```
/trace?entry_id=<uuid>
/trace?chain_root=<uuid>     (jumps to the chain root)
/trace?kpi_id=<uuid>         (filters to entries touching a KPI)
/trace?source_id=<uuid>      (filters to entries touching a source)
/trace?data_product_id=<uuid>
```

This is the universal substrate-link. Slack chat-receipt buttons link
here; data-product replay traces link here; MCP audit drill-ins link
here. **One escape hatch into the truth.**

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Verify chip red | A migration applied without re-hashing; or a manual write bypassed PEVR | Investigate as P0 — never let this go red on production |
| Filter combo returns nothing | Filters too narrow / wrong tenant cookie | Reset filters; check the tenant chip |
| Payload shows `<redacted>` for everything | Current Person is observer with min-cap on every entry | Switch to admin lens via `/people/{me}` (or ask) |
| Export 500s | Filter span too large | Narrow time-range; export in batches |
| Chain walk hangs | Long PEVR chain with deep parent links | Use the receipt-link directly to the entry instead of expanding inline |
