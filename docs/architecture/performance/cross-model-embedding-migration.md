# Cross-Model Embedding Migration

**Audience:** on-call operators
**Scope:** swapping the WormBase embedding model — default
`nomic-embed-text` (768 dim) ↔ fallback `mxbai-embed-large` (1024 dim).
**Pair with:** `v020_dim_flexible_embedding.py` migration and
`packages/inference-router/src/wormbase_inference/embedding.py`.

This procedure is destructive to existing embeddings. The v020
migration intentionally refuses to ALTER a populated column to a
different dim, so the operator must clear stamped vectors explicitly
before re-running.

---

## Why switch models

Three reasonable triggers:

1. **Rate-limit triggers.** Ollama Cloud's `nomic-embed-text` endpoint
   is hitting per-tenant throttles. Symptoms: rising `EmbeddingError:
   http error` count in `inference-router` logs; compounding-loop
   write-time wires falling behind; `embed_latency_ms_p95` >> 500ms on
   the `agent-gateway` dashboard.

2. **Recall improvements.** `mxbai-embed-large` outputs 1024 dim with
   stronger retrieval scores on semantic-search benchmarks (mxbai's
   reported MTEB delta vs nomic is ~3-5 percentage points). When
   cosine-clustering precision becomes a bottleneck on the
   `/lake/query-improvement` dashboard, the recall improvement may
   justify the migration cost.

3. **Regulatory / data-residency constraints.** `nomic-embed-text` is
   a US-hosted Ollama Cloud model. If a tenant's data classification
   restricts US-egress, `mxbai-embed-large` becomes the staging step
   toward an own-inference deployment (via the
   `mixedbread-ai/mxbai-embed-large-v1` weights for self-hosting).

If none of these apply, **do not migrate**. The byte-identical-
behaviour invariant means a deployment that leaves the env knobs unset
gets the existing ship pick unchanged.

---

## Pre-migration checklist

- **Tenant inventory.** List every tenant on the deployment that has
  stamped embeddings. Run:
  ```sql
  SELECT company_id, COUNT(*)
  FROM projection_query_outcomes
  WHERE embedding IS NOT NULL
  GROUP BY 1;
  ```
  This is the re-embedding work the operator commits to after the swap.

- **Cost estimate.** Multiply the count above by the Ollama Cloud
  `mxbai-embed-large` per-1K-token rate (~$0.0001/1K tokens at time of
  writing; check current price). For a ~10K-outcome tenant this is
  single-digit dollars; for a ~1M-outcome tenant it's an overnight job.

- **Latency budget.** `mxbai-embed-large` is ~30% slower per call than
  `nomic-embed-text` on Ollama Cloud. The compounding write-time wires
  inherit that slowdown. If `embed_latency_ms_p95` was already near the
  500ms budget, the swap pushes past it.

- **Maintenance window.** The swap requires a brief window where no
  new embeddings are written (`WORMBASE_EMBEDDING_ENABLED=false`). The
  wire still ingests; the `record_outcome` MCP tool still writes the
  outcome row; only the embedding column stays NULL until re-enabled.
  Budget ~30 min for the schema work + however long the backfill takes.

- **Rollback plan.** Verify the rollback procedure (below) before
  starting. The fastest rollback is to restore the v019 + v018
  Postgres state from a pre-swap backup; the v020 migration has no
  `down` method (forward-only).

- **Backup.** Full Postgres dump of `projection_query_outcomes` and
  `projection_query_templates`. The destructive step is the `DELETE
  FROM ... WHERE embedding IS NOT NULL` below.

---

## Procedure

The swap is a 7-step sequence. Steps 1-3 stop new writes and clear
existing data. Steps 4-5 migrate the schema + the index. Steps 6-7
re-enable writes at the new dim and backfill historical rows.

### Step 1 — Drop the HNSW index (v019)

The v019 HNSW index is bound to the column's current `vector(N)` type.
`ALTER COLUMN ... TYPE vector(M)` on an indexed column fails. Drop
first.

```sql
DROP INDEX IF EXISTS ix_projection_query_outcomes_embedding_hnsw;
```

This is reversible: running the v019 migration again at the end of
this procedure re-creates the index against the new dim.

### Step 2 — Stop write-time embedding

In the deployment's environment (e.g. `docker-compose.yml`, k8s
secret, `.env` for `apps/worm-core`):

