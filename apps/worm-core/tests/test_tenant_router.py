"""Tests — worm-core construction of the agent-gateway TenantRouter.

Path 4 (2026-05-21 overnight roadmap) wiring tests:

  1. Default OFF (env knob unset) returns None — Optional-Effect
     Injection doctrine §3 Rule 1.
  2. Enabling the env knob composes an :class:`InMemoryTenantRouter`.
  3. The router's slug_resolver matches ``wormbase_core.service.tenant_to_uuid``
     — required for cross-surface tenant ID parity (dashboard HTTP
     write API + MCP HTTP listener agree on company_id per slug).
  4. ``WORMBASE_MULTI_TENANT_SLUGS`` pre-registers comma-separated slugs.
  5. ``WORMBASE_MULTI_TENANT_RATE_LIMIT_PER_MIN`` is honored.
  6. ``compose_production_agent_gateway_deps`` threads the router into
     :class:`GatewayDeps.tenant_router`.
  7. ``run_agent_gateway_build_smoke`` surfaces ``multi_tenant_wired``.
"""
from __future__ import annotations

from uuid import UUID

from wormbase_ledger import InMemoryLedger

from wormbase_core.agent_gateway_construction import (
    build_tenant_router_from_env,
    compose_production_agent_gateway_deps,
    is_multi_tenant_mcp_enabled,
    run_agent_gateway_build_smoke,
)
from wormbase_core.service import tenant_to_uuid


_TEST_COMPANY = UUID("00000000-0000-0000-0000-000000000abc")


# ---------------------------------------------------------------------------
# 1. Default OFF
# ---------------------------------------------------------------------------


def test_default_off_returns_none(monkeypatch):
    monkeypatch.delenv("WORMBASE_MULTI_TENANT_MCP", raising=False)
    assert is_multi_tenant_mcp_enabled() is False
    router = build_tenant_router_from_env(install_id="install-test")
    assert router is None


# ---------------------------------------------------------------------------
# 2. Enabled composes a router
# ---------------------------------------------------------------------------


def test_enabled_composes_router(monkeypatch):
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.delenv("WORMBASE_MULTI_TENANT_SLUGS", raising=False)
    router = build_tenant_router_from_env(install_id="install-test")
    assert router is not None
    # The install_id itself is pre-registered.
    assert router.is_registered("install-test")


# ---------------------------------------------------------------------------
# 3. slug_resolver parity with tenant_to_uuid
# ---------------------------------------------------------------------------


def test_slug_resolver_parity_with_worm_core(monkeypatch):
    """The router's company_id for a slug MUST equal ``tenant_to_uuid(slug)``."""
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_SLUGS", "acme")
    router = build_tenant_router_from_env(install_id="install-test")
    assert router is not None
    import asyncio

    async def _check():
        ctx = await router.resolve("acme")
        return ctx

    ctx = asyncio.run(_check())
    assert ctx.company_id == tenant_to_uuid("acme"), (
        "MCP router and worm-core HTTP API must agree on company_id "
        "per tenant slug — required for cross-surface tenant parity"
    )


# ---------------------------------------------------------------------------
# 4. WORMBASE_MULTI_TENANT_SLUGS pre-registers
# ---------------------------------------------------------------------------


def test_extra_slugs_pre_registered(monkeypatch):
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_SLUGS", "acme,beta, gamma ")
    router = build_tenant_router_from_env(install_id="install-test")
    assert router is not None
    assert router.is_registered("acme")
    assert router.is_registered("beta")
    assert router.is_registered("gamma")


def test_extra_slugs_with_empty_entries_tolerated(monkeypatch):
    """Empty / blank entries between commas are silently skipped."""
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_SLUGS", "acme,,,beta")
    router = build_tenant_router_from_env(install_id="install-test")
    assert router is not None
    assert router.is_registered("acme")
    assert router.is_registered("beta")


# ---------------------------------------------------------------------------
# 5. Rate-limit env knob honored
# ---------------------------------------------------------------------------


def test_rate_limit_env_knob_honored(monkeypatch):
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_RATE_LIMIT_PER_MIN", "5")
    router = build_tenant_router_from_env(install_id="install-test")
    assert router is not None
    # Reach into the rate limiter to verify capacity.
    limiter = router._rate_limiter  # type: ignore[attr-defined]
    assert limiter._capacity == 5  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 6. GatewayDeps.tenant_router populated when enabled
# ---------------------------------------------------------------------------


def test_compose_production_threads_tenant_router_when_enabled(monkeypatch):
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_SLUGS", "acme")
    ledger = InMemoryLedger()
    deps = compose_production_agent_gateway_deps(
        ledger=ledger,
        company_id=_TEST_COMPANY,
        install_id="install-test",
    )
    assert deps.tenant_router is not None
    assert deps.tenant_router.is_registered("acme")


