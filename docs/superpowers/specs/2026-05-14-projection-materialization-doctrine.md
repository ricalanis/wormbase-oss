# Projection Materialization Doctrine — when do Reader impls promote from raw-ledger to projection-table?

**Status:** doctrine, durable. Authored 2026-05-14 as the v1.2 follow-up #4 close-out (v1.3 Task 2 Sub-task A).
**Scope:** the four Reader Protocol implementations that back the agent-gateway MCP path, plus all future Reader impls that follow the same shape.

## Context

After v1.1 + v1.2 + v1.3, the agent-gateway MCP path uses four raw-ledger Reader implementations rather than projection-table-backed queries:

- `LedgerDecisionReader` (v1.1 Task 2 — `apps/worm-core/src/wormbase_core/agent_gateway_readers.py:75`)
- `LedgerProcessMapReader` (v1.1 Task 3 — same file, line 249)
- `LedgerDataProductReader` (v1.2 Task 2 Item #3 — same file, line 377)
- `LedgerAgentGrantReader` (v1.3 Task 1 Item #1 — same file, line 564)

Each scans `await self.ledger.fetch(company_id)` and filters by `payload.tool == "emit_<kind>"` or equivalent. At tenant scale ≥10K-100K ledger entries per company, every MCP tool call backed by one of these readers becomes O(N) over the company's entire ledger. Without optimization, this is the v2 latency bottleneck the SaaS deployment will hit first.

This doctrine codifies when a reader implementation should be promoted from raw-ledger to projection-table backing.

## Current state of projection tables (2026-05-14)

Discovery: `grep "projection_" packages/ledger/src/wormbase_ledger/projections/builder.py`.

| Reader | Projection table exists? | Builder handler exists? | Today's read path |
|---|---|---|---|
| `LedgerDecisionReader` | **No** (`projection_decisions` not in `projections/schema.py`) | **No** | raw-ledger `fetch(company_id)` + filter `decision_made` / `decision_revisited` |
| `LedgerProcessMapReader` | **No** (`projection_process_maps` not in schema) | **No** | raw-ledger `fetch(company_id)` + filter `process_map_proposed` / `_confirmed` / `_archived` |
| `LedgerDataProductReader` | **Yes** (`projection_data_products` defined; `projection_data_product_runs` + `projection_data_product_consumption` siblings exist) | **Yes** (builder folds `data_product_proposed` / `data_product_generated` / `data_product_archived` per `builder.py:1687`+) | raw-ledger `fetch(company_id)` + filter |
| `LedgerAgentGrantReader` | **Yes** (`projection_agent_grants` defined; Wave-2 Task 1 v013 migration) | **Yes** (builder folds `agent_grant` execute at `builder.py:1227` + insert at `:1911`) | raw-ledger `fetch(company_id)` + filter |

**Asymmetry**: the agent-gateway-era readers (`LedgerDataProductReader`, `LedgerAgentGrantReader`) ship with projection tables already populated by the projection-builder — those readers could in principle promote today by swapping `ledger.fetch()` for a projection-table SELECT. The semantic-layer readers (`LedgerDecisionReader`, `LedgerProcessMapReader`) have neither table nor builder handler — promotion for those requires three additional steps before a reader-only swap is even possible (add table, add migration, add builder handler).

## The doctrine: when to promote

### Rule 1 — ship raw-ledger first

Greenfield Reader Protocol implementations start with `await self.ledger.fetch(company_id)` plus an in-memory filter on `payload.tool` / `payload.kind`. Zero migration work. Zero schema risk. This validates the Reader Protocol shape against real ledger entries before any projection table gets locked in.

Corollary: the first version of every reader should be raw-ledger, even when the corresponding projection table already exists. The cost of a wrong projection-schema migration ranks higher than the cost of a fast-follow promotion.

### Rule 2 — promote when latency complains

Symptoms that warrant projection promotion (any one suffices):

- **p99 MCP tool latency exceeds 500ms** for queries that should be sub-100ms (catalog lookups, agent grant lookups, data-product list operations).
- **The reader's `ledger.fetch()` scans more than 10K rows per call** for a single-company query. Measured via projection-builder progress logs or by counting entries in `projection_company_seq` for the company.
- **Single-company traffic exceeds 10 MCP calls/sec sustained.** At that rate, raw-ledger scans saturate the read path and starve writers.
- **The reader fires on every MCP tool call.** `LedgerAgentGrantReader` is the canonical case — `AgentAccessGate.grant_lookup` runs on every gateway invocation, so its read-cost dominates the gateway hot path regardless of absolute ledger size.

If none of these symptoms are present, promotion is premature optimization. Empirical latency data is the gate, not a-priori reasoning about row counts.

### Rule 3 — projection tables (and their builder handlers) must exist before reader promotion

Order of operations for promotion:

1. **Verify the projection table exists** in `packages/ledger/src/wormbase_ledger/projections/schema.py`. If missing, add the table — schema additions are additive Rule-2 changes and don't require a freeze-pause exception.
2. **Verify the builder populates the table** for every entry kind the reader cares about. Check `packages/ledger/src/wormbase_ledger/projections/builder.py`. Missing handlers are silent — the projection table will be empty and reads will return [].
3. **Backfill is automatic.** Projections are deterministic folds of the ledger, so the next projection-runner pass rebuilds the projection from genesis. No manual ETL.
4. **Only then promote the reader.** Replace `await self.ledger.fetch(company_id)` with a parameterized SELECT against the projection table, returning the same Reader Protocol shape.

Anti-pattern: promoting a reader before its projection-builder handler is wired in. Symptom: the MCP tool starts returning empty lists in production, the dashboard panel goes blank, and you spend hours hunting the regression before realizing the projection table never had rows.

### Rule 4 — dual-read for one release before retiring the raw-ledger path

When promoting a reader, keep the raw-ledger path as a fallback for one release window. Pattern:

```python
async def list_decisions(self, company_id: CompanyID, ...) -> list[Decision]:
    rows = await self._read_from_projection(company_id, ...)
    if not rows and self._fallback_enabled:
        # Projection-builder backfill incomplete? Fall back.
        return await self._read_from_ledger_fetch(company_id, ...)
    return rows
```

Retire the fallback only after:

- The projection-builder has demonstrably backfilled for every existing tenant (verify via `projection_company_seq` watermark = current ledger tail per company).
- One release has shipped without the fallback triggering (logged at WARN level so it shows in dashboards).

This protects against projection-builder bugs at the moment of cutover. The cost is a few extra lines of code carried for one release; the protection is real.

## Promotion order (recommended)

By expected hot-path frequency in production:

1. **`LedgerAgentGrantReader` first** — `AgentAccessGate.grant_lookup` fires on EVERY MCP tool call. Highest hot-path frequency by orders of magnitude. The projection table (`projection_agent_grants`) and builder handler already exist from Wave-2 Task 1 (v013 migration). Promotion cost: ~1 task (swap `ledger.fetch()` to `SELECT ... WHERE company_id = $1 AND active = true` against `projection_agent_grants`).
2. **`LedgerDataProductReader` second** — `data_products.list/get/consume` MCP tools are common in the compounding loop and grow linearly with org maturity. Projection table (`projection_data_products`) and builder handler already exist. Promotion cost: ~1 task (swap fetch for projection SELECT, preserve latest-status fold semantics from the existing reader).
3. **`LedgerDecisionReader` third** — `decisions.*` MCP tools fire less often per-tenant. Projection table does not yet exist. Promotion cost: ~3-4 tasks (add `projection_decisions` schema, add migration, add builder handler, swap reader).
4. **`LedgerProcessMapReader` last** — least frequent per-tenant. Same shape as decisions. Promotion cost: ~3-4 tasks (add `projection_process_maps` schema, migration, builder handler, swap reader).

Total promotion budget (when triggered): roughly 8-10 tasks across all four readers, sequenced by hot-path frequency.

## Today's threshold (v1.3)

**Keep all four readers on raw-ledger. No promotion in v1.3.**

Why:

- All four readers work; per-package and integration suites pass.
- ASML demo arc remains green; dashboard renders real data through every MCP tool family.
- Tenant scale is unproven. Promoting without empirical latency data is premature optimization.
- Per the velocity calibration in `agentic_datasci/.claude/CLAUDE.md` ("Plan quality is the rate limiter, not agent quality" + "Use review bandwidth as the actual constraint"), the next agent to need this signal lives in v2 — after the first paying tenant has accumulated 30+ days of MCP traffic. Spending review bandwidth on it sooner is misallocated.

The Reader Protocol surface is already Postgres-shape-compatible, so the future swap is a class substitution at the gateway construction site, not a refactor of the Protocol or the MCP tool layer. Promotion is a low-risk, isolated change when its time comes.

## What to do when the threshold breaks

Per-reader migration path, sequenced by Rule 4:

1. **Identify the symptom** from Rule 2 (latency, scan size, call rate, or hot-path).
2. **Run Rule 3 step 1+2**: verify projection table exists (add if not, ~1 migration); verify builder handler exists (add if not, ~1 builder commit). For `LedgerAgentGrantReader` and `LedgerDataProductReader` both already exist — go to step 3 directly. For `LedgerDecisionReader` and `LedgerProcessMapReader`, this is two ~1-day workstreams.
3. **Promote the reader with dual-read** per Rule 4. Add an env flag (`WORMBASE_<READER>_PROJECTION_FIRST` default true) so the path can be flipped back at the install level without a redeploy.
4. **Ship; observe one release window**; retire the raw-ledger fallback in the next release.

Cumulative budget for all four reader promotions, with no contention: roughly two weeks of agent + review wall-clock. Most of that is on the two readers (`LedgerDecisionReader`, `LedgerProcessMapReader`) that need new projection-builder handlers; the two already-projected readers can promote in a day each.

## Related doctrine

- **Schema-evolution doctrine** (`docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md`) — projection-table additions are additive Rule-2 changes per the doctrine and don't require freeze-pause exceptions. Builder-handler additions are pure code, no schema impact.
- **Velocity calibration** (`agentic_datasci/.claude/CLAUDE.md` §"Empirical calibration (2026-04-25, this hackathon)") — review bandwidth, not agent throughput, is the constraint. Promotion should be triggered by latency signal, not by speculative scaling.
- **Production-readiness state** in `docs/superpowers/notes/2026-05-14-semantic-layer-v1.2-shipped.md` — documents the raw-ledger baseline this doctrine is governing.