```bash
WORMBASE_EMBEDDING_ENABLED=false
```

Restart `apps/worm-core` so the write-time wires pick up the flag. The
`record_outcome` MCP tool continues to function but skips the embed
call (outcome row gets a NULL embedding).

Verify with a tail of the worm-core logs — the "embedding skipped:
WORMBASE_EMBEDDING_ENABLED=false" debug line should appear on the next
`record_outcome` write.

### Step 3 — Clear stamped vectors

The v020 migration refuses to ALTER a column with non-NULL data:

> v020: projection_query_outcomes.embedding is Vector(768) with N
> row(s) of non-NULL data. Cannot ALTER to Vector(1024) without data
> loss.

Pick one of:

**Option A — Drop rows with embeddings** (preferred when the rows are
recoverable from upstream `agent_query_recorded` ledger entries):

```sql
DELETE FROM projection_query_outcomes WHERE embedding IS NOT NULL;
DELETE FROM projection_query_templates WHERE embedding IS NOT NULL;
```

Both projections are materialized views over the ledger; replaying the
relevant ledger entries via the embedding-backfill admin script in
step 7 re-creates them.

**Option B — NULL the column in place** (preferred when the rows
themselves carry non-embedding data worth keeping):

```sql
UPDATE projection_query_outcomes SET embedding = NULL WHERE embedding IS NOT NULL;
UPDATE projection_query_templates SET embedding = NULL WHERE embedding IS NOT NULL;
```

Lighter touch; preserves outcome / template rows but unlinks the old-
dim vector. Backfill in step 7 fills them back in.

### Step 4 — Run the v020 migration with new env vars

Set the new dim env knob first:

```bash
export WORMBASE_EMBEDDING_DIM=1024
```

Then run the migration runner — either by restarting `apps/worm-core`
(which applies pending migrations at boot) or by invoking the runner
directly:

```bash
uv run --package wormbase-ledger python -m \
    wormbase_ledger.projections.migrate
```

Verify the ALTER landed:

```sql
SELECT a.atttypmod
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
WHERE c.relname = 'projection_query_outcomes'
  AND a.attname = 'embedding'
  AND NOT a.attisdropped;
-- expect: 1024
```

If the migration raises `EmbeddingDimMigrationError` here, step 3 left
some rows un-cleared. Re-run step 3 and verify
`SELECT COUNT(*) FROM projection_query_outcomes WHERE embedding IS NOT
NULL` returns 0.

### Step 5 — Re-create the HNSW index (v019)

The v019 migration is idempotent (`IF NOT EXISTS`). With the column
now at `Vector(1024)`, re-applying v019 creates the matching index:

```bash
uv run --package wormbase-ledger python -m \
    wormbase_ledger.projections.migrate
```

Verify the index exists at the new dim:

```sql
SELECT indexdef FROM pg_indexes
WHERE indexname = 'ix_projection_query_outcomes_embedding_hnsw';
-- expect: CREATE INDEX ... USING hnsw (embedding vector_cosine_ops) WITH (...)
```

The HNSW build params (`m`, `ef_construction`) are independent of dim.
The existing `WORMBASE_HNSW_M` / `WORMBASE_HNSW_EF_CONSTRUCTION` env
knobs apply to the rebuilt index. See
[hnsw-tuning-runbook.md](hnsw-tuning-runbook.md).

### Step 6 — Switch the embedding model + dim, re-enable writes

```bash
export WORMBASE_EMBEDDING_MODEL=mxbai-embed-large
export WORMBASE_EMBEDDING_DIM=1024
export WORMBASE_EMBEDDING_ENABLED=true
```

Restart `apps/worm-core`. The `EmbeddingService` validates the model +
dim pair at construction time (`EmbeddingConfigError` if mismatched),
so a successful boot confirms the swap landed.

Verify by triggering a `record_outcome` call (any tenant) and reading
the resulting row:

```sql
SELECT id, array_length(embedding::real[], 1) AS dim, recorded_at
FROM projection_query_outcomes
WHERE embedding IS NOT NULL
ORDER BY recorded_at DESC
LIMIT 1;
-- expect: dim = 1024
```

### Step 7 — Backfill historical embeddings

The admin script
(`packages/agent-gateway/src/wormbase_agent_gateway/scripts/embedding_backfill.py`)
re-embeds outcomes / templates with NULL `embedding`. Run it across
all tenants:

