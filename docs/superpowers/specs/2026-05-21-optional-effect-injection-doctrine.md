# Optional-Effect Injection Doctrine

**Date:** 2026-05-21
**Status:** DOCTRINE — adopted 2026-05-21
**Scope:** Applies to all new architectural additions to WormBase that introduce a service or capability optional to the existing feature set.

This doctrine governs how WormBase introduces new side-effecting services (transports, resolvers, embedders, readers, …) without breaking byte-identical-default invariants, without resorting to global feature flags, and without coupling production composition to test scaffolding. Each new architectural addition that fits the pattern shape below must comply with the rules in §3.

---

## 1. Why this doctrine exists now

The semantic-layer build between 2026-05-16 and 2026-05-20 shipped **four phases** (v2.A, v1.4, v2.B Phase 3b, v2.B Phase 3c) that each introduced a new side-effecting service into an existing Reactivity / boot path. All four shipped **zero regressions** to prior assertions — Phase-1/2 tests stayed green, ASML demo arc stayed 6/6, KIND_REGISTRY drift stayed at zero, replay determinism stayed pinned.

The pattern responsible for that property is now visible in 4 separate production cases:

1. **v2.A wire-replay** — `ReactivityContext.replay_mode: bool = False` (transport no-op under replay)
2. **v1.4 webhook secret resolver** — `LazyWebhookSecretResolver` (real broker vs placeholder lambda)
3. **v2.B Phase 3b write-time embedding** — `EmbeddingService | None` (substring fallback when absent)
4. **v2.B Phase 3c projection-promoted gather** — `QueryOutcomeProjectionReader | None` (ledger-scan fallback when absent)

The Phase 3c close-out (`docs/superpowers/notes/2026-05-20-semantic-layer-v2.B-phase3c-shipped.md` §3) called this out:

> The pattern is what makes the byte-identical-default invariant survive otherwise-disruptive architectural additions. Each phase adds capability without breaking prior assertions. The compounding layer's velocity is materially attributable to this pattern.

**Without a doctrine, this pattern erodes into ad-hoc variants within ~2-3 more waves.** Some teams will reach for hard dependencies, others for hidden global state, others for big-bang migrations. The four cases above already differ slightly in surface shape (boolean vs Protocol vs `T | None`); without doctrine, drift compounds.

This spec formalizes the pattern so that the next four phases can compose on top of it deliberately.

---

## 2. Pattern shape

The canonical Optional-Effect Injection shape:

```python
# 1. Define a Protocol or interface boundary (not a concrete class)
class FooService(Protocol):
    async def do_foo(self, x: X) -> Y: ...

# 2. Accept Optional[FooService] in the consumer's constructor / factory
def make_consumer(
    *,
    foo_service: FooService | None = None,
    # ... other dependencies ...
) -> Consumer:
    return Consumer(foo_service=foo_service, ...)

# 3. Branch at the consumer's call site
class Consumer:
    async def handle(self, entry):
        if self.foo_service is not None:
            y = await self.foo_service.do_foo(entry.x)
            self._write_with_foo(entry, y)
        else:
            self._write_without_foo(entry)  # fallback path — documented public contract

# 4. Production composes the real service via a single env knob
def is_foo_enabled() -> bool:
    return os.environ.get("WORMBASE_FOO_ENABLED", "false").lower() == "true"

def build_foo_service_from_ledger(ledger, ...) -> FooService | None:
    if not is_foo_enabled():
        return None
    return RealFooService(...)

# 5. Boot composition is opt-in (default None → fallback active)
async def boot():
    foo = build_foo_service_from_ledger(ledger)  # → None by default
    consumer = make_consumer(foo_service=foo)
    # If WORMBASE_FOO_ENABLED=true, real service flows through; otherwise fallback path.

# 6. Tests pin BOTH paths
def test_consumer_with_foo_service():
    consumer = make_consumer(foo_service=FakeFooService())
    # assert side effects of with-foo path

def test_consumer_without_foo_service():
    consumer = make_consumer(foo_service=None)
    # assert fallback path produces correct (different but valid) output
```

Variants observed in the 4 cases (all canonical):

| Variant | Example | When |
|---|---|---|
| `bool = False` switch | `replay_mode: bool = False` | Single behavioral toggle on an existing service; no new service shape needed |
| `T \| None = None` injection | `EmbeddingService \| None`, `QueryOutcomeProjectionReader \| None` | New service with a Protocol boundary; absence is meaningful |
| Lazy resolver with internal `broker=None` | `LazyWebhookSecretResolver(broker=None)` | Service constructed early in boot before its dependency is available; late-bind the dependency |

All three variants satisfy the doctrine. The Protocol/None form is the most common; the boolean and lazy-resolver forms are valid where they fit.

---

## 3. Rules

### Rule 1 — Default None (or False) preserves byte-identical behavior

The fallback path is the default. A boot that composes the consumer with no env knobs set MUST produce identical ledger entries, identical projection rows, identical observable side effects to the pre-introduction state.

**Why:** new architectural additions must not silently change pre-existing tests, demos, or pilot-customer behavior. Opt-in is the contract.

**How to apply:** every new `WORMBASE_<X>_ENABLED` knob defaults to `false`. The consumer's constructor parameter defaults to `None` (or `False`). The byte-identical assertion is verified by running the full ASML demo arc and the consumer-package test suite with the knob unset; if any test fails, the fallback path is not byte-identical and the implementation is wrong.

### Rule 2 — The fallback path is a documented public contract

The fallback path is NOT "TODO," NOT "stub," NOT "best-effort." It is a real, supported behavior that the consumer maintains across versions.

**Why:** Optional-Effect Injection's payoff is that the fallback path is *also* shippable. If the fallback degrades silently or fails opaquely, the pattern collapses into a hidden-feature-flag pattern (fragile and untestable).

**How to apply:** the fallback path has its own docstring on the consumer method, its own tests (Rule 3), and is referenced from the consumer's module docstring. If the consumer cannot articulate "what happens when foo_service is None" in one sentence, the fallback path is not yet a contract.

