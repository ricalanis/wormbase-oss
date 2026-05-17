"""Unit tests — TenantRouter, RateLimiter, QuotaTracker (Path 4, 2026-05-21).

Verifies the Optional-Effect Injection Case 5 contract in isolation:

  * Slug→company_id resolution is uuid5-stable (replay deterministic).
  * Unknown / revoked / empty slugs raise the right error type.
  * Rate limiter enforces per-tenant window correctly + per-tenant
    isolation (one tenant's exhaustion doesn't bleed into another).
  * Quota tracker enforces 24h rolling-window count + isolation.
  * Snapshot helpers expose operator-visible state.

Extended 2026-05-13 (final-wave item #7) with LedgerQuotaTracker
cadence-emission tests verifying the 7th case of the Optional-Effect
Injection doctrine.
"""
from __future__ import annotations

from uuid import UUID

import pytest

from wormbase_agent_gateway.tenancy import (
    InMemoryQuotaTracker,
    InMemoryRateLimiter,
    InMemoryTenantRouter,
    LedgerQuotaTracker,
    QuotaTracker,
    TenantContext,
    TenantQuotaExceededError,
    TenantRateLimitedError,
    TenantRevokedError,
    TenantUnknownError,
    is_multi_tenant_mcp_enabled,
    is_tenant_quota_ledger_emission_enabled,
    resolve_default_quota_count_threshold,
    resolve_default_quota_per_day,
    resolve_default_quota_time_threshold_seconds,
    resolve_default_rate_limit_per_min,
    resolve_default_tenant_region,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Env-knob defaults
# ---------------------------------------------------------------------------


async def test_env_knob_default_off(monkeypatch):
    monkeypatch.delenv("WORMBASE_MULTI_TENANT_MCP", raising=False)
    assert is_multi_tenant_mcp_enabled() is False


async def test_env_knob_truthy(monkeypatch):
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    assert is_multi_tenant_mcp_enabled() is True


async def test_env_knob_non_canonical_truthy_is_off(monkeypatch):
    """Per Optional-Effect doctrine §3 Rule 5 — only 'true' is honored."""
    for value in ("1", "yes", "True", "TRUE", "on", "ENABLED"):
        monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", value)
        # The canonical lowercase 'true' is honored — "True"/"TRUE" lowercases to "true"
        if value.lower() == "true":
            assert is_multi_tenant_mcp_enabled() is True
        else:
            assert is_multi_tenant_mcp_enabled() is False, (
                f"value {value!r} should be OFF"
            )


async def test_default_rate_limit_fallback(monkeypatch):
    monkeypatch.delenv("WORMBASE_MULTI_TENANT_RATE_LIMIT_PER_MIN", raising=False)
    assert resolve_default_rate_limit_per_min() == 100


async def test_default_rate_limit_override(monkeypatch):
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_RATE_LIMIT_PER_MIN", "250")
    assert resolve_default_rate_limit_per_min() == 250


async def test_default_rate_limit_invalid_fallback(monkeypatch):
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_RATE_LIMIT_PER_MIN", "abc")
    assert resolve_default_rate_limit_per_min() == 100


async def test_default_quota_fallback(monkeypatch):
    monkeypatch.delenv("WORMBASE_MULTI_TENANT_QUOTA_PER_DAY", raising=False)
    assert resolve_default_quota_per_day() == 100_000


# ---------------------------------------------------------------------------
# InMemoryTenantRouter — resolution
# ---------------------------------------------------------------------------


async def test_resolve_registered_tenant():
    router = InMemoryTenantRouter()
    record = router.register(tenant_slug="acme")
    ctx = await router.resolve("acme")
    assert isinstance(ctx, TenantContext)
    assert ctx.tenant_slug == "acme"
    assert ctx.company_id == record.company_id
    assert ctx.enabled is True


async def test_resolve_slug_normalization():
    """Slug is normalized via strip + lower — header value can vary."""
    router = InMemoryTenantRouter()
    router.register(tenant_slug="acme")
    ctx = await router.resolve("  ACME  ")
    assert ctx.tenant_slug == "acme"


async def test_resolve_missing_header_raises():
    router = InMemoryTenantRouter()
    with pytest.raises(TenantUnknownError):
        await router.resolve(None)


async def test_resolve_empty_header_raises():
    router = InMemoryTenantRouter()
    with pytest.raises(TenantUnknownError):
        await router.resolve("")


async def test_resolve_unregistered_tenant_raises():
    router = InMemoryTenantRouter()
    router.register(tenant_slug="acme")
    with pytest.raises(TenantUnknownError):
        await router.resolve("other")


async def test_resolve_revoked_tenant_raises():
    router = InMemoryTenantRouter()
    router.register(tenant_slug="acme")
    router.revoke("acme")
    with pytest.raises(TenantRevokedError):
        await router.resolve("acme")


async def test_slug_to_uuid_deterministic():
    """Same slug always maps to the same UUID — replay determinism."""
    router_a = InMemoryTenantRouter()
    router_b = InMemoryTenantRouter()
    rec_a = router_a.register(tenant_slug="acme")
    rec_b = router_b.register(tenant_slug="acme")
    assert rec_a.company_id == rec_b.company_id


async def test_register_with_empty_slug_raises():
    router = InMemoryTenantRouter()
    with pytest.raises(ValueError):
        router.register(tenant_slug="")
    with pytest.raises(ValueError):
        router.register(tenant_slug="   ")


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


async def test_rate_limit_under_capacity():
    rl = InMemoryRateLimiter(capacity_per_min=3, window_seconds=60.0)
    for _ in range(3):
        await rl.check("acme")  # no raise


async def test_rate_limit_over_capacity_raises():
    rl = InMemoryRateLimiter(capacity_per_min=3, window_seconds=60.0)
    for _ in range(3):
        await rl.check("acme")
    with pytest.raises(TenantRateLimitedError):
        await rl.check("acme")


async def test_rate_limit_window_eviction():
    """After the window passes, old timestamps expire and capacity opens up."""
    fake_time = [1000.0]

    def _time_fn() -> float:
        return fake_time[0]

    rl = InMemoryRateLimiter(
        capacity_per_min=2, window_seconds=60.0, time_fn=_time_fn,
    )
    await rl.check("acme")
    await rl.check("acme")
    with pytest.raises(TenantRateLimitedError):
        await rl.check("acme")
    # Move the clock forward past the window.
    fake_time[0] += 61.0
    # Should succeed now.
    await rl.check("acme")


async def test_rate_limit_per_tenant_isolation():
    """Tenant A hitting limit doesn't affect tenant B."""
    rl = InMemoryRateLimiter(capacity_per_min=2, window_seconds=60.0)
    await rl.check("acme")
    await rl.check("acme")
    with pytest.raises(TenantRateLimitedError):
        await rl.check("acme")
    # B is still fresh.
    await rl.check("beta")
    await rl.check("beta")
    with pytest.raises(TenantRateLimitedError):
        await rl.check("beta")


async def test_rate_limit_snapshot_telemetry():
    rl = InMemoryRateLimiter(capacity_per_min=5, window_seconds=60.0)
    await rl.check("acme")
    await rl.check("acme")
    snap = rl.snapshot("acme")
    assert snap == {"in_window": 2, "capacity": 5}
    # Unseen tenant returns the zero baseline.
    assert rl.snapshot("beta") == {"in_window": 0, "capacity": 5}


# ---------------------------------------------------------------------------
# Quota tracker
# ---------------------------------------------------------------------------


async def test_quota_under_capacity():
    qt = InMemoryQuotaTracker(capacity_per_day=3, window_seconds=86400.0)
    for _ in range(3):
        await qt.consume("acme")


async def test_quota_over_capacity_raises():
    qt = InMemoryQuotaTracker(capacity_per_day=3, window_seconds=86400.0)
    for _ in range(3):
        await qt.consume("acme")
    with pytest.raises(TenantQuotaExceededError):
        await qt.consume("acme")


async def test_quota_per_tenant_isolation():
    qt = InMemoryQuotaTracker(capacity_per_day=2, window_seconds=86400.0)
    await qt.consume("acme")
    await qt.consume("acme")
    with pytest.raises(TenantQuotaExceededError):
        await qt.consume("acme")
    # B unaffected.
    await qt.consume("beta")
    await qt.consume("beta")


async def test_quota_snapshot_telemetry():
    qt = InMemoryQuotaTracker(capacity_per_day=10, window_seconds=86400.0)
    await qt.consume("acme")
    snap = qt.snapshot("acme")
    assert snap == {"consumed": 1, "capacity": 10}


# ---------------------------------------------------------------------------
# Router composition — rate + quota wired through resolve
# ---------------------------------------------------------------------------


async def test_router_enforce_rate_limit_calls_limiter():
    rl = InMemoryRateLimiter(capacity_per_min=1, window_seconds=60.0)
    router = InMemoryTenantRouter(rate_limiter=rl)
    router.register(tenant_slug="acme")
    ctx = await router.resolve("acme")
    await router.enforce_rate_limit(ctx)  # 1st OK
    with pytest.raises(TenantRateLimitedError):
        await router.enforce_rate_limit(ctx)


async def test_router_consume_quota_calls_tracker():
    qt = InMemoryQuotaTracker(capacity_per_day=1, window_seconds=86400.0)
    router = InMemoryTenantRouter(quota_tracker=qt)
    router.register(tenant_slug="acme")
    ctx = await router.resolve("acme")
    await router.consume_quota(ctx)
    with pytest.raises(TenantQuotaExceededError):
        await router.consume_quota(ctx)


async def test_router_snapshot_for_registered_tenant():
    router = InMemoryTenantRouter()
    router.register(tenant_slug="acme")
    snap = router.snapshot("acme")
    assert snap["registered"] is True
    assert snap["enabled"] is True
    assert isinstance(snap["rate_limit"], dict)
    assert isinstance(snap["quota"], dict)


async def test_router_snapshot_for_unregistered_tenant():
    router = InMemoryTenantRouter()
    snap = router.snapshot("ghost")
    assert snap["registered"] is False
    assert snap["enabled"] is False


# ---------------------------------------------------------------------------
# Slug→company_id parity with worm-core's tenant_to_uuid
# ---------------------------------------------------------------------------


async def test_default_slug_resolver_parity_with_worm_core():
    """The package-default resolver MUST produce the same UUID as the
    worm-core helper. This is required for the dashboard and the MCP
    HTTP listener to agree on which tenant ID a slug maps to."""
    from wormbase_agent_gateway.tenancy import _default_slug_resolver
    # Avoid the worm-core import at the package layer; replicate the
    # logic inline so the test is self-contained.
    from uuid import uuid5
    namespace = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")
    for slug in ("acme", "BasewOrm", "demo-tenant-42"):
        expected = uuid5(namespace, slug.strip().lower())
        assert _default_slug_resolver(slug) == expected


async def test_custom_slug_resolver_injection():
    """App layer can inject a custom resolver (e.g. database lookup)."""

    def custom_resolver(slug: str) -> UUID:
        return UUID(int=hash(slug) & ((1 << 128) - 1))

    router = InMemoryTenantRouter(slug_resolver=custom_resolver)
    record = router.register(tenant_slug="acme")
    expected = custom_resolver("acme")
    assert record.company_id == expected


# ---------------------------------------------------------------------------
# LedgerQuotaTracker — final-wave item #7 (Optional-Effect Injection §6.4
# Case 7). Default OFF behavior is byte-identical Path 4 in-memory
# semantics; opt-in delivers SOC-2 audit visibility via periodic
# tenant_quota_consumed entries.
# ---------------------------------------------------------------------------


async def test_ledger_quota_emission_env_knob_default_off(monkeypatch):
    monkeypatch.delenv("WORMBASE_TENANT_QUOTA_LEDGER", raising=False)
    assert is_tenant_quota_ledger_emission_enabled() is False


async def test_ledger_quota_emission_env_knob_truthy(monkeypatch):
    monkeypatch.setenv("WORMBASE_TENANT_QUOTA_LEDGER", "true")
    assert is_tenant_quota_ledger_emission_enabled() is True


async def test_ledger_quota_count_threshold_default(monkeypatch):
    monkeypatch.delenv(
        "WORMBASE_TENANT_QUOTA_LEDGER_COUNT_THRESHOLD", raising=False,
    )
    assert resolve_default_quota_count_threshold() == 100


async def test_ledger_quota_count_threshold_override(monkeypatch):
    monkeypatch.setenv(
        "WORMBASE_TENANT_QUOTA_LEDGER_COUNT_THRESHOLD", "25",
    )
    assert resolve_default_quota_count_threshold() == 25


async def test_ledger_quota_time_threshold_default(monkeypatch):
    monkeypatch.delenv(
        "WORMBASE_TENANT_QUOTA_LEDGER_TIME_THRESHOLD_SECONDS",
        raising=False,
    )
    assert resolve_default_quota_time_threshold_seconds() == 300.0


async def test_ledger_quota_time_threshold_override(monkeypatch):
    monkeypatch.setenv(
        "WORMBASE_TENANT_QUOTA_LEDGER_TIME_THRESHOLD_SECONDS", "30",
    )
    assert resolve_default_quota_time_threshold_seconds() == 30.0


async def test_ledger_quota_protocol_compat():
    """LedgerQuotaTracker and InMemoryQuotaTracker satisfy the same Protocol.

    Both implementations expose ``consume(slug)`` and ``snapshot(slug)``,
    so they're interchangeable behind ``TenantRouter._quota_tracker``.
    """
    inner = InMemoryQuotaTracker(capacity_per_day=10, window_seconds=86400.0)

    async def _emit(_payload: dict[str, object]) -> None:
        pass

    ledger_tracker = LedgerQuotaTracker(inner, _emit)
    # Both expose the surface that QuotaTracker Protocol requires.
    assert isinstance(inner, QuotaTracker)
    assert isinstance(ledger_tracker, QuotaTracker)


async def test_ledger_quota_emits_at_count_threshold():
    """N requests at the count threshold → exactly 1 ledger entry."""
    emissions: list[dict[str, object]] = []

    async def _emit(payload: dict[str, object]) -> None:
        emissions.append(payload)

    inner = InMemoryQuotaTracker(
        capacity_per_day=1000, window_seconds=86400.0,
    )
    tracker = LedgerQuotaTracker(
        inner,
        _emit,
        count_threshold=5,
        # Long time threshold so only count fires.
        time_threshold_seconds=10_000.0,
    )
    # First 4 consumes — no emission.
    for _ in range(4):
        await tracker.consume("acme")
    assert emissions == []
    # 5th consume triggers count_threshold.
    await tracker.consume("acme")
    assert len(emissions) == 1
    p = emissions[0]
    assert p["tenant_slug"] == "acme"
    assert p["triggered_by"] == "count_threshold"
    assert p["consumption_count"] == 5
    assert p["quota_limit"] == 1000
    assert p["quota_remaining"] == 1000 - 5


async def test_ledger_quota_emits_at_time_threshold():
    """Elapsed time threshold → exactly 1 ledger entry."""
    emissions: list[dict[str, object]] = []

    async def _emit(payload: dict[str, object]) -> None:
        emissions.append(payload)

    fake_mono = [1000.0]

    def _time_fn() -> float:
        return fake_mono[0]

    inner = InMemoryQuotaTracker(
        capacity_per_day=1000, window_seconds=86400.0,
        time_fn=_time_fn,
    )
    tracker = LedgerQuotaTracker(
        inner,
        _emit,
        # High count threshold so only time fires.
        count_threshold=1_000_000,
        time_threshold_seconds=60.0,
        time_fn=_time_fn,
    )
    # First consume opens the window at t=1000.
    await tracker.consume("acme")
    assert emissions == []
    # Bump time past threshold; next consume should fire time_threshold.
    fake_mono[0] = 1061.0
    await tracker.consume("acme")
    assert len(emissions) == 1
    p = emissions[0]
    assert p["tenant_slug"] == "acme"
    assert p["triggered_by"] == "time_threshold"
    # Two requests landed inside the window before the trigger.
    assert p["consumption_count"] == 2


async def test_ledger_quota_emits_immediately_on_quota_exhausted():
    """The deny moment is captured immediately, not amortized."""
    emissions: list[dict[str, object]] = []

    async def _emit(payload: dict[str, object]) -> None:
        emissions.append(payload)

    inner = InMemoryQuotaTracker(
        capacity_per_day=2, window_seconds=86400.0,
    )
    tracker = LedgerQuotaTracker(
        inner,
        _emit,
        # High thresholds so periodic emission would never fire on its own.
        count_threshold=1_000_000,
        time_threshold_seconds=1_000_000.0,
    )
    # First two consumes — no emission (under threshold).
    await tracker.consume("acme")
    await tracker.consume("acme")
    assert emissions == []
    # Third consume — quota exhausted, deny-moment emission fires.
    with pytest.raises(TenantQuotaExceededError):
        await tracker.consume("acme")
    assert len(emissions) == 1
    p = emissions[0]
    assert p["tenant_slug"] == "acme"
    assert p["triggered_by"] == "quota_exhausted"
    assert p["quota_remaining"] == 0
    assert p["quota_limit"] == 2


async def test_ledger_quota_per_tenant_cadence_isolation():
    """A's accumulation doesn't trigger B's emission."""
    emissions: list[dict[str, object]] = []

    async def _emit(payload: dict[str, object]) -> None:
        emissions.append(payload)

    inner = InMemoryQuotaTracker(
        capacity_per_day=1000, window_seconds=86400.0,
    )
    tracker = LedgerQuotaTracker(
        inner,
        _emit,
        count_threshold=3,
        time_threshold_seconds=10_000.0,
    )
    # 2 consumes for acme — under threshold.
    await tracker.consume("acme")
    await tracker.consume("acme")
    # 2 consumes for beta — under threshold (each tenant gets own state).
    await tracker.consume("beta")
    await tracker.consume("beta")
    assert emissions == []
    # acme's 3rd consume fires its own emission.
    await tracker.consume("acme")
    assert len(emissions) == 1
    assert emissions[0]["tenant_slug"] == "acme"
    # beta's 3rd consume fires its own emission.
    await tracker.consume("beta")
    assert len(emissions) == 2
    assert emissions[1]["tenant_slug"] == "beta"


async def test_ledger_quota_resets_window_after_emission():
    """After a count-threshold emission, the next window starts fresh."""
    emissions: list[dict[str, object]] = []

    async def _emit(payload: dict[str, object]) -> None:
        emissions.append(payload)

    inner = InMemoryQuotaTracker(
        capacity_per_day=1000, window_seconds=86400.0,
    )
    tracker = LedgerQuotaTracker(
        inner,
        _emit,
        count_threshold=2,
        time_threshold_seconds=10_000.0,
    )
    # First window — 2 consumes triggers emission.
    await tracker.consume("acme")
    await tracker.consume("acme")
    assert len(emissions) == 1
    # Second window — another 2 consumes triggers a new emission.
    await tracker.consume("acme")
    await tracker.consume("acme")
    assert len(emissions) == 2
    # Both emissions carry consumption_count=2 (window reset between them).
    assert emissions[0]["consumption_count"] == 2
    assert emissions[1]["consumption_count"] == 2


async def test_ledger_quota_wraps_in_memory_byte_identical_consume_semantics():
    """LedgerQuotaTracker.consume preserves exact InMemoryQuotaTracker
    enforcement semantics — exhaustion at the same boundary."""
    emissions: list[dict[str, object]] = []

    async def _emit(payload: dict[str, object]) -> None:
        emissions.append(payload)

    # Reference: in-memory tracker alone.
    ref = InMemoryQuotaTracker(capacity_per_day=3, window_seconds=86400.0)
    await ref.consume("acme")
    await ref.consume("acme")
    await ref.consume("acme")
    with pytest.raises(TenantQuotaExceededError):
        await ref.consume("acme")

    # Wrapped: LedgerQuotaTracker over fresh in-memory.
    wrapped_inner = InMemoryQuotaTracker(
        capacity_per_day=3, window_seconds=86400.0,
    )
    tracker = LedgerQuotaTracker(
        wrapped_inner,
        _emit,
        count_threshold=1_000_000,  # disable count cadence
        time_threshold_seconds=1_000_000.0,  # disable time cadence
    )
    await tracker.consume("acme")
    await tracker.consume("acme")
    await tracker.consume("acme")
    with pytest.raises(TenantQuotaExceededError):
        await tracker.consume("acme")


async def test_ledger_quota_router_composition_swappable():
    """A router composed with LedgerQuotaTracker enforces correctly."""
    emissions: list[dict[str, object]] = []

    async def _emit(payload: dict[str, object]) -> None:
        emissions.append(payload)

    inner = InMemoryQuotaTracker(capacity_per_day=1, window_seconds=86400.0)
    ledger_tracker = LedgerQuotaTracker(
        inner,
        _emit,
        count_threshold=1_000_000,
        time_threshold_seconds=1_000_000.0,
    )
    router = InMemoryTenantRouter(quota_tracker=ledger_tracker)
    router.register(tenant_slug="acme")
    ctx = await router.resolve("acme")
    await router.consume_quota(ctx)  # 1st OK
    with pytest.raises(TenantQuotaExceededError):
        await router.consume_quota(ctx)
    # The deny moment fired a quota_exhausted emission.
    assert len(emissions) == 1
    assert emissions[0]["triggered_by"] == "quota_exhausted"


# ---------------------------------------------------------------------------
# Multi-region routing (post-rest #7, 2026-05-13)
#
# Additive ``region`` field on :class:`TenantContext` + the
# ``WORMBASE_DEFAULT_TENANT_REGION`` env-fallback helper. Default
# behavior is byte-identical Path 4 + Phase 1+2 (#1).
# ---------------------------------------------------------------------------


async def test_tenant_context_region_defaults_to_none() -> None:
    """The additive ``region`` field on :class:`TenantContext`
    defaults to ``None`` ("no region preference") — Path 4 + Phase
    1+2 byte-identity preserved."""
    from uuid import uuid4
    ctx = TenantContext(tenant_slug="acme", company_id=uuid4())
    assert ctx.region is None


async def test_tenant_context_can_carry_region_pin() -> None:
    """A :class:`TenantContext` can be constructed with an explicit
    ``region`` pin — the multi-region routing extension surfaces it
    for ops + monitoring without enforcing connection-pool locality."""
    from uuid import uuid4
    ctx = TenantContext(
        tenant_slug="globex",
        company_id=uuid4(),
        region="eu-central-1",
    )
    assert ctx.region == "eu-central-1"


async def test_router_resolved_context_has_no_region_by_default() -> None:
    """:class:`InMemoryTenantRouter` does NOT itself populate
    ``region`` — multi-region wiring lives at the engine-per-tenant
    boundary. Path 4 byte-identity preserved at the router layer."""
    router = InMemoryTenantRouter()
    router.register(tenant_slug="acme")
    ctx = await router.resolve("acme")
    assert ctx.region is None


async def test_default_tenant_region_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``WORMBASE_DEFAULT_TENANT_REGION`` unset → ``None`` (no
    region preference) — byte-identical default."""
    monkeypatch.delenv("WORMBASE_DEFAULT_TENANT_REGION", raising=False)
    assert resolve_default_tenant_region() is None


async def test_default_tenant_region_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A set ``WORMBASE_DEFAULT_TENANT_REGION`` env knob surfaces as
    the install-wide fallback region."""
    monkeypatch.setenv("WORMBASE_DEFAULT_TENANT_REGION", "us-west-2")
    assert resolve_default_tenant_region() == "us-west-2"


async def test_default_tenant_region_empty_normalizes_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty / whitespace-only ``WORMBASE_DEFAULT_TENANT_REGION``
    normalizes to ``None`` so an operator can clear the fallback."""
    monkeypatch.setenv("WORMBASE_DEFAULT_TENANT_REGION", "   ")
    assert resolve_default_tenant_region() is None


# ---------------------------------------------------------------------------
# Optional-Effect Injection Case 8 — InMemoryTenantRouter.engine_registry guard
# (doctrine Addendum 2 adoption — 2026-05-27)
# ---------------------------------------------------------------------------


async def test_engine_registry_guard_absent_returns_none_and_ticks_absent_counter():
    """No registry injected → ``resolve_engine_for_slug`` returns None.

    Verifies Shape A byte-identical behavior preserved (doctrine §3
    Rule 1) AND the guard's per-path counter ticks the absent path
    (doctrine §3 Rule 9 — telemetry distinguishes paths).
    """
    router = InMemoryTenantRouter()
    assert router.engine_registry_guard.is_present() is False

    result = await router.resolve_engine_for_slug("acme")
    assert result is None

    metrics = router.engine_registry_guard.metrics()
    assert metrics == {"present_path_count": 0, "absent_path_count": 1}


async def test_engine_registry_guard_present_delegates_to_registry():
    """Registry injected → ``resolve_engine_for_slug`` delegates to it.

    The guard's present-path callable invokes the registry's
    ``resolve_engine`` for the normalized slug and returns its result.
    """
    from wormbase_agent_gateway.tenancy import StaticTenantEngineRegistry

    sentinel_engine = object()  # opaque "AsyncEngine" stand-in

    async def _factory(slug: str, dsn_secret_ref: str) -> object:
        return sentinel_engine

    registry = StaticTenantEngineRegistry.from_file.__func__.__self__ if False else None
    # Build a real static registry via TOML for the parity test.
    import tempfile
    import textwrap
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".toml", delete=False,
    ) as f:
        f.write(textwrap.dedent(
            """
            [tenants.acme]
            dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"
            """,
        ))
        toml_path = f.name
    registry = StaticTenantEngineRegistry.from_file(
        toml_path, engine_factory=_factory,
    )

    router = InMemoryTenantRouter(engine_registry=registry)
    assert router.engine_registry_guard.is_present() is True

    # Mapped slug → registry resolves it to the factory-built engine.
    result = await router.resolve_engine_for_slug("acme")
    assert result is sentinel_engine

    # Unmapped slug → registry returns None; guard still ticks the
    # present-path counter (the registry was consulted).
    unmapped = await router.resolve_engine_for_slug("globex")
    assert unmapped is None

    metrics = router.engine_registry_guard.metrics()
    assert metrics == {"present_path_count": 2, "absent_path_count": 0}


async def test_engine_registry_guard_normalizes_slug():
    """``resolve_engine_for_slug`` lowercases + strips its argument.

    Defense: the consumer-side guard must apply the same normalization
    as :meth:`InMemoryTenantRouter.register` so a tenant whose slug was
    registered as ``"acme"`` resolves consistently regardless of whether
    the caller passes ``"ACME"`` or ``"  acme "``.
    """
    from wormbase_agent_gateway.tenancy import StaticTenantEngineRegistry

    sentinel = object()

    async def _factory(slug: str, dsn_secret_ref: str) -> object:
        return sentinel

    import tempfile
    import textwrap
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".toml", delete=False,
    ) as f:
        f.write(textwrap.dedent(
            """
            [tenants.acme]
            dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"
            """,
        ))
        toml_path = f.name

    registry = StaticTenantEngineRegistry.from_file(
        toml_path, engine_factory=_factory,
    )
    router = InMemoryTenantRouter(engine_registry=registry)

    assert await router.resolve_engine_for_slug("ACME") is sentinel
    assert await router.resolve_engine_for_slug("  acme  ") is sentinel


async def test_engine_registry_guard_does_not_affect_existing_router_surface():
    """Adoption is purely additive — pre-Addendum-2 behavior preserved.

    All pre-existing :class:`InMemoryTenantRouter` methods (``resolve``,
    ``enforce_rate_limit``, ``consume_quota``, ``snapshot``) keep their
    byte-identical contracts when ``engine_registry`` is not injected.
    """
    router = InMemoryTenantRouter()
    router.register(tenant_slug="acme")

    ctx = await router.resolve("acme")
    assert ctx.tenant_slug == "acme"
    # Rate limit / quota still work end-to-end.
    await router.enforce_rate_limit(ctx)
    await router.consume_quota(ctx)
    snap = router.snapshot("acme")
    assert snap["registered"] is True
    assert snap["enabled"] is True
    # No engine_registry calls were issued — guard counters stay at zero.
    assert router.engine_registry_guard.metrics() == {
        "present_path_count": 0,
        "absent_path_count": 0,
    }
