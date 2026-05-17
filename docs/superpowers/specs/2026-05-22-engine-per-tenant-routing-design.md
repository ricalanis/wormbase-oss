# Engine-per-Tenant Routing — Shape B Design Spec

**Date:** 2026-05-22
**Status:** DESIGN-ONLY — implementation gated on concrete premium-tier customer demand
**Scope:** A complete architectural design for **Shape B** (engine-per-tenant) multi-tenant routing — the deferred follow-up to Path 4 (Shape A, shipped 2026-05-21 in `a0daffe`). No code changes accompany this spec. The spec exists to lock the architectural decisions now, so when a tenant ask materializes the implementation is a focused 1-2 day execution rather than a re-design + execution sprint.

**Authority:** approved as item #1 of the final-wave dispatch on 2026-05-13. Implementation gated on concrete premium-tier customer demand (data-residency, physical-isolation, or paid-tier resource ceiling). No premium tenant ask exists today.

---

## 1. Status

**DESIGN-ONLY.** This document is the durable architectural artifact. It does NOT authorize implementation, schema migrations, or boot-path changes. The status note documenting the trigger condition + approval lives separately at `docs/superpowers/notes/2026-05-22-engine-per-tenant-deferred.md` (orchestrator close-out); this spec is the architectural record.

The user's open-paths list conditions implementation on a concrete trigger:

> "Engine-per-tenant (Shape B) — physical isolation; `TenantRouter.resolve()` Protocol extension to return engine handle. **Trigger: when a premium-tier customer demands physical isolation.**"

The agentic_datasci CLAUDE.md prescribes:

> "Don't add features, refactor, or introduce abstractions beyond what the task requires. Don't design for hypothetical future requirements."

These two prescriptions are reconciled here by **writing the spec without writing the code**. The spec is cheap. The code is not. The spec also pre-decides every architectural question, so the implementation, when triggered, is execution-only.

When the trigger fires, this spec graduates from DESIGN-ONLY to ACTIVE and a small implementation plan (1-2 day) is drafted that quotes this spec section-by-section.

---

## 2. Motivation — when does Shape A become insufficient?

Path 4 shipped Shape A (lightweight tenant context) with this rationale (`docs/superpowers/notes/2026-05-21-overnight-run-complete.md` §"Path 4"):

> "All readers already do SQL-level `WHERE company_id = $1` isolation; Shape B (engine-per-tenant) would duplicate readers, gateway deps, and broker plumbing for zero correctness gain — multi-tenant isolation is already enforced at the SQL layer. Shape A adds visibility and per-tenant policy (rate limits + quotas) without disturbing the existing single-engine architecture."

Shape A is correct *as long as* the following five conditions hold:

1. Every reader uses `WHERE company_id = $1` and the WHERE-clause is never elided.
2. Every writer attaches `company_id` to every row.
3. The hosting tenant accepts the operational implications of co-tenanted Postgres (shared connection pool, shared backup window, shared maintenance window).
4. No customer compliance requirement demands physical data separation (data-residency, SOC-2 control X.Y, regulator boundary).
5. No tenant's working set is large enough to evict another tenant's pages from `shared_buffers`.

Shape B becomes the right architecture when *any* of those conditions break. Concretely, the five trigger conditions are:

### 2.1 Data-residency / regulatory

Customer requires data-at-rest in a specific Postgres instance — geographic (EU resident in EU-region RDS), regulatory (in-country compute for some jurisdictions), or contractual (BAA / DPA mandates physical separation). Shape A cannot satisfy this; the shared Postgres lives in one region and one tenant.

### 2.2 Performance isolation

A "hot" tenant's query mix evicts pages another tenant is working from. Shape A makes the two compete for `shared_buffers`, write-ahead log throughput, autovacuum cycles, and connection-pool slots. Shape B gives each premium tenant their own Postgres with their own buffers + their own pool.

### 2.3 Resource ceiling for premium tier

Premium tier sells a per-tenant resource budget (e.g. "100M ledger entries / 10TB lake / 1k req/s sustained"). Shape A's Postgres has one resource ceiling shared across all tenants; Shape B's premium tenant has their own ceiling.

### 2.4 Compliance lifecycle (e.g. "delete all data for tenant X")

Shape A satisfies "delete tenant X" via `DELETE FROM ledger_entries WHERE company_id = $1` plus parallel deletes on every projection table. This is **correct but auditable-only after the fact** — proving "tenant X's data is gone" requires SQL evidence, not physical evidence. Shape B satisfies "delete tenant X" via `DROP DATABASE wormbase_tenant_X` plus retiring the engine handle. Physical evidence; trivially auditable.

### 2.5 Premium tier monetization

Physical isolation as a paid feature. The customer perceives the difference: "our Postgres, our backups, our maintenance window, our perf isolation." Shape B is the marketable artifact behind the premium SKU.

**Trigger condition for graduating DESIGN-ONLY to ACTIVE:** any one of 2.1-2.5 surfaces as a concrete ask from a paying or about-to-pay customer. Not a hypothetical, not a roadmap item — a named customer with a named requirement.

---

## 3. Architecture

### 3.1 Shape A (today)

```
MCP request
     │
     ▼
X-Tenant-Slug header
     │
     ▼
TenantRouter.resolve(slug) → TenantContext { company_id, rate_limit, quota }
     │
     ▼
Gateway deps (global) ── reads from single shared engine ──
                          SELECT ... FROM projection_*
                          WHERE company_id = $1
```

One engine. One connection pool. One Postgres. Multi-tenant isolation enforced at the SQL `WHERE` layer in every reader.

### 3.2 Shape B (future)

```
MCP request
     │
     ▼
X-Tenant-Slug header
     │
     ▼
TenantRouter.resolve(slug) → TenantContext {
                                tenant_slug,
                                company_id,
                                rate_limit,
                                quota,
                                engine: AsyncEngine,             ← NEW
                                engine_dsn_secret_ref: str,      ← NEW
                                engine_kind: Literal[
                                    "shared", "isolated"         ← NEW
                                ],
                                enabled: bool,
                             }
     │
     ▼
Per-tenant gateway deps (composed lazily from PerTenantGatewayDepsCache) ──
                          reads from tenant's engine ──
                          SELECT ... FROM projection_*
                          (no WHERE company_id needed for isolated
                           engines since the DB itself isolates; the
                           WHERE clause stays as defense-in-depth
                           per §3.4 below)
```

