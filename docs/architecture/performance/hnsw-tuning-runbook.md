# HNSW Index Tuning Runbook

**Audience:** operators of a WormBase deployment running pgvector
**Scope:** the HNSW index on `projection_query_outcomes.embedding`
shipped by migration v019.

This runbook walks an operator through tuning the HNSW index for
recall, latency, and build time. The defaults are calibrated for
low/mid traffic; this document documents when to deviate, what knobs
to turn, and how to validate the result.

---

## TL;DR

- `WORMBASE_HNSW_M` and `WORMBASE_HNSW_EF_CONSTRUCTION` env vars tune
  the index built by the v019 migration.
- Defaults (`m=16`, `ef_construction=64`) match the pre-tunable build —
  existing deployments stay byte-identical.
- `IF NOT EXISTS` short-circuits on re-apply. **To actually re-tune,
  you must `DROP INDEX` first, then restart worm-core.**
- Invalid env values raise a loud boot failure. Silent fallback to
  defaults would silently degrade recall and is therefore refused.

---

## 1. When to tune

The defaults are calibrated for low/mid traffic and the pgvector
documented baseline. Tune when telemetry signals one of:

- **Slow `<=>` cosine queries.** Projection-promoted gather latency
  rises above the 50ms p95 budget logged by the agent-gateway
  reactivity reader. Visible in the `/lake/query-improvement`
  dashboard's latency panel and in `pg_stat_statements` for the
  `SELECT ... ORDER BY embedding <=> $1 LIMIT N` shape.
- **Recall miss.** Projection-promoted gather returns markedly fewer
  high-cosine candidates than the SQLite Python-fallback reader does
  for the same triggering entry. Sample with the validation procedure
  in §4.
- **Large table size.** `projection_query_outcomes` over ~100K rows
  for any single tenant. The seq-scan fallback that pgvector uses when
  the graph index is undersized stops being viable.
- **High `ef_search` already in flight.** If `ef_search` has been
  raised to 200+ to recover recall, you are paying the latency tax at
  query time; raising build-time `m` and `ef_construction` is the
  durable fix.

If none of these signals are present, **do not tune**. The defaults are
intentionally conservative; raising `ef_construction` in particular
makes index build dramatically slower for marginal recall gains on
small datasets.

---

## 2. Parameter trade-offs

### `m` (max connections per layer)

- **Default:** 16
- **Valid range:** 4 — 64 (gate-enforced)
- **Effect:** controls graph fan-out. Higher = better recall, slower
  build, more memory per row.
- **Memory:** roughly `m * (sizeof(int) + sizeof(int))` bytes per row
  per layer; on 768-dim vectors with `m=16` this is small compared to
  the vector payload itself, but doubles when you double `m`.
- **Tune to:** 24-32 for high-recall semantic search at >100K rows per
  tenant.
- **Don't:** raise above 48 unless you've validated recall is the
  dominant cost — index build slows superlinearly.

### `ef_construction` (build-time search depth)

- **Default:** 64
- **Valid range:** 16 — 256 (gate-enforced)
- **Effect:** controls search depth during graph construction. Higher
  = better-quality graph, much slower build.
- **Tune to:**
  - 128-256 for offline batch builds (long migration acceptable).
  - 64-128 for online / cold-start builds where boot-time matters.
  - Avoid raising above 128 for online builds — the migration runs at
    boot, and >128 can push migration time past container start-probe
    budgets in some orchestrators.

### `ef_search` (query-time search depth)

- **Not part of index DDL.** You do not set this via env on the
  migration.
- **How to set:** per-query via `SET LOCAL hnsw.ef_search = N;` inside
  a transaction, or per-session via `SET hnsw.ef_search = N;`.
- **Default:** 40 (pgvector default).
- **Effect:** widens the query-time search frontier. Higher = better
  recall, slower per-query.
- **Tune to:** 100-200 for high-stakes lookups; 40 for cheap probes.
- **Rule of thumb:** raise `ef_search` first (it's a flag flip, no
  rebuild); only raise `m` / `ef_construction` if `ef_search=200`
  still doesn't hit your recall target.

---

## 3. How to re-tune

v019 uses `CREATE INDEX IF NOT EXISTS`. Re-applying the migration with
new env values is a no-op — the existing index name short-circuits the
create. To actually re-tune, drop the index manually first.

### Procedure

```bash
# 1. Connect to the tenant DB.
psql "$WORMBASE_DATABASE_URL"

# 2. Drop the existing HNSW index.
DROP INDEX ix_projection_query_outcomes_embedding_hnsw;

# 3. Exit psql.
\q

# 4. Set the new env vars on the worm-core container / systemd unit.
export WORMBASE_HNSW_M=24
export WORMBASE_HNSW_EF_CONSTRUCTION=128

# 5. Restart worm-core so v019 re-applies with the new params.
docker compose restart worm-core    # or your orchestrator's equivalent
```

The migration runner re-applies v019 at boot. With the index now
absent, `CREATE INDEX IF NOT EXISTS` actually creates it — this time
with the new `m` and `ef_construction` reloptions.

**Why no in-place rebuild?** Postgres has no `ALTER INDEX ... SET
(m=...)` for HNSW reloptions. The only way to change them is drop +
recreate. The migration stays idempotent (IF NOT EXISTS) rather than
destructive on every boot; operator-driven re-tuning is the deliberate
trade-off.

### Online vs offline rebuild

- **Offline rebuild (preferred for large tables):** schedule a
  maintenance window. Drop the index, restart worm-core, wait for the
  migration to rebuild. During the rebuild, the projection-promoted
  gather falls back to seq scan + sort (functionally correct,
  slower); reactivities continue to work with degraded latency.