def test_compose_production_omits_tenant_router_when_disabled(monkeypatch):
    """Default-OFF preserves byte-identical Phase 1-3c GatewayDeps shape."""
    monkeypatch.delenv("WORMBASE_MULTI_TENANT_MCP", raising=False)
    ledger = InMemoryLedger()
    deps = compose_production_agent_gateway_deps(
        ledger=ledger,
        company_id=_TEST_COMPANY,
        install_id="install-test",
    )
    assert deps.tenant_router is None


# ---------------------------------------------------------------------------
# 7. Build-smoke surfaces multi_tenant_wired
# ---------------------------------------------------------------------------


def test_build_smoke_reports_multi_tenant_wired_off_by_default(monkeypatch):
    monkeypatch.delenv("WORMBASE_MULTI_TENANT_MCP", raising=False)
    ledger = InMemoryLedger()
    result = run_agent_gateway_build_smoke(
        ledger=ledger,
        company_id=_TEST_COMPANY,
        install_id="install-test",
    )
    assert result.multi_tenant_wired is False
    # Multi-tenant appears in pending_deps as an opt-in (info-only).
    assert any("multi_tenant_mcp" in p for p in result.pending_deps)


def test_build_smoke_reports_multi_tenant_wired_when_enabled(monkeypatch):
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_SLUGS", "acme")
    ledger = InMemoryLedger()
    result = run_agent_gateway_build_smoke(
        ledger=ledger,
        company_id=_TEST_COMPANY,
        install_id="install-test",
    )
    assert result.multi_tenant_wired is True
    # When enabled, it should NOT appear in pending_deps.
    assert not any("multi_tenant_mcp" in p for p in result.pending_deps)


# ---------------------------------------------------------------------------
# 8. WORMBASE_TENANT_QUOTA_LEDGER env knob — final-wave item #7 (2026-05-13)
# ---------------------------------------------------------------------------


def test_tenant_quota_ledger_emission_default_off_uses_in_memory(monkeypatch):
    """Env-knob OFF preserves byte-identical Path 4 in-memory behavior.

    With ``WORMBASE_TENANT_QUOTA_LEDGER`` unset, the wired router's
    quota tracker is an ``InMemoryQuotaTracker`` (not the
    ``LedgerQuotaTracker`` wrapper). This is the Optional-Effect
    Injection doctrine §3 Rule 1 guarantee.
    """
    from wormbase_agent_gateway.tenancy import (
        InMemoryQuotaTracker,
        LedgerQuotaTracker,
    )

    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.delenv("WORMBASE_TENANT_QUOTA_LEDGER", raising=False)
    ledger = InMemoryLedger()
    router = build_tenant_router_from_env(
        install_id="install-test",
        ledger=ledger,
        company_id=_TEST_COMPANY,
    )
    assert router is not None
    quota_tracker = router._quota_tracker  # type: ignore[attr-defined]
    assert isinstance(quota_tracker, InMemoryQuotaTracker)
    assert not isinstance(quota_tracker, LedgerQuotaTracker)


def test_tenant_quota_ledger_emission_on_composes_ledger_tracker(monkeypatch):
    """Env-knob ON composes a LedgerQuotaTracker around the in-memory counter."""
    from wormbase_agent_gateway.tenancy import LedgerQuotaTracker

    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.setenv("WORMBASE_TENANT_QUOTA_LEDGER", "true")
    ledger = InMemoryLedger()
    router = build_tenant_router_from_env(
        install_id="install-test",
        ledger=ledger,
        company_id=_TEST_COMPANY,
    )
    assert router is not None
    quota_tracker = router._quota_tracker  # type: ignore[attr-defined]
    assert isinstance(quota_tracker, LedgerQuotaTracker)


def test_tenant_quota_ledger_emission_on_without_ledger_falls_back(
    monkeypatch,
):
    """Env-knob ON but no ledger / company_id → fall back to in-memory.

    Defense in depth: callers that forget to thread the ledger get a
    warning + the in-memory default, not an exception. The MCP path
    must not boot-fail because an audit-emission dep wasn't wired.
    """
    from wormbase_agent_gateway.tenancy import (
        InMemoryQuotaTracker,
        LedgerQuotaTracker,
    )

    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.setenv("WORMBASE_TENANT_QUOTA_LEDGER", "true")
    router = build_tenant_router_from_env(install_id="install-test")
    assert router is not None
    quota_tracker = router._quota_tracker  # type: ignore[attr-defined]
    assert isinstance(quota_tracker, InMemoryQuotaTracker)
    assert not isinstance(quota_tracker, LedgerQuotaTracker)