Examples from the 4 cases:
- v2.A: "When replay_mode is True, the dispatcher still writes `agent_event_delivered` deterministically; the network transport is no-op."
- v1.4: "When the broker is unbound, the LazyWebhookSecretResolver returns a placeholder lambda that raises on `await`; production callers MUST bind the broker before the first delivery." (This is the most edge-case-y of the four; the contract is "fail loudly if no one bound the broker," not "silently degrade.")
- v2.B Phase 3b: "When the EmbeddingService is None, the write lands with `embedding=None`; downstream cluster_fn falls back to substring canonicalization for that entry."
- v2.B Phase 3c: "When the projection_reader is None, axes 1+3 gather candidates by scanning the ledger via `ctx.ledger.fetch(company_id)` (the Phase 1+2 path)."

### Rule 3 — Tests assert BOTH paths

For every Optional-Effect Injection, the test suite contains at least one test for each of:
1. Consumer behavior with the real service injected (or a fake implementing the Protocol)
2. Consumer behavior with `None` / `False` — the fallback path
3. Wire-replay determinism: replaying a recorded ledger that mixes both modes produces deterministic output (when applicable to the consumer)

**Why:** the pattern's safety property is "neither path silently regresses." That property only holds if both paths are exercised on every test run.

**How to apply:** parametrize fixtures or write paired test cases. Naming convention: `test_<consumer>_with_<service>` and `test_<consumer>_without_<service>`. Replay tests follow `test_<consumer>_replay_<scenario>`.

Examples from the 4 cases:
- v2.A: `test_replay_mode_no_op_transport`, `test_replay_mode_deterministic`, `test_replay_mode_preserves_idempotency`
- v1.4: `test_lazy_resolves_env_ref`, `test_lazy_resolves_vault_ref`, `test_late_binds_broker`, `test_raises_on_unbound_resolve`
- v2.B Phase 3b: `test_axis1_backward_compat_substring_fallback`, `test_axis3_backward_compat_substring_fallback`, `test_embedding_field_round_trips_through_ledger`
- v2.B Phase 3c: `test_projection_reader_topk_with_embedding`, `test_projection_reader_falls_back_to_ledger_scan_without_embedding`, integration tests in `test_projection_promoted_gather.py` cover both `projection_reader=None` and `projection_reader=...` cases

### Rule 4 — Production opt-in is via a single env knob with the `WORMBASE_` prefix

Each Optional-Effect Injection gets exactly one boolean env knob to enable production composition:

| Pattern | Env knob example | Default |
|---|---|---|
| Capability gate | `WORMBASE_SUBSCRIPTIONS_ENABLED` | `false` |
| Capability gate | `WORMBASE_EMBEDDING_ENABLED` | `false` |
| Capability gate | `WORMBASE_GATHER_VIA_PROJECTION` | `false` |
| Sub-tuning of an enabled capability | `WORMBASE_SUBSCRIPTIONS_WEBHOOK_TIMEOUT_S` | `10` |

**Why:** one knob per capability keeps composition tractable. Multiple knobs per capability invite combinatoric matrices that nobody tests.

**How to apply:** the env knob is read by a single `is_<feature>_enabled()` helper in the consumer's app-level construction module (e.g. `apps/worm-core/src/wormbase_core/agent_gateway_construction.py`). The helper is the only place that consults the environment. The consumer itself takes the resolved Optional[T] parameter — never reads env vars directly.

Sub-tuning knobs (timeout, retry count, threshold) are permitted but ONLY meaningful when the primary capability knob is `true`. They have safe defaults.

### Rule 5 — Env knob default is OFF

`WORMBASE_<X>_ENABLED=true` is the active opt-in. Any other value (unset, `"false"`, `"0"`, `""`) is OFF.

**Why:** safe default. Opt-in is the contract; unset must always mean fallback.

**How to apply:** `os.environ.get("WORMBASE_<X>_ENABLED", "false").lower() == "true"`. No alternative truthy values are honored. `"yes"`, `"1"`, `"on"` are all treated as OFF (defensive — anything other than the canonical `"true"` is suspect input).

### Rule 6 — The injected service has a Protocol or interface boundary

The service consumed by the consumer is a Python `Protocol`, an `abc.ABC`, or an equivalent interface. The consumer never imports a concrete class.

**Why:** the Optional-Effect Injection's reusability depends on the boundary. Tests inject fakes. Production injects real impls. Future implementations (vLAN-hosted variants, alternative backends) slot in without consumer changes.

**How to apply:** define the Protocol in the package that owns the consumer or in a shared infrastructure package (e.g. `wormbase_inference.embedding.EmbeddingService` in `packages/inference-router`). Concrete implementations live next to the Protocol or in app-level construction modules. The consumer type-hints the Protocol, not the concrete.

Variants:
- `EmbeddingService` Protocol → `OllamaCloudEmbeddingService` concrete
- `QueryOutcomeProjectionReader` Protocol → `PostgresQueryOutcomeProjectionReader` + `SqliteQueryOutcomeProjectionReader` concretes
- `WebhookSecretResolver` Protocol → `LazyWebhookSecretResolver` concrete (note: even the resolver itself is named via behavior, not by what backs it)

### Rule 7 — Construction site is a factory at the boundary between app and package

The Optional[T] enters the consumer via a factory function at the package's public surface, not via a hard-coded construction.

**Why:** package code stays composable; app code owns the wiring decisions. The factory signature is the contract; what app composition does with it is replaceable.

**How to apply:**

```python
# In packages/<name>/src/<name>/reactivities.py
def make_foo_reactivities(
    *,
    foo_service: FooService | None = None,
) -> list[Reactivity]:
    ...

# In apps/worm-core/src/wormbase_core/<feature>_construction.py
def build_foo_service_from_ledger(ledger, ...) -> FooService | None:
    if not is_foo_enabled():
        return None
    return RealFooService(...)

# In apps/worm-core/src/wormbase_core/cli.py
foo = build_foo_service_from_ledger(ledger)
reactivities = make_foo_reactivities(foo_service=foo)
```

The package never imports the app. The app imports the package. Composition flows app → package via factory parameters.

### Rule 8 — Wire-replay determinism is preserved across both paths

When the consumer participates in a Reactivity that gets wire-replayed, both the with-service and without-service paths must produce deterministic output under replay.

**Why:** wire-replay is the substrate's determinism backstop (per `CLAUDE.md §1`). An Optional-Effect Injection that breaks replay determinism breaks the substrate's central commitment.