- **Online rebuild (smaller tables):** the migration completes
  quickly for tables under ~10K rows per tenant; the window of
  degraded latency is minutes, not hours.

### Multi-tenant note

The index is per-table, not per-tenant. A single `DROP INDEX` +
restart re-tunes the index for **all** tenants sharing the database.
If you have tenants with different recall/latency profiles, you cannot
tune per-tenant via this knob alone — see §5.5 for per-tenant
overrides under engine-per-tenant routing.

---

## 4. How to validate after a re-tune

### Recall sampling

Sample ~50 triggering entries with known-good cosine matches. Run the
projection-promoted gather and verify top-K overlap with a brute-force
reference (the SQLite Python-cosine fallback is a clean reference).

```sql
-- Pick a triggering embedding to test against.
\set test_embedding (SELECT embedding FROM projection_query_outcomes
                     WHERE id = '<known-id>' LIMIT 1)

-- Index-backed top 10.
SELECT id, 1 - (embedding <=> :test_embedding) AS cosine_sim
FROM projection_query_outcomes
WHERE company_id = '<tenant>'
ORDER BY embedding <=> :test_embedding
LIMIT 10;
```

Compare to brute force (forcing a seq scan):

```sql
SET LOCAL enable_indexscan = off;
SET LOCAL enable_bitmapscan = off;

SELECT id, 1 - (embedding <=> :test_embedding) AS cosine_sim
FROM projection_query_outcomes
WHERE company_id = '<tenant>'
ORDER BY embedding <=> :test_embedding
LIMIT 10;
```

Recall@10 should be ≥0.95 for typical semantic-search workloads. Below
that, raise `ef_search` first; if recall doesn't recover at
`ef_search=200`, raise `m`.

### EXPLAIN ANALYZE the production hot-path

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id
FROM projection_query_outcomes
WHERE company_id = '<tenant>'
ORDER BY embedding <=> '[0.01,0.02,...]'::vector
LIMIT 20;
```

Look for `Index Scan using ix_projection_query_outcomes_embedding_hnsw`
in the plan. If you see `Seq Scan`, the index is missing or the
planner chose not to use it — check `pg_indexes`, check pgvector
version, and verify `ANALYZE projection_query_outcomes` has been run
since the rebuild.

### Verify the rebuild took effect

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE indexname = 'ix_projection_query_outcomes_embedding_hnsw';
```

`indexdef` reconstructs the `WITH (m=..., ef_construction=...)`
clause. Confirm your new values are present.

---

## 5. Rollback

If a re-tune degrades recall or latency, roll back:

```bash
psql "$WORMBASE_DATABASE_URL" -c \
  "DROP INDEX ix_projection_query_outcomes_embedding_hnsw;"

unset WORMBASE_HNSW_M
unset WORMBASE_HNSW_EF_CONSTRUCTION

docker compose restart worm-core
```

The migration re-applies v019 with the documented defaults (`m=16,
ef_construction=64`). Recall and latency return to the pre-re-tune
baseline.

---

## 5.5. Per-tenant tuning (engine-per-tenant deployments)

The global `WORMBASE_HNSW_M` / `WORMBASE_HNSW_EF_CONSTRUCTION` env
knobs apply to every tenant sharing the database. When engine-per-
tenant routing is active, per-tenant HNSW overrides can be set in the
`StaticTenantEngineRegistry` TOML config:

```toml
[tenants.acme]
dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"
hnsw_m = 24                    # optional per-tenant override
hnsw_ef_construction = 128     # optional per-tenant override

[tenants.globex]
dsn_secret_ref = "vault://wormbase/tenants/globex/engine_dsn"
# No HNSW overrides → v019 env globals apply at migration-apply.
```

When unset, the v019 env globals apply. Each field is independently
optional — a tenant can override `m` only and inherit the env-global
`ef_construction`.

The data-model fields ship on `TenantEngineRegisteredPayload` and
`StaticTenantEngineRegistry`. The `resolve_hnsw_params(slug) → (m,
ef_construction)` Protocol method is the consumer surface. The v019
migration does not yet read these overrides directly — the Phase 3+4
admin migration tool, when it ships, will call `resolve_hnsw_params`
per tenant engine at migration-apply time and pass the resolved tuple
into `_resolve_hnsw_params` as overrides (falling back to env globals
for tenants without pins).

**Validation:** values are checked against the documented ranges
(`m ∈ [4, 64]`, `ef_construction ∈ [16, 256]`) at TOML-load time and
at ledger-payload-write time. A misconfigured TOML fails fast at boot;
a misconfigured `tenant_engine_registered` ledger entry fails fast at
emit. Both invariants line up with the env-knob valid range so an
operator sees the same error message at whichever surface they touch.

With per-tenant overrides and engine-per-tenant routing, each tenant's
index can be tuned independently — addressing the "the index is per-
table, not per-tenant" limitation from §3.

---

## 6. References

- **pgvector HNSW docs:** <https://github.com/pgvector/pgvector#hnsw>
  — canonical build-param trade-offs.
- **v019 migration source:**
  `packages/ledger/src/wormbase_ledger/projections/migrations/v019_hnsw_index_query_outcomes.py`
- **v019 tests:**
  `packages/ledger/tests/test_migration_v019.py` — pins the env-knob
  contract and the IF NOT EXISTS short-circuit invariant.
- [cross-model-embedding-migration.md](cross-model-embedding-migration.md)
  — the dim-flexible companion runbook (v020).