def test_tenant_quota_ledger_emits_through_full_wire(monkeypatch):
    """End-to-end: env knob ON + consume → ledger has tenant_quota_consumed.

    Walks the full wire: env knob set → build_tenant_router_from_env →
    consume_quota → in-memory tick → cadence trigger → PEVR write →
    ledger has 4 entries (propose/execute/verify/resolve) for kind
    ``tenant_quota_consumed``.
    """
    import asyncio

    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.setenv("WORMBASE_TENANT_QUOTA_LEDGER", "true")
    # Tight cadence so a small loop fires emission.
    monkeypatch.setenv(
        "WORMBASE_TENANT_QUOTA_LEDGER_COUNT_THRESHOLD", "3",
    )
    monkeypatch.setenv(
        "WORMBASE_TENANT_QUOTA_LEDGER_TIME_THRESHOLD_SECONDS", "100000",
    )
    ledger = InMemoryLedger()
    router = build_tenant_router_from_env(
        install_id="install-test",
        ledger=ledger,
        company_id=_TEST_COMPANY,
    )
    assert router is not None
    router.register(tenant_slug="acme")

    async def _drive():
        ctx = await router.resolve("acme")
        # 3 consumes triggers the count cadence emission.
        await router.consume_quota(ctx)
        await router.consume_quota(ctx)
        await router.consume_quota(ctx)

    asyncio.run(_drive())

    # Pull all ledger rows and assert at least one quota-consumed PEVR.
    rows = asyncio.run(ledger.fetch(_TEST_COMPANY))
    propose_rows = [
        r for r in rows
        if r["kind"] == "propose"
        and r["payload"].get("target_kind") == "tenant_quota_consumed"
    ]
    resolve_rows = [
        r for r in rows
        if r["kind"] == "resolve"
        and r["payload"].get("rationale", "").startswith(
            "periodic tenant-quota audit emission",
        )
    ]
    assert len(propose_rows) >= 1
    assert len(resolve_rows) >= 1


# ---------------------------------------------------------------------------
# 9. Optional-Effect Injection Case 7 — quota_emission_guard (doctrine Addendum 2)
# ---------------------------------------------------------------------------


def test_quota_emission_guard_records_absent_path_when_env_knob_off(monkeypatch):
    """Env knob OFF → guard absent path ticked at boot.

    Verifies the Case 7 ``OptionalEffectGuard`` adoption: when the
    audit-emission capability is absent (env knob unset OR ledger /
    company_id missing), the guard's ``absent_path_count`` is 1 after
    boot and the quota tracker is the bare in-memory impl.
    """
    from wormbase_agent_gateway.tenancy import (
        InMemoryQuotaTracker,
        LedgerQuotaTracker,
    )

    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.delenv("WORMBASE_TENANT_QUOTA_LEDGER", raising=False)
    ledger = InMemoryLedger()
    router = build_tenant_router_from_env(
        install_id="install-test",
        ledger=ledger,
        company_id=_TEST_COMPANY,
    )
    assert router is not None
    assert isinstance(
        router._quota_tracker, InMemoryQuotaTracker,  # type: ignore[attr-defined]
    )
    assert not isinstance(
        router._quota_tracker, LedgerQuotaTracker,  # type: ignore[attr-defined]
    )

    guard = build_tenant_router_from_env._last_quota_emission_guard  # type: ignore[attr-defined]
    assert guard.is_present() is False
    assert guard.metrics() == {
        "present_path_count": 0, "absent_path_count": 1,
    }


def test_quota_emission_guard_records_present_path_when_env_knob_on(monkeypatch):
    """Env knob ON + ledger + company_id → guard present path ticked at boot.

    Verifies the doctrine Rule 9 telemetry: when the audit-emission
    capability is present, the guard's ``present_path_count`` is 1
    after boot and the quota tracker is ``LedgerQuotaTracker``.
    """
    from wormbase_agent_gateway.tenancy import LedgerQuotaTracker

    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.setenv("WORMBASE_TENANT_QUOTA_LEDGER", "true")
    ledger = InMemoryLedger()
    router = build_tenant_router_from_env(
        install_id="install-test",
        ledger=ledger,
        company_id=_TEST_COMPANY,
    )
    assert router is not None
    assert isinstance(
        router._quota_tracker, LedgerQuotaTracker,  # type: ignore[attr-defined]
    )

    guard = build_tenant_router_from_env._last_quota_emission_guard  # type: ignore[attr-defined]
    assert guard.is_present() is True
    assert guard.metrics() == {
        "present_path_count": 1, "absent_path_count": 0,
    }


def test_quota_emission_guard_case_name_matches_doctrine(monkeypatch):
    """The guard's ``case_name`` is the doctrine-canonical identifier.

    Pins the case_name string so log filters / dashboards can rely on
    a stable identifier matching the doctrine's Case 7 nomenclature.
    """
    monkeypatch.setenv("WORMBASE_MULTI_TENANT_MCP", "true")
    monkeypatch.delenv("WORMBASE_TENANT_QUOTA_LEDGER", raising=False)
    build_tenant_router_from_env(install_id="install-test")
    guard = build_tenant_router_from_env._last_quota_emission_guard  # type: ignore[attr-defined]
    assert guard.case_name == "ledger_quota_tracker"