N engines: one shared (for "shared" tenants — Shape A behavior under the new Protocol), N-1 isolated (one per "isolated" tenant). The router decides which engine a request uses by reading `engine_kind` on the resolved `TenantContext`.

### 3.3 The seam — `build_projection_reader_from_ledger`

Phase 3c close-out (`docs/superpowers/notes/2026-05-20-semantic-layer-v2.B-phase3c-shipped.md` §"build_projection_reader_from_ledger is the natural seam") flagged the precise locus where Shape B integrates:

```python
# apps/worm-core/src/wormbase_core/agent_gateway_construction.py:1016
def build_projection_reader_from_ledger(
    ledger,
    *,
    engine: AsyncEngine | None = None,
    ...
) -> QueryOutcomeProjectionReader | None:
    ...
```

In Shape A, `engine` is `ledger.engine` (the single shared engine). In Shape B, `engine` is `tenant_context.engine` (resolved per request). The factory signature does not change; what changes is *who calls it and with what engine*. Same factory, lazily composed per tenant, cached in `PerTenantGatewayDepsCache`.

This is the single-most-important architectural commitment in this spec: **no reader changes shape**. Readers continue to take an `engine` parameter; the difference is whether they all share one engine (Shape A) or each tenant brings its own (Shape B). The Protocol layer that already exists (`QueryOutcomeProjectionReader`, `LedgerDecisionReader`, `LedgerSubscriptionReader`, etc.) is engine-agnostic by construction.

### 3.4 Defense-in-depth — WHERE company_id stays

Even in Shape B, every reader's `WHERE company_id = $1` clause is **retained**. Removing it would weaken correctness if a registry misconfiguration ever pointed two tenant slugs at one engine. The `WHERE` clause becomes belt-and-braces:

| Layer | What enforces isolation |
|---|---|
| Physical (Postgres instance) | Connection routing |
| SQL `WHERE` (reader) | Defense-in-depth — survives router bugs |
| SQL `INSERT ... company_id` (writer) | Tags rows so the `WHERE` clause works |

The third layer is required because Shape A and Shape B share a code path; writers under Shape B still attach `company_id` to every row even though the engine is single-tenant. This keeps the migration path Shape A → Shape B + the inverse symmetric.

---

## 4. New abstractions

### 4.1 `TenantEngineRegistry` Protocol

```python
# packages/wormbase-agent-gateway/src/wormbase_agent_gateway/tenancy.py
# (additive — extends the existing module, not a new file)

@runtime_checkable
class TenantEngineRegistry(Protocol):
    """Resolves tenant_slug → AsyncEngine handle.

    Default impl returns None for every slug (= Shape A: every tenant
    uses the shared engine). Premium tenants get a non-None handle from
    one of the impls below.

    The Protocol is intentionally minimal: one method, async, returns
    an engine handle or None. Lifecycle (start/stop, pool tuning) is
    the impl's responsibility (see §4.4).
    """

    async def resolve_engine(self, slug: str) -> AsyncEngine | None: ...
```

The Protocol is a *separate* surface from `TenantRouter`. Composition flows:

```
TenantRouter.resolve(slug) → TenantContext {company_id, rate_limit, quota}
                                  │
                                  ▼ (Shape B layer below)
                          TenantEngineRegistry.resolve_engine(slug) → AsyncEngine | None
                                  │
                                  ▼
                          IsolatedTenantContext { ..., engine, engine_kind }
```

The router knows nothing about engines; the registry knows nothing about quotas. Composition is in the wiring layer (`agent_gateway_construction.py`).

### 4.2 `IsolatedTenantContext`

```python
@dataclass(frozen=True)
class IsolatedTenantContext(TenantContext):
    """TenantContext extended with optional engine handle (Shape B).

    Shape A continues to construct plain TenantContext (engine field
    absent / None). Shape B's router constructs IsolatedTenantContext
    when the registry returns a non-None engine for a slug.

    The downstream consumer sites (tool handlers in mcp_server) use
    isinstance(ctx, IsolatedTenantContext) AND ctx.engine is not None
    to decide which engine to compose against.
    """

    engine: AsyncEngine | None = None
    engine_dsn_secret_ref: str | None = None
    engine_kind: Literal["shared", "isolated"] = "shared"
```

Subclass rather than additive fields on the parent because:

- Shape A's `TenantContext` stays exactly as it is (no risk to existing Path 4 tests).
- The Optional-Effect Injection doctrine §6 Rule 6 (Protocol boundary) is satisfied: the boundary widens via subclass, not via mutation.
- Type-narrowing at call sites is explicit (`isinstance` check), which makes the two paths visible in code review.

### 4.3 `PerTenantGatewayDepsCache`

```python
# apps/worm-core/src/wormbase_core/agent_gateway_construction.py (additive)

class PerTenantGatewayDepsCache:
    """LRU cache of GatewayDeps composed against per-tenant engines.

    Keyed by (tenant_slug, engine_id) so that:
      * Shape A tenants share one cached GatewayDeps (key = (any_slug, <shared_engine_id>))
      * Each Shape B tenant has its own cached GatewayDeps

    Eviction policy: LRU with a configurable max-size (default 32).
    Eviction triggers TenantEngineLifecycle.on_evict(slug) (see §4.4),
    which closes the engine's pool gracefully.

    The cache key includes engine_id (not engine_dsn) so that
    engine-rotation flips invalidate the cached deps; pointing the
    registry at a new engine for the same slug evicts the old deps
    immediately.
    """

    def __init__(self, *, max_size: int = 32, lifecycle: TenantEngineLifecycle):
        ...

    async def get_or_build(
        self,
        *,
        ctx: IsolatedTenantContext,
        build_fn: Callable[[AsyncEngine], Awaitable[GatewayDeps]],
    ) -> GatewayDeps:
        ...
```