```bash
uv run --package wormbase-agent-gateway python -m \
    wormbase_agent_gateway.scripts.embedding_backfill --all-tenants
```

This issues one Ollama Cloud `mxbai-embed-large` call per row. Budget
the cost and wall-clock against the inventory in the pre-migration
checklist. The script is resumable — if it gets killed mid-run, re-
running picks up at the next row with a NULL embedding.

Verify completion:

```sql
SELECT
  COUNT(*) FILTER (WHERE embedding IS NULL) AS missing,
  COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS present
FROM projection_query_outcomes;
-- target: missing = 0 after backfill completes
```

---

## Rollback procedure

The fastest rollback is **restore the pre-swap Postgres backup**. The
v020 migration is forward-only; reverting to the old dim requires the
same destructive ALTER in the reverse direction.

If a restore isn't available, the manual rollback mirrors the swap:

1. Set `WORMBASE_EMBEDDING_ENABLED=false`, restart `apps/worm-core`.
2. `DROP INDEX ix_projection_query_outcomes_embedding_hnsw;`
3. `DELETE FROM projection_query_outcomes WHERE embedding IS NOT
   NULL;` (or NULL-in-place).
4. `unset WORMBASE_EMBEDDING_DIM` (defaults back to 768) OR
   `export WORMBASE_EMBEDDING_DIM=768`.
5. Re-run the migration runner. v020 ALTERs back to `Vector(768)`.
6. Re-run the migration runner again (or restart). v019 rebuilds the
   index at 768 dim.
7. `unset WORMBASE_EMBEDDING_MODEL` (defaults back to
   `nomic-embed-text`), `export WORMBASE_EMBEDDING_ENABLED=true`,
   restart.
8. Re-run the embedding-backfill admin script.

Time budget: comparable to the forward swap. **Embeddings are not
preserved across the rollback** — the rollback re-embeds with the
default model. Cosine distances are not comparable across model swaps
regardless of direction (the `Result.model` echo on every
`EmbeddingResult` exists precisely so downstream consumers can detect
this and re-embed).

---

## Validation queries

Post-swap sanity checks the operator should run before declaring the
migration complete:

### Confirm column dim

```sql
SELECT
  c.relname AS table_name,
  a.atttypmod AS embedding_dim
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
WHERE c.relname IN ('projection_query_outcomes',
                    'projection_query_templates')
  AND a.attname = 'embedding'
  AND NOT a.attisdropped;
-- expect: 1024 for both tables (or 768 after rollback)
```

### Confirm HNSW index dim

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE indexname = 'ix_projection_query_outcomes_embedding_hnsw';
```

The `indexdef` should reference the same column type. pgvector
serializes the HNSW build params (`m`, `ef_construction`) into the
reconstructed DDL.

### Confirm embedding coverage

```sql
SELECT
  COUNT(*) AS total,
  COUNT(embedding) AS embedded,
  ROUND(100.0 * COUNT(embedding) / NULLIF(COUNT(*), 0), 2) AS pct_embedded
FROM projection_query_outcomes;
-- target: pct_embedded > 95% after backfill completes
```

A small gap is expected — outcomes that fail the quality gate (e.g.
`quality_score < threshold`) are intentionally not embedded.

### Confirm model echo on fresh writes

```sql
SELECT model_used, COUNT(*)
FROM projection_query_outcomes
WHERE recorded_at >= NOW() - INTERVAL '1 hour'
GROUP BY 1;
-- expect: 'mxbai-embed-large' on every row from the post-swap window
```

The `model_used` column is stamped from `EmbeddingResult.model` on
every write; cross-checking it against the env confirms the swap
actually plumbed through the wire and wasn't shadowed by a stale cache
or stuck process.

---

## See also

- `packages/inference-router/src/wormbase_inference/embedding.py` —
  the env-knob model + dim selection.
- `packages/ledger/src/wormbase_ledger/projections/migrations/v020_dim_flexible_embedding.py`
  — the migration.
- [hnsw-tuning-runbook.md](hnsw-tuning-runbook.md) — v019 index tuning
  (orthogonal to dim).
- `packages/agent-gateway/src/wormbase_agent_gateway/scripts/embedding_backfill.py`
  — the admin backfill script.