**How to apply:**
- Side effects that are not deterministic functions of the ledger (network calls, wall-clock reads, random IDs) MUST be guarded by the `replay_mode` flag or equivalent
- Ledger writes inside the consumer remain deterministic under both paths
- Tests in `test_<consumer>_replay_*` verify that replaying a recorded ledger twice produces byte-identical observable output (modulo the explicitly-no-op'd side effects)

Cross-reference: v2.A's `replay_mode` is itself an instance of Optional-Effect Injection (Case 1), AND it's the mechanism Rule 8 leans on. The two ideas reinforce each other.

### Rule 9 — Telemetry distinguishes the two paths

Production observability MUST be able to answer "what fraction of fires hit the with-service path vs the fallback path?"

**Why:** without this telemetry, the team cannot answer "is the env knob actually doing anything in production?" or "is the fallback path silently swallowing what should be real work?"

**How to apply:**
- Counter metrics like `consumer_fires_with_service_total{consumer}` and `consumer_fires_with_fallback_total{consumer}`
- OR a single counter with a label: `consumer_fires_total{consumer, path}` where `path ∈ {"with_service", "fallback"}`
- The labels stay stable across env-knob flips; flipping the knob shifts which counter increments

This telemetry obligation is in addition to standard Reactivity telemetry (PEVR cycle duration, projection lag, etc. per `2026-05-03-schema-evolution-doctrine.md §7`).

### Rule 10 — Document the optional service in the consumer's module docstring

The consumer's top-of-module docstring names the optional service, what its presence enables, and what its absence falls back to.

**Why:** discoverability. A new contributor reading the consumer should not need to grep for `is None` branches to discover that an Optional-Effect Injection is in play.

**How to apply:**

```python
"""Compounding axis for template promotion.

This module accepts an optional :class:`EmbeddingService` for write-time
embedding generation. When the service is injected (composed via
``WORMBASE_EMBEDDING_ENABLED=true`` in the app layer), entries gain
``embedding`` payload fields and downstream cluster_fn uses cosine
similarity. When the service is absent, entries carry ``embedding=None``
and cluster_fn falls back to substring canonicalization.

Both paths are byte-identical under replay.
"""
```

---

## 4. The 4 cases (detailed)

### Case 1 — v2.A wire-replay (`replay_mode: bool = False`)

**Shipped:** 2026-05-17 in `35b2191` (Tasks 3+4+5+6 of v2.A plan).

**Shape:** a boolean field on `ReactivityContext` that the SubscriptionDispatcher reads to decide whether to actually execute side effects.

```python
# packages/reactivities/src/wormbase_reactivities/context.py
class ReactivityContext:
    ...
    replay_mode: bool = False  # additive field per schema-evolution doctrine Rule 2

# packages/wormbase-agent-gateway/src/wormbase_agent_gateway/dispatcher.py
class SubscriptionDispatcher:
    async def fire(self, ctx: ReactivityContext, entry: LedgerEntry) -> None:
        # ... matching + idempotency + agent_event_delivered ledger write happens always ...
        if ctx.replay_mode:
            return  # no-op the transport — fallback path
        await self.transport.deliver(entry, subscription)
```

**Presence (replay_mode=True):** transport side effect skipped; ledger write still happens.

**Absence (replay_mode=False, default):** live transport runs.

**Env knob:** none (this is a Reactivity-context property, not a production capability gate). Wire-replay tool sets `replay_mode=True` in its ReactivityContext construction.

**Tests:** `test_subscription_wire_replay.py::test_replay_mode_no_op_transport`, `test_replay_mode_deterministic`, `test_replay_mode_preserves_idempotency`.

**Why Optional-Effect Injection:** the dispatcher's behavior with `replay_mode=False` is the production behavior. With `replay_mode=True`, the network side effect is replaced by a no-op fallback that preserves all ledger-resident state. Both are documented contracts.

### Case 2 — v1.4 webhook secret resolver (`LazyWebhookSecretResolver`)

**Shipped:** 2026-05-18 in `1af126d` (Item #3 of v1.4 polish bundle).

**Shape:** a resolver class with an internal `broker: CredentialBroker | None = None` that gets late-bound after build-smoke.

```python
# apps/worm-core/src/wormbase_core/webhook_secret_resolver.py
class LazyWebhookSecretResolver:
    """Resolves secret_ref → secret at delivery time, not at boot."""

    def __init__(self, broker: CredentialBroker | None = None):
        self._broker = broker

    def bind_broker(self, broker: CredentialBroker) -> None:
        self._broker = broker

    async def resolve(self, secret_ref: str) -> str:
        if self._broker is None:
            raise RuntimeError(
                "LazyWebhookSecretResolver: broker not bound at resolve time. "
                "Did you forget to call bind_broker() during boot?"
            )
        return await self._broker.resolve(secret_ref)
```

**Presence (broker bound):** real secret resolution against env:// or vault:// refs.

**Absence (broker unbound):** raises a loud RuntimeError on first resolve. NOT a silent placeholder.

**Env knob:** `WORMBASE_SUBSCRIPTIONS_ENABLED=true` (the broker is only bound when the surrounding capability is enabled).

**Tests:** `apps/worm-core/tests/test_lazy_webhook_secret_resolver.py` (11 tests covering env://, vault://, late-binding, async-await, and the unbound-raises case).

**Why Optional-Effect Injection:** the resolver is constructible before the broker exists, satisfying the boot-ordering constraint. The "absence" path is loud failure, not silent degradation — which is a valid fallback contract when silent degradation would be more dangerous than failing fast (Rule 2 + "When NOT to apply" §5 — the absence-behavior must be worse than failing fast in some other variants; here it's safer to fail loudly because a webhook with an unresolved secret would be a security incident).

### Case 3 — v2.B Phase 3b write-time embedding (`EmbeddingService | None`)

**Shipped:** 2026-05-19 in `1ad8163`, `3a2878e`, `28a12d9`, `0392162`.

**Shape:** an optional `EmbeddingService` injected at the MCP-tool-construction site.

```python
# packages/inference-router/src/wormbase_inference/embedding.py
class EmbeddingService(Protocol):
    async def embed(self, text: str) -> EmbeddingResult: ...

class OllamaCloudEmbeddingService(EmbeddingService):
    ...  # production implementation

# apps/worm-core/src/wormbase_core/tools_compounding.py
async def lake_query_record_outcome(
    args: ...,
    *,
    embedding_service: EmbeddingService | None = None,
    ...
):
    embedding = None
    if embedding_service is not None:
        try:
            result = await embedding_service.embed(args.nl_question)
            embedding = result.vector
        except Exception:
            # best-effort: write lands without embedding; cluster_fn falls back
            pass

    await ledger.write(emit_query_outcome_recorded(
        ...,
        embedding=embedding,  # None or list[float]
    ))

# packages/wormbase-agent-gateway/src/wormbase_agent_gateway/reactivities.py
def _make_hybrid_cluster_fn(threshold: float):
    def cluster(entries):
        embedded = [e for e in entries if e.payload.embedding is not None]
        non_embedded = [e for e in entries if e.payload.embedding is None]
        return (
            _cluster_by_embedding_similarity(embedded, threshold)
            + _cluster_by_substring(non_embedded)
        )
    return cluster
```

**Presence (`EmbeddingService` injected):** write-time embedding populated; downstream cluster_fn uses cosine similarity.

**Absence (None):** `embedding` field stays None; downstream cluster_fn falls back to substring canonicalization (the Phase 1+2 behavior).

**Env knob:** `WORMBASE_EMBEDDING_ENABLED=true`.

**Tests:** `test_axis1_backward_compat_substring_fallback`, `test_axis3_backward_compat_substring_fallback`, `test_embedding_field_round_trips_through_ledger`, 12 embedding service tests, 15 cosine clustering tests.

**Why Optional-Effect Injection:** the embedding capability is sufficient (better clustering) but not necessary (substring clustering is a complete contract). Tests pin both. Production deployments enable progressively without breaking pre-3b ledgers.

### Case 4 — v2.B Phase 3c projection-promoted gather (`QueryOutcomeProjectionReader | None`)

**Shipped:** 2026-05-20 in `a01dc73`.

**Shape:** an optional `QueryOutcomeProjectionReader` injected at the Reactivity-factory site, with a dialect-aware concrete builder.

```python
# apps/worm-core/src/wormbase_core/projection_readers.py
class QueryOutcomeProjectionReader(Protocol):
    async def topk_by_embedding(
        self, company_id: str, embedding: list[float], k: int
    ) -> list[QueryOutcomeRow]: ...
    async def all_for_company(self, company_id: str) -> list[QueryOutcomeRow]: ...

class PostgresQueryOutcomeProjectionReader(QueryOutcomeProjectionReader):
    # pgvector <=> cosine TopK with day-window pre-filter
    ...

class SqliteQueryOutcomeProjectionReader(QueryOutcomeProjectionReader):
    # Python cosine fallback for SQLite
    ...

def make_projection_reader_for_engine(engine) -> QueryOutcomeProjectionReader:
    if engine.dialect.name == "postgresql":
        return PostgresQueryOutcomeProjectionReader(engine)
    return SqliteQueryOutcomeProjectionReader(engine)

# packages/wormbase-agent-gateway/src/wormbase_agent_gateway/reactivities.py
def make_agent_gateway_reactivities(
    *,
    projection_reader: QueryOutcomeProjectionReader | None = None,
    ...
) -> list[Reactivity]:
    gather = _make_gather_via_projection(projection_reader) if projection_reader else None
    return [
        make_outcome_to_template_promotion_reactivity(gather_fn=gather),
        make_query_failure_to_bad_pattern_reactivity(gather_fn=gather),
        ...
    ]
```

**Presence (`QueryOutcomeProjectionReader` injected):** axes 1+3 read candidates via SQL TopK with pgvector cosine (PG) or Python cosine (SQLite).

**Absence (None):** axes 1+3 fall back to `ctx.ledger.fetch(company_id)` ledger scan (the Phase 1+2+3b path).

**Env knob:** `WORMBASE_GATHER_VIA_PROJECTION=true`.

**Tests:** `test_query_outcome_projection_reader.py` (9 reader correctness tests), `test_projection_promoted_gather.py` (8 integration tests covering both paths).

**Why Optional-Effect Injection:** the projection reader is the hot-path optimization (production-scale unblock at 10K+ outcomes/company). At pilot-stage scale, the ledger-scan path is acceptable. Tests pin both; production opts in via env knob.

---

## 5. When to apply

Decision tree for whether a new architectural addition warrants Optional-Effect Injection:

```
New service / capability being added?
│
├── Is the existing feature still meaningfully functional without it?
│   │
│   ├── NO → Hard dependency. Construct in the consumer's constructor.
│   │        Do NOT use Optional-Effect Injection. (Examples: ledger,
│   │        reactivity-registry, identity-resolver — these are core.)
│   │
│   └── YES → continue
│
├── Does the fallback path produce a different but valid contract?
│   │
│   ├── NO (fallback is "TODO" / "stub" / "raise") → Either:
│   │   (a) Apply Optional-Effect Injection with explicit "loud failure"
│   │       fallback contract (Case 2 shape — LazyWebhookSecretResolver)
│   │   (b) Defer the introduction until the fallback is real
│   │
│   └── YES → continue
│
├── Will the with-service path eventually be the production default?
│   │
│   ├── YES, soon (next 1-2 waves) → Optional-Effect Injection is the bridge.
│   │   Plan the OFF→ON migration in the spec.
│   │
│   └── NO, this is a permanent variant (tenant choice, deployment-mode
│       choice) → Optional-Effect Injection is the steady state. The env
│       knob is a permanent configuration surface, not a migration tool.
│
└── Apply Optional-Effect Injection per rules in §3.
```

**Heuristics:**
- New write-time side effect on an existing Reactivity? → Almost always Optional-Effect Injection.
- New read-side optimization that changes performance but not semantics? → Optional-Effect Injection.
- New transport / protocol that supplements an existing one? → Optional-Effect Injection.
- New core substrate (ledger, reactivity registry, KIND_REGISTRY)? → Hard dependency, not Optional-Effect Injection.
- New gate that prevents writes when it fails? → Hard dependency (gate must always run); not Optional-Effect Injection.

---

## 6. When NOT to apply

Optional-Effect Injection has costs (an extra indirection, two test paths, a documented fallback contract). The pattern is wrong when:

### 6.1 The fallback path is itself complex

If implementing "what happens when foo_service is None" requires more code than the with-service path, you have two implementations of the feature, not one feature with an optional acceleration. Pick one and commit.

**Example NOT to apply:** "Optional MultiTenantRouter" where the absence path would require implementing a single-tenant emulation layer. That's two products. Just ship one.

### 6.2 The service is core-required

If the absence of the service makes the surrounding feature semantically wrong (not just slower or less-clustered), it's a hard dependency. Forcing it through Optional-Effect Injection invites consumers to compose with `None` and produce subtly wrong output.

**Example NOT to apply:** the IdentityResolver (per `CLAUDE.md §1.5 Rules for new worm work`, "IdentityResolver is the only shared Protocol that downstream worms consume; instances come from the hub"). Identity resolution is required for every Person-related write. There is no valid "without IdentityResolver" path.

### 6.3 The absence-behavior would be worse than failing fast

If silently falling back would produce data corruption, security issues, or audit-trail gaps, the pattern is wrong. Either:
- Make the dependency required (Rule 6.2 NOT-to-apply), OR
- Apply Optional-Effect Injection with a **loud failure** fallback contract (Case 2 shape — LazyWebhookSecretResolver raises rather than silently using a placeholder secret)

The doctrine accepts loud-failure fallbacks; it does not accept silent-corruption fallbacks.

### 6.4 The capability is a tenant-wide policy, not a per-call composition

If the capability is a customer-config-level decision ("this tenant uses webhook delivery, that tenant uses MCP stream"), it belongs in tenant configuration / governance, not in env-knob-gated boot composition. Optional-Effect Injection is for capabilities that opt-in at the deployment level, not the tenant level.

**Future doctrine boundary:** when multi-tenant SaaS ships (per `CLAUDE.md §11` and Phase 3c's carry-forward #3), per-tenant capability flags will not use the `WORMBASE_<X>_ENABLED` env-knob pattern. They will use a tenant-resolved configuration table. The Optional-Effect Injection pattern at the consumer's signature stays — only the source of the Optional[T] changes from env-knob-resolution to tenant-config-resolution.

### 6.5 Feature flags for A/B testing or gradual rollout

Optional-Effect Injection is NOT a feature flagging system. If the goal is "10% of tenants get this feature this week, 25% next week," use a feature-flag library with telemetry, not env-knob-gated composition. Optional-Effect Injection assumes binary opt-in at the deployment level.

---

## 7. Migration guide for retroactive adoption

When an existing required service grows a need to be optional (e.g. a new deployment mode, a test path that needs to compose without it), the conversion is:

### Step 1 — Add a Protocol boundary

If the existing service is consumed via a concrete class, introduce a Protocol that captures the surface area the consumer actually uses. Update the consumer's type hints to the Protocol. Keep the concrete class as the production implementation.

```python
# Before
class Consumer:
    def __init__(self, real_service: ConcreteFooService):
        self._foo = real_service

# After
class FooService(Protocol):
    async def do_foo(self, x: X) -> Y: ...

class ConcreteFooService(FooService):
    ...  # existing impl

class Consumer:
    def __init__(self, foo_service: FooService):
        self._foo = foo_service
```

### Step 2 — Widen the parameter to `Optional[T]`

```python
class Consumer:
    def __init__(self, foo_service: FooService | None = None):
        self._foo = foo_service
```

### Step 3 — Implement the fallback path

This is where the doctrine work actually happens. Decide:
- What does the consumer do when `_foo is None`?
- Is the fallback a no-op, a degraded alternative, or a loud failure?
- Document the fallback contract in the consumer's docstring (Rule 10).

```python
class Consumer:
    async def handle(self, entry):
        if self._foo is not None:
            return await self._with_foo(entry)
        return await self._without_foo(entry)  # NEW fallback path

    async def _without_foo(self, entry):
        # Documented fallback contract here.
        ...
```

### Step 4 — Pin both paths with tests

Add `test_consumer_without_foo_service` cases. Make sure they cover the same observable invariants as the existing tests (which now become the with-foo-service cases).

### Step 5 — Add the env knob

```python
# apps/worm-core/src/wormbase_core/<feature>_construction.py
def is_foo_enabled() -> bool:
    return os.environ.get("WORMBASE_FOO_ENABLED", "false").lower() == "true"

def build_foo_service(...) -> FooService | None:
    if not is_foo_enabled():
        return None
    return ConcreteFooService(...)
```

### Step 6 — Verify byte-identical default

Run the full test suite + ASML demo arc with `WORMBASE_FOO_ENABLED` unset. All prior assertions must still pass. If any fail, the fallback path is not byte-identical and Step 3 needs more work.

### Step 7 — Update consumer docstring (Rule 10)

The migration is complete only when a new contributor reading the consumer's module docstring can identify that Optional-Effect Injection is in play and what the fallback contract is.

**Reverse migration (Optional → Required):** if an optional service becomes universally adopted and the fallback path is no longer wanted, the reverse is also possible: change `Optional[T] = None` to `T` (required), remove the fallback path, delete the `WORMBASE_<X>_ENABLED` knob (or make it permanently-on with a deprecation note). This is a breaking change to consumers that composed with `None`; coordinate with a major-version boundary.

---

## 8. Relationship to other doctrines

### 8.1 Schema-evolution doctrine

The schema-evolution doctrine (`2026-05-03-schema-evolution-doctrine.md`) governs how ledger entry kinds and projection schemas evolve. Optional-Effect Injection is the **runtime counterpart**.

| Doctrine | Governs | Mechanism |
|---|---|---|
| Schema evolution | Persistent state shape | Rules 1-5 on entry kinds + projection columns |
| Optional-Effect Injection | Runtime side-effect composition | Rules 1-10 on consumer signatures + env knobs |

Both share the principle "additive-only preserves replay determinism." The schema rule lets you add fields to ledger entries without breaking historical replay; the injection rule lets you add services to the runtime without breaking pre-existing test assertions or composing-without-the-service deployments.

Cross-references:
- Phase 3b added an `embedding: list[float] | None = None` field to `QueryOutcomeRecordedPayload` (schema-evolution Rule 2) AND added the `EmbeddingService | None` injection (this doctrine Case 3). The two rules compose: the field is additive at the persistence layer, the service is optional at the runtime layer, and both default-paths preserve byte-identical behavior.
- Phase 3c added zero schema changes (schema-evolution N/A) and added the `QueryOutcomeProjectionReader | None` injection (this doctrine Case 4). Pure runtime-layer pattern, no schema move needed.

### 8.2 Wire-replay determinism

Optional-Effect Injection IS the mechanism by which wire-replay determinism is preserved when side-effecting services join the runtime. Case 1 (replay_mode) is the canonical example: the dispatcher's transport is no-op'd under replay, but the ledger writes are deterministic.

Without Optional-Effect Injection, every new side-effecting service would either:
- Refuse to run under replay (fragile, requires replay-aware coding in every new service)
- Run side effects under replay (breaks the replay contract — production webhooks fired during a replay would be a security incident)
- Need a separate replay-aware variant (code duplication)

Optional-Effect Injection's Rule 8 codifies the pattern: "when the consumer participates in a Reactivity that gets wire-replayed, both paths must produce deterministic output." This works because the with-service path's non-determinism is gated by `replay_mode`, and the without-service path is deterministic by construction (no service, no side effect).

### 8.3 The "production-like posture" principle (`CLAUDE.md §1`)

`CLAUDE.md §1` requires that demo and production share one code path: "The demo environment and the pilot-customer environment share one code path." Optional-Effect Injection is consistent with this principle: the consumer's code path is identical in both modes; the difference is which `Optional[T]` is wired in.

Demos compose without the env knob (fallback path). Pilots compose with the env knob (with-service path). Both run the same consumer code. No demo-only shortcut, no fixture-load bypass.

### 8.4 Compounding query layer (semantic-layer master spec §4.5)

The semantic-layer master spec at `docs/superpowers/specs/2026-05-10-semantic-layer-design.md` §4.5 sketches the compounding query layer. Optional-Effect Injection is the pattern that lets §4.5 ship in **incremental phases** without each phase rewriting prior assertions:

- Phase 1+2: compounding axes ship with substring clustering
- Phase 3b: adds embedding-similarity clustering as an Optional-Effect Injection (Case 3); substring stays as the fallback
- Phase 3c: adds projection-promoted gather as an Optional-Effect Injection (Case 4); ledger-scan stays as the fallback

A future Phase 4 might add `MultiTenantProjectionRouter | None` (the carry-forward #3 from Phase 3c) as a 5th Optional-Effect Injection. The doctrine here is the template.

---

## 9. Open questions / future cases to watch

The doctrine is adopted on the basis of 4 production cases. The following are watch-list candidates for the 5th case; each will validate or refine the doctrine.

### 9.1 Multi-tenant projection routing (highest-probability 5th case)

Per Phase 3c's carry-forward #3 (`docs/superpowers/notes/2026-05-20-semantic-layer-v2.B-phase3c-shipped.md`):

> Multi-tenant routing — single-engine assumption today; future tenant-router-resolved engine swap. `build_projection_reader_from_ledger` is the natural seam.

The shape would be:

```python
class TenantEngineRouter(Protocol):
    def resolve_engine_for(self, company_id: str) -> Engine: ...

def build_projection_reader_from_ledger(
    ledger,
    *,
    tenant_router: TenantEngineRouter | None = None,
    ...
) -> QueryOutcomeProjectionReader | None:
    if not is_gather_via_projection_enabled():
        return None
    if tenant_router is None:
        # Fallback: single-engine assumption (current behavior)
        return make_projection_reader_for_engine(ledger.engine)
    # With-service: per-call tenant-resolved engine
    return TenantRoutedProjectionReader(tenant_router, ...)
```

If this lands, it adds Case 5 with env knob `WORMBASE_TENANT_ROUTING_ENABLED=true` and validates the doctrine across two levels (a Reactivity that already participates in Optional-Effect Injection now hosts a second-order Optional-Effect Injection inside its builder).

**Doctrine question:** when an Optional-Effect Injection's builder itself accepts an Optional[T], is the inner injection bound by the same rules? Probable answer: yes, but the doctrine may need to clarify recursive composition explicitly when the 5th case lands.

### 9.2 SSE transport upgrade for MCP stream

Per v2.A carry-forward #1 (`docs/superpowers/notes/2026-05-17-semantic-layer-v2.A-shipped.md`):

> MCP stream is list-collected, not true SSE — FastMCP version-compat concern. Upgrade for real-time clients in v2.

A `SSEStreamTransport | None` injection that defaults to the current list-collected fallback would fit the doctrine. Env knob: `WORMBASE_MCP_SSE_ENABLED=true`. Watch-list as the 6th case.

### 9.3 Dashboard accessor variants (lower-confidence candidate)

The "optional projection readers" and "optional dashboard accessors" mentioned in `2026-05-19-semantic-layer-v2.B-phase3b-shipped.md` §3 are speculative. If a dashboard surface starts accepting an `Optional[AccessorVariant]` to swap between read modes, that's a 7th case candidate.

### 9.4 Cache-namespace-strict embedding service

The Phase 3b carry-forward #2 ("Tenancy-strict cache namespacing in `OllamaCloudEmbeddingService._EmbeddingCache`") suggests that some Optional-Effect Injections may grow internal-state-related Optional[T]s of their own (e.g. `Optional[TenancyCacheKeyer]`). Future case watch.

### 9.5 Vault resolver

The `LazyWebhookSecretResolver` is Case 2. A future Vault-backed `Optional[VaultResolver]` for other secret types (DB passwords, API tokens) would follow the same lazy-resolver shape. Likely subsumed under the existing CredentialBroker rather than spawning a new Optional-Effect Injection — but worth watching.

---

## Addendum 1 — Case 6: StreamTransport for ``agent.subscriptions.stream`` (2026-05-21, Path 3)

**Status:** ACCEPTED — added 2026-05-21 with the v2.A Phase 2 / Path 3 commit on the overnight roadmap.

The MCP ``agent.subscriptions.stream`` tool (v2.A Batch B, commit `35b2191`) shipped with a list-mode wrapper: the async-generator producing replay + live-tail events was drained into a list before the FastMCP tool return. v2.A close-out flagged this as a carry-forward: "FastMCP version-compat concern. Upgrade for real-time clients in v2." §9.2 of this doctrine anticipated the upgrade as the candidate 6th case.

Path 3 lands the upgrade as Case 6 under the doctrine.

**Shape:** `StreamTransport | None` injection on `SubscriptionToolDeps`, with `__post_init__` defaulting `None → ListModeTransport()` so construction sites that predate Path 3 stay byte-identical.

- **Protocol:** `StreamTransport` (`packages/wormbase-agent-gateway/src/wormbase_agent_gateway/subscriptions/stream_transport.py`)
  - Method: `async deliver(*, subscription_id, generator, stream_registry) -> Any`
- **Default impl:** `ListModeTransport` — drains the generator into `{subscription_id, events: [...]}`; byte-identical to the pre-Path-3 inline wrapper.
- **Opt-in impl:** `SseStreamTransport` — uses a capability probe (`fastmcp_supports_streaming_tools()`) to decide whether to yield events one-at-a-time (true SSE) or degrade to list-mode. Today the probe returns `False` (FastMCP 3.2.4 materializes async-generator tool results into lists at the runner level — see `function_tool.py:_materialize_generator`). The degrade path logs once at INFO so operators see the intent vs reality gap.
- **Env knob:** `WORMBASE_MCP_SSE_TRANSPORT=true` (default off).
- **Boot composition:** `apps/worm-core/src/wormbase_core/agent_gateway_construction.py` calls `build_stream_transport_from_env()` when the subscriptions feature is enabled and threads the result into `SubscriptionToolDeps.stream_transport`.

**Why it fits the doctrine:**

- **Rule 1 (byte-identical default):** Env knob unset → `ListModeTransport` → identical `{subscription_id, events: [...]}` response shape as v2.A Batch B. All 4 pre-existing v2.A subscription-stream tests pass unchanged.
- **Rule 2 (fallback as public contract):** The list-mode response shape is the documented public contract. Even when `SseStreamTransport` is selected via the env knob, if the FastMCP probe returns False, the transport degrades to list-mode (not denial) — clients never see a worse experience than the default.
- **Rule 3 (both paths pinned):** `tests/integration/test_subscription_stream_sse.py` pins ListModeTransport (default), SseStreamTransport-degrades-to-list-mode (today's probe = False), and SseStreamTransport-yields-directly (probe = True via mock — pins the upgrade contract).
- **Rule 4 (single env knob, `WORMBASE_` prefix):** `WORMBASE_MCP_SSE_TRANSPORT`.
- **Rule 5 (default OFF):** Yes.
- **Rule 6 (Protocol boundary):** `StreamTransport(Protocol)` is the boundary.
- **Rule 7 (factory at app/package boundary):** `build_stream_transport_from_env()` lives in the package (`subscriptions/stream_transport.py`); the app calls it from `agent_gateway_construction.py`.
- **Rule 8 (wire-replay determinism):** SSE is a transport concern (how events surface to the consumer), not a data-model concern. The ledger entries written by `stream_subscription`'s generator are identical across both transports. Wire-replay produces the same `agent_event_delivered` entries either way.
- **Rule 9 (telemetry distinguishes paths):** The degrade-to-list-mode case logs at INFO with a clear message. The list-mode-default case is silent (it's the default — no anomaly to report).
- **Rule 10 (consumer docstring documents the choice):** The module docstring of `subscriptions/stream_transport.py` documents the two impls + the upgrade path. The `stream_subscription` consumer's docstring in `mcp_tools.py` references the transport.

**Variant note:** Case 6 mixes two variants from §2:
- `T | None = None` injection at the dataclass level
- A second-level `bool` probe inside `SseStreamTransport` (the FastMCP capability detection)

This is the first Case to combine variants. The combination is principled: the outer injection picks `Which transport?` (a per-deployment choice), and the inner probe picks `Can the underlying FastMCP support true SSE?` (a per-version runtime fact). The doctrine's allowance of all three variants (§2) covers this composition without amendment.

**Upgrade path:** When a future FastMCP grows true async-generator tool streaming (likely via a `stream=True` decorator flag or a new tool type), `fastmcp_supports_streaming_tools()` flips to True for that version. `SseStreamTransport` then delivers true event-by-event yields with no consumer-side change. The list-mode contract continues to work for clients that prefer the single-shot response shape (the agent gateway can run mixed clients — env knob OFF + env knob ON — without cross-talk).

**Open follow-ups:**
- §9.1 (Case 5 multi-tenant routing, Path 4) merged just before Path 3. Both should be appended as addenda; Case 5 addendum is a follow-up task on the overnight roadmap.
- When FastMCP grows streaming-tool support, a follow-up close-out should land that flips the probe and re-pins the SseStreamTransport-with-probe-True test to a live FastMCP round-trip (instead of the current `unittest.mock.patch`).

**Test count delta:** +22 new tests in `test_subscription_stream_sse.py` (8 unit-shaped + 14 integration-shaped). v2.A regression unchanged: 10/10 pre-existing subscription tests pass.

---

## 10. Authority

This doctrine is binding for all WormBase architectural additions that introduce a service or capability optional to the existing feature set. The four cases enumerated in §4 are the canonical references; new cases that emerge must comply with §3's rules or document why they deviate.

Update the doctrine additively (per the schema-evolution doctrine's Rule 2 spirit): append addenda for new cases, clarifications, or rule refinements. Do not rewrite the original rules — let history accumulate.

Cross-references:
- `docs/superpowers/specs/2026-05-03-schema-evolution-doctrine.md` — companion doctrine (persistent state shape)
- `docs/superpowers/specs/2026-05-10-semantic-layer-design.md` — semantic-layer master spec; §4.5 is the compounding query layer that exercises Cases 3 + 4
- `docs/superpowers/notes/2026-05-17-semantic-layer-v2.A-shipped.md` — Case 1 (replay_mode) original close-out
- `docs/superpowers/notes/2026-05-18-semantic-layer-v1.4-polish-shipped.md` — Case 2 (LazyWebhookSecretResolver) original close-out
- `docs/superpowers/notes/2026-05-19-semantic-layer-v2.B-phase3b-shipped.md` — Case 3 (EmbeddingService) original close-out, where the pattern was first named "Optional-Effect Injection"
- `docs/superpowers/notes/2026-05-20-semantic-layer-v2.B-phase3c-shipped.md` — Case 4 (QueryOutcomeProjectionReader) close-out and "Doctrine candidate" §3 seeded this spec
- `CLAUDE.md §1` — production-like posture principle that this doctrine supports
- `CLAUDE.md §1.5 Rules for new worm work` — boundary at which Optional-Effect Injection meets package decomposition

---

---

## Addendum 2 — `OptionalEffectGuard[T]` helper (adopted 2026-05-27)

The 2026-05-27 maintenance audit (`docs/superpowers/notes/2026-05-27-maintenance-audit.md` §"Category 8") found that **6 of the 8 in-flight Optional-Effect Injection cases violate Rule 9** (telemetry distinguishes paths). The doctrine is well-followed in shape and contract; the telemetry obligation is the consistent miss.

To make Rule 9 compliance uniform across new cases without forcing a retrofit of the 8, the doctrine now supplies a shared helper.

### `OptionalEffectGuard[T]`

Canonical module: `apps/worm-core/src/wormbase_core/optional_effect.py`.

A byte-identical copy lives at `packages/wormbase-agent-gateway/src/wormbase_agent_gateway/optional_effect.py` because `wormbase-agent-gateway` cannot depend on `wormbase-core` (agent-gateway is a lower layer in the dependency graph). The two files MUST stay byte-identical at the public surface; an eventual promotion to a shared lower-level package (e.g. introducing `wormbase-common`) would drop the duplicate. Tests pin both copies independently.

Public API:

| Member | Signature | Purpose |
|---|---|---|
| `__init__` | `(case_name: str, service: T \| None)` | Construct a guard; ``case_name`` is the stable doctrine-case identifier |
| `is_present()` | `-> bool` | True iff the service is non-None |
| `use()` | `-> T` | Returns the service; raises ``OptionalEffectAbsent`` if absent |
| `take_path()` | `async (*, with_present, without) -> R` | Async dispatch with telemetry; both callables return the same ``R`` |
| `take_path_sync()` | `(*, with_present, without) -> R` | Sync counterpart for composition-time / boot-time decisions |
| `metrics()` | `-> dict[str, int]` | Returns ``{"present_path_count": ..., "absent_path_count": ...}`` |
| `case_name` (property) | `-> str` | Read-only access to the construction-time case identifier |

Telemetry contract:

- Each `take_path` / `take_path_sync` call increments exactly one of the two counters and emits a DEBUG-level log keyed by `case_name` with `path` and `count` extras.
- `use()` is a low-level accessor and does NOT tick a counter — callers using `use()` are expected to record their own telemetry.

### Adoption policy

- **New cases (the 9th + onwards) MUST use the guard.**
- **Existing 8 cases MAY migrate at their own cadence; not required in a single sweep.**
- Migrated cases MUST preserve their external contract byte-identically.

### Pilot adoptions (this Addendum's scope)

This Addendum lands the helper plus 2 proof-of-pattern adoptions; the remaining 6 cases stay on the audit's known-deferred list.

| Case | Site | Guard | Adoption nature |
|---|---|---|---|
| 7 — LedgerQuotaTracker | `apps/worm-core/src/wormbase_core/agent_gateway_construction.py` (composition site) | `OptionalEffectGuard[tuple[Ledger, UUID]]("ledger_quota_tracker", ...)` | Composition-time `take_path_sync` decides whether to wrap `InMemoryQuotaTracker` in `LedgerQuotaTracker`. Guard accessible via `build_tenant_router_from_env._last_quota_emission_guard` for inspection. |
| 8 — TenantEngineRegistry | `packages/wormbase-agent-gateway/src/wormbase_agent_gateway/tenancy.py` (`InMemoryTenantRouter`) | `OptionalEffectGuard[TenantEngineRegistry]("tenant_engine_registry", ...)` | Per-call `take_path` in `resolve_engine_for_slug()`. Guard accessible via `router.engine_registry_guard`. The router's pre-existing methods are unchanged — adoption is purely additive. |

For both adopted cases:

- Default-None preserves byte-identical pre-adoption behavior (existing 89 tenancy tests + 27 worm-core tenant-router tests stay green).
- The guard's per-path counters become the Rule 9 telemetry artifact.
- Operators / dashboards can read `metrics()` to answer "what fraction of fires hit the with-service path vs the fallback path?"

### Deferred cases (carry-forward — 6 of 8)

Cases NOT migrated in this Addendum's scope, with rationale:

| Case | Status | Rationale |
|---|---|---|
| 1 — `replay_mode: bool = False` | not migrated | Boolean toggle, not `Optional[T]` — out of guard pattern scope; keep as variant per §"Variants observed" |
| 2 — LazyWebhookSecretResolver | not migrated | Variant shape (lazy late-bind, not basic Optional[T]); guard would awkwardly fit |
| 3 — `EmbeddingService \| None` | not migrated | Eligible — single-sweep risk; deferred to its own follow-up |
| 4 — `QueryOutcomeProjectionReader \| None` | not migrated | Eligible — single-sweep risk; deferred to its own follow-up |
| 5 — `TenantRouter \| None` | not migrated | Already 9.5/10 R9 per audit (ledger audit IS the telemetry); marginal benefit |
| 6 — SseStreamTransport | not migrated | Variant shape (capability probe), guard would need extension |

The audit's Rule 9 findings for these 6 cases remain a known carry-forward. Future migration MAY happen as part of dedicated R9-compliance work; this Addendum's pilot adoptions demonstrate the pattern works and bound the migration risk.

### Cross-references

- `apps/worm-core/src/wormbase_core/optional_effect.py` — canonical helper
- `packages/wormbase-agent-gateway/src/wormbase_agent_gateway/optional_effect.py` — package-local copy
- `apps/worm-core/tests/test_optional_effect_guard.py` — guard unit tests (13 cases)
- `apps/worm-core/tests/test_tenant_router.py` (last 3 tests) — Case 7 adoption tests
- `packages/wormbase-agent-gateway/tests/test_tenancy.py` (last 4 tests) — Case 8 adoption tests
- `docs/superpowers/notes/2026-05-27-maintenance-audit.md` §"Category 8" — originating Rule 9 audit

---

**Status:** DOCTRINE — adopted 2026-05-21. Four canonical cases (§4) + Addendum 1 (Case 6, StreamTransport) + Addendum 2 (`OptionalEffectGuard[T]` helper + 2 pilot adoptions, 2026-05-27). Rules 1-10 binding. Section 9 watch-list is informational; future cases that match the shape will be added as addenda following the schema-evolution doctrine's addendum convention.