Why a cache: `build_projection_reader_from_ledger` and the other Phase-3c factories are non-trivial (they wire 5+ Protocols against the engine). Rebuilding them per-request would dominate per-request latency. Caching is per-tenant, with engine-id keying so registry changes invalidate cleanly.

Why LRU and not unbounded: connection-pool exhaustion (see §9.1). Every active cache entry holds an engine pool open; bounding the cache bounds the connection count.

### 4.4 `TenantEngineLifecycle`

```python
class TenantEngineLifecycle(Protocol):
    """Engine start/stop hooks — keeps connection pools from leaking."""

    async def on_resolve(self, slug: str, engine: AsyncEngine) -> None:
        """Called the first time a slug resolves to an engine in this process.

        Concrete impls: warm the pool, ping the DB, increment a counter,
        record a metric, emit a `tenant_engine_resolved` ledger entry
        (impl-time, against the SHARED engine — the per-tenant engine
        has no global ledger to write to).
        """

    async def on_evict(self, slug: str, engine: AsyncEngine) -> None:
        """Called when the per-tenant cache evicts this slug.

        Closes the engine's pool. The next resolve_engine() for this
        slug builds a fresh pool.
        """

    async def on_shutdown(self) -> None:
        """Called on process shutdown — drains every still-open pool."""
```

Without this lifecycle Protocol, abandoned pools leak. With it, the lifecycle is observable and composable (Vault-backed engine credential rotation, for example, is a `TenantEngineLifecycle` decorator that evicts on credential change).

### 4.5 Composition diagram

```
                          ┌──────────────────────┐
inbound MCP request  ───▶ │   FastMCP listener   │
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │  TenantRouter        │
                          │  .resolve(slug)      │──► TenantContext
                          └──────────┬───────────┘   { company_id,
                                     │                rate_limit,
                                     ▼                quota }
                          ┌──────────────────────┐
                          │ TenantEngineRegistry │
                          │ .resolve_engine(slug)│──► AsyncEngine | None
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │ Wiring layer wraps:  │
                          │ IsolatedTenantContext│
                          │ { ...ctx, engine }   │
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │ PerTenantGatewayDeps │
                          │ Cache.get_or_build   │──► GatewayDeps (per-tenant)
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │ MCP tool handler     │
                          │ uses GatewayDeps     │
                          └──────────────────────┘
```

Each rectangle is engine-agnostic in shape; only the wiring layer knows the difference between shared and isolated.

---

## 5. Migration path — Shape A deployment adds Shape B for one tenant

The migration is the high-leverage operation this spec exists to de-risk. The steps below are an operational runbook.

### 5.1 Steps

1. **Provision the isolated Postgres** for the tenant.
   - Same major version as the shared engine (currently Postgres 16; pgvector ≥0.6 per `v019_hnsw_index`).
   - Same extensions enabled (`pg_extension >=0.6` per the boot-time pre-flight in `133b34a`).
   - Reachable from the agent-gateway process (private VPC, DNS resolvable, credentials in vault).

2. **Run the standard projection migrations** on the isolated DB.
   - The same `v00X` → `v019` migrations that ran against the shared engine.
   - The migration tool reads the migrations directory and applies in order. Idempotent.
   - Validation: `SELECT version FROM schema_migrations ORDER BY version` should match the shared engine's output exactly.

3. **Replay the tenant's ledger entries** from the shared DB into the isolated DB.
   - One-shot admin tool: `wormbase-worm-core tenant-migrate-to-isolated --slug=<slug> --target-dsn-secret-ref=<vault-ref>`.
   - Implementation template: the Phase 3b backfill (`embedding-backfill`) is the closest precedent — both are admin-driven, per-tenant, idempotent, dry-run-supported.
   - Reads from the shared engine: `SELECT * FROM ledger_entries WHERE company_id = $1 ORDER BY seq ASC`.
   - Writes to the isolated engine: `INSERT INTO ledger_entries (...) VALUES (...)` preserving `entry.seq`, `entry.hash`, `entry.prev_hash`, `entry.ts`.
   - Reconstructs projection tables from the replayed ledger (running the projection runner against the isolated engine), not by SQL-COPY-ing the shared engine's projections — projections are derivable, the ledger is the truth.

