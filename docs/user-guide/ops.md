# `/ops` — User guide

## What it does

The Ops tab is the **observability surface** for the running stack. Four
production-critical health metrics, polled every 5 seconds via SSE on
`/api/v1/ops/health`:

1. **Postgres reachability + latency** — green if reachable < 50ms p95,
   amber 50-200ms, red unreachable or > 200ms.
2. **Ledger throughput sparkline** — entries/second over the last 10
   minutes, color-coded by quadrant.
3. **MCP rate-limit status per tenant** — call counts vs budget, last
   call timestamp.
4. **Agent loop status** — for each loop (worm-core reactivity loops,
   channel-adapter, projection-runner): last heartbeat, current cycle
   number, errors in the last hour.

Per the role-nav, this tab is **admin (daily)** and **observer
(weekly)**. Members and the installer don't see it — per-tenant rate
limits surface other tenants' metadata that members shouldn't browse.

## First action

Confirm the stack is healthy:

1. Open `/ops`. The first paint shows current state from a
   server-component fetch; the OpsLiveView client then takes over with
   5s polling.
2. Every card should be green. If anything's red:
   - **Postgres red** — `make logs postgres`; usually a connection pool
     exhaustion. `make worm-restart` rotates connections.
   - **Ledger throughput flat** — projection runner stalled. Check the
     loop status card; restart if last heartbeat > 60s ago.
   - **MCP rate-limit red** — a tenant exceeded its budget. Either raise
     the budget via `/settings/mcp` or wait for the rolling window to
     clear.
   - **Agent loop unreachable** — `make ps` to check container status;
     `make worm-restart` or `make adapter-restart`.

## Advanced

- **Drill into a loop** — click any loop card. Drawer shows the last 50
  cycles (timestamp, duration, entries written, errors). Errors expand
  to the full traceback inline.
- **Postgres latency histogram** — click the postgres card. Renders a
  100-bucket histogram of query latencies over the last hour.
- **MCP per-Person breakdown** — click the rate-limit card to see
  per-Person usage within the tenant. Top 10 callers; click any to
  open `/people/{id}`.
- **Trigger a manual projection rebuild** — admin-only. `Recompute
  projections` button. Writes `emit_projection_rebuild_requested`. The
  runner re-folds every projection from the ledger (slow — minutes for
  a full tenant).
- **Force a heartbeat** — admin-only. `Ping all loops`. Each loop
  responds with a fresh heartbeat. Use this when the loop status card
  looks stale but you suspect a UI desync rather than a real loop hang.

## Behind the scenes

Reads from `lib/server/ops-health.ts` which fans out to:

- `SELECT 1` against postgres (reachability + latency)
- `SELECT max(seq), count(*), max(ts) FROM ledger_entries WHERE company_id = $1 AND ts > now() - interval '10 minutes'` (throughput)
- `SELECT * FROM projection_mcp_calls WHERE ... GROUP BY ...` (rate-limits)
- HTTP `/health` against worm-core, channel-adapter, projection-runner
  (loop heartbeats)

The OpsLiveView client polls `/api/v1/ops/health` every 5 seconds. The
endpoint is server-side cached for 1s to avoid hammering Postgres.

The agent loops report status by writing to a `loop_heartbeats` table (a
projection) on every cycle. The Ops tab's loop status reads from this
table; "unreachable" means the heartbeat row is older than 60s.

## What "healthy" looks like

| Card | Healthy |
|---|---|
| Postgres | green, p95 < 50ms |
| Ledger throughput | non-zero on a tenant with chat traffic; flat is fine on idle tenants |
| MCP rate-limit | green or amber across all tenants; red only after explicit budget |
| Agent loops | every loop heartbeat < 60s old; cycle count incrementing |

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| All cards red on first paint | dashboard can't reach worm-core | Check `WORMBASE_LEDGER_API_BASE`; `make dashboard-restart` |
| Postgres flapping green/red | connection pool exhausted | Tune `WORMBASE_DB_POOL_SIZE`; restart worm-core |
| Throughput card empty | no entries in last 10 min | Idle tenant — drop a chat message to confirm wire works |
| MCP card says "no tenants" | no `emit_mcp_call_*` entries yet | Connect Claude Desktop and ask one question |
| Loop status says "unreachable" but logs look fine | heartbeat write failed silently | Check `loop_heartbeats` projection migration applied |