4. **Update `TenantEngineRegistry`** config to point that tenant's slug at the isolated engine.
   - For `StaticTenantEngineRegistry` (§6.1): edit config + restart agent-gateway.
   - For `LedgerTenantEngineRegistry` (§6.2): emit a `tenant_engine_registered` entry on the **shared** engine (the registry's own ledger source); the watcher picks it up + the cache invalidates immediately.

5. **Subsequent requests route to isolated.** Shared DB rows for that tenant can be tombstoned + retained (for audit) or purged (for the "delete all data" promise).
   - Tombstone strategy: emit a `tenant_migrated_to_isolated` entry on the shared engine; reader projections respect tombstones (don't return rows where `tombstoned_at IS NOT NULL`).
   - Purge strategy: `DELETE FROM ledger_entries WHERE company_id = $1` plus parallel deletes on every projection table. Reversible only via a re-replay from a backup.

6. **Validation: parallel-replay assertion.** For a recent N-day window, both engines produce byte-identical ledger replay outputs. This is the migration's correctness gate — the tool DOES NOT consider the migration complete until parallel-replay passes.

### 5.2 Parallel-replay validator

The validator is a tool, not a Reactivity:

```python
# apps/worm-core/src/wormbase_core/admin/parallel_replay_validator.py (new, impl-time)

async def assert_parallel_replay_byte_identical(
    *,
    company_id: UUID,
    since: datetime,
    until: datetime,
    shared_engine: AsyncEngine,
    isolated_engine: AsyncEngine,
) -> ParallelReplayResult:
    """Replay both engines' ledger entries for company_id over [since, until].

    For each (entry.seq, entry.hash) pair across the two engines:
      - Both engines must have the same seq present (no gaps, no extras).
      - Both engines must have the same hash for that seq.
      - Both engines' projection-builder outputs for that entry must be
        byte-identical (modulo replay_mode-no-op'd side effects, per
        Optional-Effect Injection doctrine §3 Rule 8).

    Returns ParallelReplayResult with:
      - matched_seqs: count of seqs that matched
      - hash_mismatches: list of seqs where hash differed
      - missing_in_isolated: seqs present in shared, absent in isolated
      - missing_in_shared: seqs present in isolated, absent in shared
      - projection_diffs: structured diff of per-entry projection outputs
    """
```

Diff format (for `projection_diffs`): a JSON Lines stream, one line per mismatched entry, with `seq`, `kind`, `expected` (shared engine's projection-builder output), `actual` (isolated engine's projection-builder output). Operators read this stream to diagnose the cause of any mismatch.

The migration runbook step 6 BLOCKS if `parallel-replay` produces any non-empty diff. The tool returns nonzero; the admin retries (potentially after fixing the projection-builder or re-replaying the ledger). The route flip in step 4 happens **only after** the validator passes.

### 5.3 Cutover idempotency

If the migration is interrupted mid-replay (network blip, container restart), re-running the tool from the start is safe:

- Step 3 (ledger replay) is idempotent — `INSERT ... ON CONFLICT (seq) DO NOTHING`.
- Step 4 (registry update) is idempotent — re-emitting `tenant_engine_registered` is a no-op if the active state already matches.
- Step 6 (validation) is read-only.

Mid-flight failure leaves the system in Shape A; the route does not flip until the registry update lands.

---

## 6. `TenantEngineRegistry` implementations

Three impls, increasing in complexity, decreasing in friction.

### 6.1 `StaticTenantEngineRegistry`

```python
class StaticTenantEngineRegistry:
    """Config-file-based mapping {slug → DSN}."""

    def __init__(self, *, mapping: dict[str, str]):
        self._mapping = mapping
        self._engines: dict[str, AsyncEngine] = {}

    async def resolve_engine(self, slug: str) -> AsyncEngine | None:
        dsn = self._mapping.get(slug)
        if dsn is None:
            return None
        if slug not in self._engines:
            self._engines[slug] = create_async_engine(dsn, pool_size=...)
        return self._engines[slug]
```

Config source: JSON / TOML at a path resolved by `WORMBASE_TENANT_ENGINE_REGISTRY_PATH`. Loaded at boot. Restart-required to change.

Use case: **early Shape B deployments**, where the operator team manages 1-3 isolated tenants by hand. Simplest possible impl; no ledger entries, no watchers, no race conditions.

### 6.2 `LedgerTenantEngineRegistry`

```python
class LedgerTenantEngineRegistry:
    """Reads tenant_engine_registered entries from the shared engine's ledger.

    Reactive: watches for new entries via a Reactivity on
    tenant_engine_registered and updates its in-memory map
    accordingly. Cache-invalidation propagates via TenantEngineLifecycle.
    """

    def __init__(self, *, ledger: Ledger, secret_resolver: CredentialBroker):
        ...

    async def resolve_engine(self, slug: str) -> AsyncEngine | None:
        ...

    async def on_tenant_engine_registered(
        self, entry: LedgerEntry
    ) -> None:
        """Reactivity callback — invalidates cache + resolves new engine."""
        ...
```

Use case: **mature Shape B deployments**, where adding an isolated tenant is a no-restart operation. The admin emits the entry; the registry picks it up; the cache invalidates; the next request routes to the new engine.

Composition: the registry is itself constructed against the shared ledger (the shared engine remains the metadata source-of-truth even when most read/write traffic is on isolated engines). This is intentional — the shared engine becomes a coordination plane.

### 6.3 `RemoteTenantEngineRegistry`

```python
class RemoteTenantEngineRegistry:
    """Calls out to a tenant-management service.

    Use case: WormBase has a separate control plane (CRM-grade tenant
    table, billing integration, provisioning automation). The registry
    is a thin client of that service.

    OUT OF SCOPE for v4 of this design. Listed here as the natural
    evolution if/when the control plane gets its own service.
    """
```

Not implemented in the first Shape B release. Documented here so the Protocol's evolution path is visible.

### 6.4 Choice of impl at boot

```python
# apps/worm-core/src/wormbase_core/agent_gateway_construction.py (additive)

def build_tenant_engine_registry_from_env(
    *, ledger: Ledger, secret_resolver: CredentialBroker
) -> TenantEngineRegistry | None:
    if not is_engine_per_tenant_enabled():
        return None
    impl = os.environ.get(
        "WORMBASE_TENANT_ENGINE_REGISTRY_IMPL", "static"
    ).strip().lower()
    if impl == "static":
        path = os.environ.get("WORMBASE_TENANT_ENGINE_REGISTRY_PATH")
        ...
        return StaticTenantEngineRegistry(mapping=...)
    if impl == "ledger":
        return LedgerTenantEngineRegistry(
            ledger=ledger, secret_resolver=secret_resolver
        )
    raise ValueError(f"Unknown tenant engine registry impl: {impl!r}")


def is_engine_per_tenant_enabled() -> bool:
    return os.environ.get(
        "WORMBASE_ENGINE_PER_TENANT", "false"
    ).strip().lower() == "true"
```

Single canonical capability gate: `WORMBASE_ENGINE_PER_TENANT=true`. Default OFF. Sub-tuning knob: `WORMBASE_TENANT_ENGINE_REGISTRY_IMPL` (default `static`).

---

## 7. New ledger entry kind: `tenant_engine_registered`

### 7.1 Payload

```python
# packages/ledger/src/wormbase_ledger/entry_kinds/tenant_engine_registered.py
# (new at impl time)

class TenantEngineRegisteredPayload(EntryPayload):
    kind: ClassVar[str] = "tenant_engine_registered"
    tenant_slug: str
    engine_kind: Literal["shared", "isolated"]
    engine_dsn_secret_ref: str   # e.g. vault://wormbase/tenants/{slug}/engine_dsn
    provisioned_at: datetime
    migrated_from_shared_at: datetime | None  # NULL for new tenants;
                                              # SET after Shape A → B migration
    provisioned_by_person_id: str
```

### 7.2 Schema-evolution compliance

Per `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md`:

- **Rule 1 (kind is forever):** new kind, joins the permanent registry. No existing kind covers "physical engine binding for a tenant" — this is a genuinely new concept.
- **Rule 2 (additive only):** `migrated_from_shared_at: datetime | None` carries a default, future flips don't need new fields, secondary metadata can be added as additive `Optional[T]` fields.
- **Rule 3 (deprecation is retired-not-deleted):** if a tenant migrates back from isolated to shared (rare; covered by symmetric reverse migration), a future `tenant_engine_deregistered` kind is emitted; the original `tenant_engine_registered` stays in the ledger as historical evidence.
- **Rule 4 (replay is graceful):** the projection-builder folds this kind into the registry-projection table; older binaries that don't know this kind skip it gracefully (per the existing kind dispatcher policy).
- **Rule 5 (freeze pause at 50 / 100 → review threshold):** current `KIND_REGISTRY = 105` (after final-wave #7's `tenant_quota_consumed`). Adding `tenant_engine_registered` at Shape B impl time takes it to **106**. The 2026-05-03 doctrine's threshold of 50 was already adjusted upward to ~100 per the schema-evolution doctrine Wave F Addendum 1 (see project memory `project_worm_decomposition`); 106 is one over that addended threshold. Implementation-time: the addition itself does NOT block, but the impl plan must:
  1. Confirm the threshold's then-current value (the addendum may have moved it again).
  2. If still ≥100, flag the freeze-pause review for "is this addition warranted?" The answer is yes (engine binding is structural, not behavioral) but the review must be on the record.

### 7.3 Projection

```sql
-- v020_tenant_engine_registry.sql (at impl time)

CREATE TABLE projection_tenant_engines (
    id UUID PRIMARY KEY,
    tenant_slug TEXT NOT NULL,
    company_id UUID NOT NULL,
    engine_kind TEXT NOT NULL CHECK (engine_kind IN ('shared', 'isolated')),
    engine_dsn_secret_ref TEXT NOT NULL,
    provisioned_at TIMESTAMPTZ NOT NULL,
    migrated_from_shared_at TIMESTAMPTZ,
    provisioned_by_person_id UUID NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One active engine binding per slug at a time
    UNIQUE (tenant_slug, active) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX projection_tenant_engines_slug_idx
    ON projection_tenant_engines (tenant_slug);
```

This projection lives on the **shared** engine, never on an isolated engine — the shared engine is the metadata source-of-truth (§6.2).

### 7.4 Emit sites

`tenant_engine_registered` is emitted by **one** site: the admin migration tool's step 4. There is no Reactivity that emits it. Provenance: the admin who ran the migration tool is `provisioned_by_person_id`.

---

## 8. Rollout sequence — once a tenant asks

Sequenced for de-risking: each phase is shippable on its own. The deployment in Phase 4 is the only step that needs production downtime (and only for the requesting tenant, not the platform).

### Phase 1 — Protocol + types (week 1)

- Add `TenantEngineRegistry` Protocol to `tenancy.py`.
- Add `IsolatedTenantContext` dataclass subclass.
- Add `StaticTenantEngineRegistry` impl.
- Add `is_engine_per_tenant_enabled()` env helper.
- Compose at boot, default disabled.
- Tests: Protocol contract, IsolatedTenantContext immutability, env-helper default-OFF.
- **Outcome:** Shape B Protocol is reachable; no production tenant uses it.

### Phase 2 — Ledger kind + replay tool (week 2)

- Add `tenant_engine_registered` kind to the entry-type registry.
- KIND_REGISTRY 105 → 106 at this impl-time commit.
- Add `LedgerTenantEngineRegistry` impl.
- Add the parallel-replay validator (`assert_parallel_replay_byte_identical`).
- Tests: kind round-trips through ledger; registry watches + invalidates; validator catches a synthetic mismatch.
- **Outcome:** the metadata plane is ready; the validation gate is ready.

### Phase 3 — Admin tool + manual approval gate (week 3)

- Add `wormbase-worm-core tenant-migrate-to-isolated --slug=<slug> --target-dsn-secret-ref=<vault-ref> [--dry-run] [--approve]`.
- Without `--approve`, the tool exits after the parallel-replay validation step (does not flip the route).
- With `--approve`, the tool emits `tenant_engine_registered` and the registry picks up the new binding.
- Tests: end-to-end on a SQLite-backed two-engine fixture.
- **Outcome:** the migration mechanism exists; no tenant has used it yet.

### Phase 4 — Production deployment (timing TBD by customer)

- Provision the isolated Postgres for the requesting tenant.
- Run schema migrations.
- Run `tenant-migrate-to-isolated --dry-run` to validate.
- Run `tenant-migrate-to-isolated --approve` to cut over.
- Monitor for 24h; rollback path = re-emit `tenant_engine_registered` with `engine_kind="shared"` (the inverse migration). Reverse parallel-replay validation must pass.

Each phase is committable separately. Phases 1-3 ship the architecture; Phase 4 ships the deployment.

---

## 9. Risks

### 9.1 Connection pool exhaustion

**Risk:** N isolated tenants × M connections per pool = N × M open connections. With default `pool_size=20`, 20 isolated tenants is 400 open connections — past the default Postgres `max_connections=100`.

**Mitigation:**

- Hard ceiling on Shape B tenants: start at 10, raise to 20 after operational experience, never exceed `(max_connections - shared_pool_reservation) / per_tenant_pool_size` without raising `max_connections` first.
- `PerTenantGatewayDepsCache` LRU eviction closes idle tenants' pools; `max_size=32` is the soft ceiling for warm pools.
- Pool size per tenant is configurable: `WORMBASE_TENANT_ENGINE_POOL_SIZE=10` (default; lower than the shared engine's 20 because isolated tenants get more dedicated resource per connection).
- Metrics: `tenant_engine_pool_size{slug}` and `tenant_engine_pool_in_use{slug}` exported per tenant; alarms on `in_use / size > 0.8` per tenant.

### 9.2 Migration corruption

**Risk:** the cutover in Phase 4 flips the route to an isolated engine that has subtly-different data than the shared engine (replay drift, off-by-one seq, mid-flight ledger writes during replay). The new engine then becomes the source-of-truth with corrupted state.

**Mitigation:**

- Parallel-replay validator (§5.2) is a HARD blocker: cutover does not proceed without byte-identical replay over the validation window.
- Replay window covers a recent N days (default 7); shorter windows are configurable for early-stage tenants, longer for long-tenured tenants.
- During the replay window, writes to the shared engine continue. The replay tool reads `MAX(seq)` from shared at start, replays up to that seq, then loops: re-reads `MAX(seq)`, replays the new tail, until two consecutive iterations show zero new entries. This is a quiesce loop; the cutover then happens during a brief "freeze writes for this tenant" window (5-30 seconds).
- Documentation of the diff format (`projection_diffs` JSON Lines stream) makes failure mode debuggable.

### 9.3 Audit chain across engines

**Risk:** the ledger hash chain is per-tenant under Shape B (each engine has its own ledger table). A cross-tenant audit query (e.g. "show me every `agent_grant_revoked` across all tenants") today is a single SQL over the shared engine; under Shape B it becomes N queries across N engines.

**Mitigation:**

- Acknowledge: cross-tenant queries are **not** a first-class workload. They exist for platform admins / SOC-2 evidence collection / billing reconciliation.
- For those queries, the metadata projection on the shared engine (`projection_tenant_engines`) provides the engine list; an admin tool iterates engines.
- The hash chain remains intact *within* each tenant's ledger — that's the property that matters for tenant-level audit (which is the primary audit use case, and the SOC-2-relevant one).
- Document: cross-tenant ledger queries are an admin-tool concern, not a reader-Protocol concern.

### 9.4 Cost

**Risk:** each isolated Postgres has its own RDS / Aurora / Cloud SQL bill. Per-tenant cost rises from ~$0 (marginal compute on shared) to $X/month (dedicated instance).

**Mitigation:**

- Premium tier monetization (§2.5) is the explicit pricing surface. The customer pays for the dedicated infrastructure.
- Cost-per-tenant documented at design time: small-tier RDS (db.t4g.medium) ~$60/month, mid-tier (db.m6g.large) ~$140/month, before storage / backup / IOPS. These are reference numbers; the impl plan documents the then-current pricing.
- Cost is bounded by §9.1's max-N ceiling: at 20 tenants × $140/month, $2.8k/month additional infrastructure cost is the operational ceiling.

### 9.5 Operator complexity

**Risk:** Shape A had 1 DB to operate (monitor, back up, patch). Shape B has N. Operational surface area grows linearly with isolated-tenant count.

**Mitigation:**

- The max-N ceiling (§9.1) is the primary mitigation: 10-20 DBs is operable; 200 DBs is not.
- Provisioning automation is mandatory before scaling past 5 isolated tenants (Terraform module, Vault auto-rotation, etc.). The Phase 3 admin tool is the manual baseline.
- Per-tenant alerting reuses the existing alarms but multiplies by tenant count; standardize on a managed observability stack (Datadog / CloudWatch) before Shape B impl, not during.
- Backup / restore strategy: isolated engines participate in the same daily-snapshot policy as the shared engine, but a per-tenant restore is a per-tenant operation. The runbook documents this.

### 9.6 Embedding index per engine

**Risk:** the HNSW index from `v019_hnsw_index` (Path 1) is built per-engine. Each isolated engine has its own HNSW index over its own `projection_query_outcomes.embedding` column. No cross-engine vector search.

**Mitigation:**

- Acknowledge: cross-tenant semantic search is not a designed workload. The compounding-axis design is per-tenant by construction.
- Per-tenant HNSW indexes are smaller, build faster, search faster than a single shared index. This is actually a Shape-B *advantage*, not a risk — but it's documented as a deliberate property.

### 9.7 Replay-mode determinism under Shape B

**Risk:** wire-replay (per `CLAUDE.md §1.5`) is the substrate's determinism backstop. Under Shape B, replaying a recorded JSONL of `InfraEvent`s must still produce byte-identical ledger outputs — but now the replay engine has to know *which engine* to write each event's resulting ledger entries against.

**Mitigation:**

- The recorded JSONL includes the resolved `company_id` per event (already; this is Phase 4 of the existing channel-adapter normalization).
- Wire-replay reads `company_id` from the event, then looks up the tenant slug via the metadata projection, then writes to the corresponding engine via `TenantEngineRegistry.resolve_engine`.
- Tests: wire-replay over a recorded JSONL that spans multiple tenants produces byte-identical outputs on both shared and isolated engines.

---

## 10. What stays the same

The single most important Shape B property is **what does NOT change**.

### 10.1 Reader Protocols unchanged

`QueryOutcomeProjectionReader`, `LedgerDecisionReader`, `LedgerProcessMapReader`, `LedgerSubscriptionReader`, `LedgerDataProductReader`, `LedgerAgentGrantReader` — same signatures, same docstrings, same return shapes. Each takes an `engine` parameter; what changes is which engine is passed.

### 10.2 Compounding axes (Phase 1-3c) unchanged

All four compounding axes — outcome-to-template, query-rewrite-evolution, projection-promoted-gather, embedding-canonicalization — operate per-engine in Shape B exactly as they did per-shared-engine in Shape A. Each isolated tenant gets its own compounding loop; cross-tenant compounding is out of scope by design (no leakage between tenants).

### 10.3 Wire-replay determinism unchanged

Per §9.7. Wire-replay's determinism property is engine-routing-aware; per-tenant replays produce same outputs as live ingest did.

### 10.4 MCP tool surface unchanged (21 tools)

Tool names, argument shapes, return shapes — all identical. The only difference is which engine the tool reads/writes against. Identical to a customer's perspective.

### 10.5 Default deployment shape unchanged

Shape A is the default. New customers, all non-premium customers, every demo and pilot, every dev environment — Shape A. Shape B is opt-in per-tenant, and only when the trigger conditions in §2 fire.

### 10.6 KIND_REGISTRY discipline unchanged

One new kind (`tenant_engine_registered`) when Phase 2 ships. No reuse, no rename. Per the schema-evolution doctrine.

### 10.7 Optional-Effect Injection doctrine compliance preserved

Default `tenant_engine_registry=None` = Shape A behavior. Set the env knob = Shape B activation. This is the same shape as all 7 prior cases. The doctrine doesn't need amendment.

---

## 11. Optional-Effect Injection compliance

`TenantEngineRegistry` is the **8th case** of the Optional-Effect Injection doctrine (`docs/superpowers/specs/2026-05-21-optional-effect-injection-doctrine.md`).

### 11.1 Case enumeration after Shape B

1. v2.A `replay_mode: bool = False` — transport no-op in replay (Path 7 doctrine case 1)
2. v1.4 `LazyWebhookSecretResolver` — broker placeholder vs real (Path 7 doctrine case 2)
3. v2.B Phase 3b `EmbeddingService | None` — substring fallback when absent (Path 7 doctrine case 3)
4. v2.B Phase 3c `QueryOutcomeProjectionReader | None` — ledger-scan fallback when absent (Path 7 doctrine case 4)
5. **Wave 4** `TenantRouter | None` — single-tenant fallback when absent (Path 4 / `a0daffe`)
6. **Wave 5** `SseStreamTransport` — `T | None` + capability probe (Path 3 / `5a4c004`)
7. **Final wave #7** `LedgerQuotaTracker | None` — in-memory fallback (final wave / `c12389e`)
8. **Shape B** `TenantEngineRegistry | None` — single-engine fallback (this spec, impl-time)

### 11.2 Doctrine rule-by-rule compliance

| Rule | How Shape B complies |
|---|---|
| 1 — Default None preserves byte-identical behavior | `WORMBASE_ENGINE_PER_TENANT` unset → `tenant_engine_registry=None` → IsolatedTenantContext never constructed → readers compose against the shared engine exactly as today. |
| 2 — Fallback path is a documented public contract | "When `TenantEngineRegistry` is None, every tenant resolves to the shared engine via the existing single-engine code path (Shape A). All `WHERE company_id = $1` isolation continues to enforce correctness." Stated in module docstrings at impl time. |
| 3 — Tests assert BOTH paths | At impl time: `test_router_resolves_with_registry_returning_isolated`, `test_router_resolves_with_registry_returning_none`, `test_router_resolves_when_registry_is_none` (Shape A path). |
| 4 — Single env knob `WORMBASE_<X>_ENABLED` | `WORMBASE_ENGINE_PER_TENANT=true` (default OFF). Sub-tuning: `WORMBASE_TENANT_ENGINE_REGISTRY_IMPL`, `WORMBASE_TENANT_ENGINE_REGISTRY_PATH`, `WORMBASE_TENANT_ENGINE_POOL_SIZE`. |
| 5 — Env knob default is OFF | `os.environ.get("WORMBASE_ENGINE_PER_TENANT", "false").lower() == "true"` — only canonical `"true"` is ON. |
| 6 — Protocol or interface boundary | `TenantEngineRegistry` is a `Protocol`; consumers type-hint the Protocol, never the concrete impls. |
| 7 — Construction site is a factory | `build_tenant_engine_registry_from_env(...)` in `agent_gateway_construction.py`; the consumer takes `tenant_engine_registry: TenantEngineRegistry | None` as a parameter. |
| 8 — Wire-replay determinism across both paths | Per §9.7. Replay-mode side effects (network calls) are no-op'd in replay, just as in Shape A; the engine-routing decision is a pure function of the recorded event. |
| 9 — Telemetry distinguishes the two paths | `tool_calls_total{path}` where `path ∈ {"shape_a_shared", "shape_b_isolated"}`. Plus per-tenant pool metrics from §9.1. |
| 10 — Document optional service in module docstring | Both `tenancy.py` (Protocol + types) and `agent_gateway_construction.py` (wiring) get module-docstring entries naming the optional service and the fallback contract. |

### 11.3 Combination with Case 6's capability-probe pattern

Case 6 (Wave 5 SseStreamTransport) combined `T | None` injection with an inner `bool` capability probe. Shape B does NOT need the capability-probe inner pattern: `TenantEngineRegistry` returning `None` for an unknown slug is itself the fallback signal. The shape is the simple `T | None` injection (variant 2 in the doctrine §2 variants table). The doctrine does not need amendment to cover this case.

---

## 12. Open questions

These are deferred to implementation time. Each has a working answer; none requires re-design.

### 12.1 HNSW index interaction (v019)

**Q:** Does the HNSW index from `v019_hnsw_index` work across per-tenant engines?

**A:** Each engine has its own HNSW index over its own `projection_query_outcomes.embedding` column. No cross-engine vector search by design. Each tenant's compounding loop sees only its own embeddings — this is the *correct* semantic for the compounding axes (no cross-tenant leakage). Documented in §9.6.

### 12.2 `embedding-backfill --all-tenants` under Shape B

**Q:** Does the existing `embedding-backfill --all-tenants` CLI (`3de8886`) need to operate across engines?

**A:** Yes. At Shape B impl time, the CLI gets an additional `TenantEngineRegistry` parameter. The `--all-tenants` flag iterates the metadata projection's slug list, resolves each slug to its engine via the registry, and runs the backfill per engine. Same logic as today, parameterized by engine instead of running once against the shared engine.

The CLI's existing tests (multi-tenant safety, per-`--company-id` scoping) are extended at Shape B impl time to cover both Shape A and Shape B paths. Per the Optional-Effect Injection doctrine §3 Rule 3.

### 12.3 Does the doctrine need a 9th rule about "engine-bound services"?

**A:** Probably not. The existing 10 rules cover the engine-binding case without amendment:
- Rule 6 (Protocol boundary) — `TenantEngineRegistry` is a Protocol.
- Rule 7 (factory at the boundary) — `build_tenant_engine_registry_from_env`.
- Rule 8 (wire-replay determinism) — engine routing is a pure function of the recorded event.
- Rule 9 (telemetry distinguishes paths) — per-tenant pool metrics.

If implementation surfaces a recurring pattern around "services bound to a per-tenant engine handle" (e.g. Vault-backed engine-credential rotation, per-tenant migration runners, per-tenant projection-runners), then Rule 11 becomes a candidate. But that's a 9th-case observation, not a Shape-B-design decision.

### 12.4 Should Shape A → Shape B → Shape A migrate symmetrically?

**A:** Yes. The reverse migration (isolated → shared) is supported via:

1. `tenant-migrate-to-shared --slug=<slug>` admin tool.
2. Replays the isolated engine's ledger entries back into the shared engine.
3. Parallel-replay validator runs in reverse.
4. `tenant_engine_registered` is re-emitted with `engine_kind="shared"`.
5. The isolated engine is decommissioned.

Why support this: a tenant downgrading from premium tier, or a customer whose residency requirement lapses, or operational consolidation. Symmetric migration is the property that makes the trip reversible — and reversibility is a property of the substrate, not a feature.

### 12.5 Per-tenant projection-runner

**Q:** The projection runner today runs against the shared engine. Under Shape B, does each isolated tenant get its own projection-runner process, or does one process iterate engines?

**A:** One process iterates engines. The projection runner is a singleton today (one process, one engine); under Shape B, the singleton acquires a `TenantEngineRegistry` and iterates all known engines (shared + isolated) on each tick. Per-engine progress is tracked in a per-engine `projection_progress` table (already exists; no schema change).

If/when projection lag on isolated tenants becomes a bottleneck, the singleton can be sharded by tenant. Out of scope for Shape B v1.

### 12.6 Backup / restore strategy

**Q:** How are isolated engines backed up and restored?

**A:** Per the cloud provider's managed snapshot policy (RDS automated backups, Aurora continuous backup, etc.). Snapshots are per-engine, naturally per-tenant. Cross-tenant point-in-time-recovery is not a designed workload (would require coordinated snapshots across N engines). Documented at impl time in the runbook.

### 12.7 Multi-region

**Q:** If §2.1 (data-residency) drives Shape B for an EU tenant, does the agent-gateway process need to run in EU too?

**A:** The data-residency requirement applies to data-at-rest. The agent-gateway process can run anywhere as long as it doesn't persist tenant data outside the isolated engine's region. Network latency to the EU engine is the only operational cost (and a regional gateway colocation is the natural mitigation if latency becomes an issue).

For strict-interpretation residency (the compute also has to be in-region), a per-region agent-gateway deployment is the answer — orthogonal to Shape B's engine-routing design. Documented as a follow-up if needed.

### 12.8 Schema migration coordination

**Q:** When a new projection migration (e.g. `v021_*`) lands, how is it applied across all engines?

**A:** Migration runner iterates the engine list from the metadata projection at boot and applies migrations per-engine. Same migration-idempotence properties as today (already idempotent per-engine via `schema_migrations` version table). The only new concern is "what if migration succeeds on shared but fails on an isolated engine?" — answer: the migration runner exits non-zero with a per-engine failure summary; the operator addresses the failing engine; subsequent runs retry only the failing engines.

---

## 13. Authority

**Status:** DESIGN-ONLY. Approved by user "go" on 2026-05-13 final-wave dispatch.

**Implementation gated on:** concrete premium-tier customer demand surfacing as a named ask (per §2 trigger conditions).

**Owner of trigger evaluation:** the orchestrator. When a candidate trigger surfaces, the orchestrator:
1. Verifies the ask is concrete (named customer, named requirement, signed contract or LOI).
2. Confirms the trigger maps to one of §2.1-2.5.
3. Drafts an implementation plan that quotes this spec section-by-section.
4. Schedules Phase 1-3 (3-week impl) per §8.

**Status notes:** orchestrator-level close-out for "what conditions would activate this" lives at `docs/superpowers/notes/2026-05-22-engine-per-tenant-deferred.md`. This spec is the durable architectural artifact; that note is the deferred-state ledger entry.

**Cross-references:**

- `docs/superpowers/specs/2026-05-21-optional-effect-injection-doctrine.md` — the pattern this design follows (8th case)
- `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md` — ledger-kind addition compliance (Rule 1-5)
- `docs/superpowers/notes/2026-05-21-overnight-run-complete.md` §"Path 4" — Shape A rationale ("readers already do SQL-level `WHERE company_id = $1` isolation")
- `docs/superpowers/notes/2026-05-20-semantic-layer-v2.B-phase3c-shipped.md` §"build_projection_reader_from_ledger is the natural seam" — Phase 3c gestation of this design
- `apps/worm-core/src/wormbase_core/projection_readers.py` — the reader pattern Shape B inherits unchanged
- `packages/wormbase-agent-gateway/src/wormbase_agent_gateway/tenancy.py` — the Shape A tenancy module Shape B extends
- `apps/worm-core/src/wormbase_core/agent_gateway_construction.py` — the wiring layer Shape B extends with `build_tenant_engine_registry_from_env`

**Update rule:** this spec is updated only when (a) the trigger fires and impl starts (status flips to ACTIVE), (b) a follow-up architectural decision is made that changes one of the sections, or (c) the doctrine evolves in a way that invalidates a compliance claim in §11. Routine prose tightening is not an update event.

---

## Appendix A — Quick reference

**Trigger:** premium tenant asks for data-residency / physical-isolation / paid-tier resource ceiling.

**Time-to-impl from trigger:** 3 weeks (1 week Protocol, 1 week ledger + replay, 1 week admin tool + cutover).

**New env knob:** `WORMBASE_ENGINE_PER_TENANT=true` (default OFF).

**Sub-tuning:** `WORMBASE_TENANT_ENGINE_REGISTRY_IMPL` (default `static`), `WORMBASE_TENANT_ENGINE_REGISTRY_PATH`, `WORMBASE_TENANT_ENGINE_POOL_SIZE` (default 10).

**New ledger kind:** `tenant_engine_registered` (KIND_REGISTRY 105 → 106 at impl-time).

**New Protocol:** `TenantEngineRegistry.resolve_engine(slug) -> AsyncEngine | None`.

**New types:** `IsolatedTenantContext`, `PerTenantGatewayDepsCache`, `TenantEngineLifecycle`.

**New impls (v1):** `StaticTenantEngineRegistry`, `LedgerTenantEngineRegistry`.

**Doctrine compliance:** 8th case of Optional-Effect Injection, fully compliant.

**Default deployment unchanged:** Shape A is the default; Shape B is opt-in per tenant.

**Max isolated tenants (v1 ceiling):** 10-20, raised only after operational experience.

**Reversible:** yes — Shape B → Shape A migration is supported symmetrically.
