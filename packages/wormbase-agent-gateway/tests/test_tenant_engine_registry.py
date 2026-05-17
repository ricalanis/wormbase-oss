"""Tests for engine-per-tenant Phase 1 — Protocol + IsolatedTenantContext
+ StaticTenantEngineRegistry.

Per the engine-per-tenant routing design spec at
``docs/superpowers/specs/2026-05-22-engine-per-tenant-routing-design.md``
§4 + §8, Phase 1+2 ships the contract + reference impl. Phases 3+4
(operator-driven admin migration tool + production cutover) are
deferred to operator-driven tooling.

What this pins:

  * :class:`TenantContext` additive engine fields default to None /
    "shared" — existing Path 4 byte-identity preserved.
  * :class:`IsolatedTenantContext` raises when engine is None or
    engine_kind != "isolated" — strict Shape B contract.
  * :class:`StaticTenantEngineRegistry.from_file` reads TOML with the
    ``[tenants.<slug>]`` shape; rejects malformed files.
  * :meth:`StaticTenantEngineRegistry.from_env` honors
    ``WORMBASE_TENANT_ENGINE_MAP_FILE`` pointer; empty env → empty
    registry → every slug resolves to Shape A.
  * :meth:`StaticTenantEngineRegistry.resolve_engine` returns None
    for unmapped slugs (Shape A fallback).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from wormbase_agent_gateway.tenancy import (
    IsolatedTenantContext,
    StaticTenantEngineRegistry,
    TenantContext,
    TenantEngineRegistry,
)


# ---------------------------------------------------------------------------
# TenantContext additive fields — Path 4 byte-identity preserved
# ---------------------------------------------------------------------------


def test_tenant_context_engine_fields_default_to_shared() -> None:
    """Engine-per-tenant Phase 1 (additive): the new engine fields
    default to None / "shared" so existing Path 4 consumers see
    byte-identical behavior."""
    ctx = TenantContext(tenant_slug="acme", company_id=uuid4())
    assert ctx.engine is None
    assert ctx.engine_dsn_secret_ref is None
    assert ctx.engine_kind == "shared"


def test_tenant_context_can_carry_isolated_engine_shape() -> None:
    """Shape B (isolated) construction sets engine + engine_kind +
    engine_dsn_secret_ref simultaneously."""
    sentinel_engine: Any = object()  # any non-None placeholder
    ctx = TenantContext(
        tenant_slug="globex",
        company_id=uuid4(),
        engine=sentinel_engine,
        engine_dsn_secret_ref="vault://wormbase/tenants/globex/engine_dsn",
        engine_kind="isolated",
    )
    assert ctx.engine is sentinel_engine
    assert ctx.engine_kind == "isolated"
    assert ctx.engine_dsn_secret_ref == (
        "vault://wormbase/tenants/globex/engine_dsn"
    )


# ---------------------------------------------------------------------------
# IsolatedTenantContext — strict Shape B contract
# ---------------------------------------------------------------------------


def test_isolated_tenant_context_wraps_valid_shape_b_ctx() -> None:
    """A Shape B ctx (engine + kind="isolated") wraps cleanly."""
    sentinel_engine: Any = object()
    company_id = uuid4()
    ctx = TenantContext(
        tenant_slug="globex",
        company_id=company_id,
        engine=sentinel_engine,
        engine_dsn_secret_ref="vault://wormbase/tenants/globex/engine_dsn",
        engine_kind="isolated",
    )
    isolated = IsolatedTenantContext(ctx)
    assert isolated.engine is sentinel_engine
    assert isolated.tenant_slug == "globex"
    assert isolated.company_id == company_id
    assert isolated.engine_dsn_secret_ref == (
        "vault://wormbase/tenants/globex/engine_dsn"
    )
    assert isolated.ctx is ctx


def test_isolated_tenant_context_raises_on_none_engine() -> None:
    """Shape A (engine=None) refuses to wrap — IsolatedTenantContext
    is for code that REQUIRES isolation, not code that opportunistically
    accepts it."""
    ctx = TenantContext(
        tenant_slug="acme", company_id=uuid4(),
    )  # default engine=None
    with pytest.raises(ValueError):
        IsolatedTenantContext(ctx)


def test_isolated_tenant_context_raises_on_shared_engine_kind() -> None:
    """Even with a non-None engine, engine_kind="shared" is refused —
    the registration policy is what enforces isolation, not just the
    presence of an engine handle."""
    sentinel_engine: Any = object()
    ctx = TenantContext(
        tenant_slug="acme",
        company_id=uuid4(),
        engine=sentinel_engine,
        engine_kind="shared",
    )
    with pytest.raises(ValueError):
        IsolatedTenantContext(ctx)


# ---------------------------------------------------------------------------
# TenantEngineRegistry Protocol — runtime_checkable on StaticTenantEngineRegistry
# ---------------------------------------------------------------------------


def test_static_registry_satisfies_protocol() -> None:
    """The static impl is a structural :class:`TenantEngineRegistry`.

    Post-promotion (carry-forward #4): the Protocol now carries
    :meth:`resolve_engine_region` as part of its surface alongside
    :meth:`resolve_engine` and :meth:`get_dsn_secret_ref`. The static
    impl satisfies all four (post-#6 adds :meth:`resolve_hnsw_params`).
    """
    registry = StaticTenantEngineRegistry()
    assert isinstance(registry, TenantEngineRegistry)
    # Pin the post-promotion surface: every method named on the
    # Protocol must be reachable on the impl.
    assert callable(getattr(registry, "resolve_engine", None))
    assert callable(getattr(registry, "get_dsn_secret_ref", None))
    assert callable(getattr(registry, "resolve_engine_region", None))
    assert callable(getattr(registry, "resolve_hnsw_params", None))


def test_fake_registry_with_hardcoded_regions_satisfies_protocol() -> None:
    """A minimal fake impl that models regions but no real engines
    structurally satisfies the post-promotion Protocol.

    Pins the forward-compat contract: future :class:`TenantEngineRegistry`
    impls (``LedgerTenantEngineRegistry`` Phase 4, remote / vault-backed
    impls) honor the surface from day one. The Protocol method has no
    default body — implementations MUST declare it explicitly. This test
    documents the minimum a new impl needs to satisfy the contract.

    Post-#6: the Protocol also carries :meth:`resolve_hnsw_params`, so
    even a region-only fake must declare it (returning the default-OFF
    ``(None, None)`` tuple is enough to satisfy the contract).
    """

    class _FakeRegionedRegistry:
        """Test-only impl: hardcoded region map, no real engines."""

        def __init__(self, regions: dict[str, str]) -> None:
            self._regions = {k.strip().lower(): v for k, v in regions.items()}

        async def resolve_engine(self, slug: str) -> Any | None:
            return None  # no engine modeling — region-only fake

        def get_dsn_secret_ref(self, slug: str) -> str | None:
            return None

        def resolve_engine_region(self, slug: str) -> str | None:
            return self._regions.get(slug.strip().lower())

        def resolve_hnsw_params(
            self, slug: str,
        ) -> tuple[int | None, int | None]:
            return (None, None)  # default-OFF posture — env globals apply

    fake = _FakeRegionedRegistry(
        {"acme": "us-west-2", "globex": "eu-central-1"},
    )
    assert isinstance(fake, TenantEngineRegistry)
    assert fake.resolve_engine_region("acme") == "us-west-2"
    assert fake.resolve_engine_region("GLOBEX") == "eu-central-1"
    assert fake.resolve_engine_region("unmapped") is None


# ---------------------------------------------------------------------------
# StaticTenantEngineRegistry.from_file
# ---------------------------------------------------------------------------


def _write_toml(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")


def test_from_file_reads_valid_toml(tmp_path: Path) -> None:
    """A valid TOML with one ``[tenants.<slug>]`` table per isolated
    tenant produces a registry that maps the right slugs."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"

        [tenants.globex]
        dsn_secret_ref = "vault://wormbase/tenants/globex/engine_dsn"
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    assert registry.is_registered("acme")
    assert registry.is_registered("globex")
    assert not registry.is_registered("unmapped-tenant")
    assert registry.get_dsn_secret_ref("acme") == (
        "vault://wormbase/tenants/acme/engine_dsn"
    )
    assert registry.registered_slugs() == ["acme", "globex"]


def test_from_file_missing_file_raises(tmp_path: Path) -> None:
    """A missing TOML raises ``FileNotFoundError`` — the operator must
    fix the config before the registry can boot."""
    missing = tmp_path / "no_such_file.toml"
    with pytest.raises(FileNotFoundError):
        StaticTenantEngineRegistry.from_file(str(missing))


def test_from_file_malformed_toml_raises(tmp_path: Path) -> None:
    """A malformed TOML raises ``ValueError`` — fail-fast at boot."""
    cfg = tmp_path / "broken.toml"
    cfg.write_text("[tenants.acme\nthis is not valid toml]\n")
    with pytest.raises(ValueError):
        StaticTenantEngineRegistry.from_file(str(cfg))


def test_from_file_empty_config_yields_empty_registry(tmp_path: Path) -> None:
    """An empty TOML (no ``[tenants.*]`` tables) is valid — every slug
    resolves to Shape A (the default-OFF posture)."""
    cfg = tmp_path / "empty.toml"
    cfg.write_text("# intentionally empty\n")
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    assert registry.registered_slugs() == []
    assert registry.get_dsn_secret_ref("any-slug") is None


def test_from_file_rejects_missing_dsn_secret_ref(tmp_path: Path) -> None:
    """A ``[tenants.<slug>]`` table without a non-empty
    ``dsn_secret_ref`` is rejected — Shape B requires a DSN ref."""
    cfg = tmp_path / "no_dsn.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        # dsn_secret_ref missing
        unrelated_field = "x"
        """,
    )
    with pytest.raises(ValueError):
        StaticTenantEngineRegistry.from_file(str(cfg))


# ---------------------------------------------------------------------------
# StaticTenantEngineRegistry.from_env
# ---------------------------------------------------------------------------


def test_from_env_uses_env_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``WORMBASE_TENANT_ENGINE_MAP_FILE`` env points at a TOML; the
    registry constructs from that path."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://x/y"
        """,
    )
    monkeypatch.setenv("WORMBASE_TENANT_ENGINE_MAP_FILE", str(cfg))
    registry = StaticTenantEngineRegistry.from_env()
    assert registry.is_registered("acme")


def test_from_env_unset_yields_empty_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the env var is unset / empty, the registry has no mappings
    — every slug → Shape A (default-OFF preserves byte-identity)."""
    monkeypatch.delenv("WORMBASE_TENANT_ENGINE_MAP_FILE", raising=False)
    registry = StaticTenantEngineRegistry.from_env()
    assert registry.registered_slugs() == []


# ---------------------------------------------------------------------------
# StaticTenantEngineRegistry.resolve_engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_engine_returns_none_for_unmapped_slug() -> None:
    """Unmapped slug → ``None`` → Shape A fallback. No exception, no
    engine construction, no factory call."""
    factory_calls: list[tuple[str, str]] = []

    async def _factory(slug: str, dsn: str) -> Any:
        factory_calls.append((slug, dsn))
        return object()

    registry = StaticTenantEngineRegistry(
        mappings=[], engine_factory=_factory,
    )
    engine = await registry.resolve_engine("anything")
    assert engine is None
    assert factory_calls == []


@pytest.mark.asyncio
async def test_resolve_engine_constructs_on_first_call_then_caches(
    tmp_path: Path,
) -> None:
    """For a mapped slug, the factory is invoked once on first
    resolve and the engine handle is cached for subsequent calls."""
    sentinel_engine: Any = object()
    factory_calls: list[tuple[str, str]] = []

    async def _factory(slug: str, dsn: str) -> Any:
        factory_calls.append((slug, dsn))
        return sentinel_engine

    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(
        str(cfg), engine_factory=_factory,
    )

    first = await registry.resolve_engine("acme")
    second = await registry.resolve_engine("acme")
    assert first is sentinel_engine
    assert second is sentinel_engine
    assert factory_calls == [
        ("acme", "vault://wormbase/tenants/acme/engine_dsn"),
    ]


@pytest.mark.asyncio
async def test_resolve_engine_raises_when_factory_missing(
    tmp_path: Path,
) -> None:
    """A mapped slug with no engine_factory injected raises — the
    registry can't materialize an engine on its own. Phase 3 will
    wire the credential-broker factory; until then, the test pins
    the explicit failure surface."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://x/y"
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    with pytest.raises(RuntimeError):
        await registry.resolve_engine("acme")


def test_resolve_engine_normalizes_slug_case(tmp_path: Path) -> None:
    """Slug lookups are case-insensitive — the registry normalizes
    on both register and resolve paths so the canonical form is
    stable."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.AcMe]
        dsn_secret_ref = "vault://x/y"
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    assert registry.is_registered("acme")
    assert registry.is_registered("ACME")
    assert registry.get_dsn_secret_ref("AcMe") == "vault://x/y"


# ---------------------------------------------------------------------------
# Multi-region routing (post-rest #7, 2026-05-13) — additive ``region``
# field on TOML + ``resolve_engine_region`` resolution precedence.
# ---------------------------------------------------------------------------


def test_from_file_parses_region_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the TOML carries a ``region`` field, the registry surfaces
    it via :meth:`resolve_engine_region` — the per-slug pin wins over
    the env fallback (which we explicitly unset)."""
    monkeypatch.delenv("WORMBASE_DEFAULT_TENANT_REGION", raising=False)
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"
        region = "us-west-2"

        [tenants.globex]
        dsn_secret_ref = "vault://wormbase/tenants/globex/engine_dsn"
        region = "eu-central-1"
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    assert registry.resolve_engine_region("acme") == "us-west-2"
    assert registry.resolve_engine_region("globex") == "eu-central-1"


def test_from_file_region_absent_yields_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tenant entry without a ``region`` field resolves to ``None``
    when no env fallback is set — preserves byte-identity with the
    pre-region (Phase 1+2 #1) registry shape."""
    monkeypatch.delenv("WORMBASE_DEFAULT_TENANT_REGION", raising=False)
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    assert registry.resolve_engine_region("acme") is None


def test_resolve_engine_region_unmapped_slug_yields_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For an unmapped slug AND no env fallback, the resolved region
    is ``None`` (Shape A byte-identity)."""
    monkeypatch.delenv("WORMBASE_DEFAULT_TENANT_REGION", raising=False)
    registry = StaticTenantEngineRegistry(mappings=[])
    assert registry.resolve_engine_region("not-mapped") is None


def test_resolve_engine_region_env_fallback_when_unpinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a tenant has NO per-slug region pin AND
    ``WORMBASE_DEFAULT_TENANT_REGION`` is set, the env value becomes
    the resolved region — operator-wide default without per-tenant
    entries."""
    monkeypatch.setenv("WORMBASE_DEFAULT_TENANT_REGION", "ap-southeast-1")
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    assert registry.resolve_engine_region("acme") == "ap-southeast-1"


def test_resolve_engine_region_per_slug_pin_wins_over_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolution precedence: the per-slug TOML pin wins over the
    env fallback (so operators can override the install-wide default
    per tenant)."""
    monkeypatch.setenv("WORMBASE_DEFAULT_TENANT_REGION", "ap-southeast-1")
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"
        region = "us-west-2"
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    assert registry.resolve_engine_region("acme") == "us-west-2"


def test_resolve_engine_region_env_fallback_for_unmapped_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when the slug is not in the registry at all, the env
    fallback still applies — so a Shape A tenant ALSO honors the
    install-wide region default."""
    monkeypatch.setenv("WORMBASE_DEFAULT_TENANT_REGION", "eu-central-1")
    registry = StaticTenantEngineRegistry(mappings=[])
    assert registry.resolve_engine_region("anything") == "eu-central-1"


def test_from_file_rejects_empty_region(tmp_path: Path) -> None:
    """An empty / whitespace-only ``region`` is rejected — fail-fast
    at boot rather than silently coercing to ``None``."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://x/y"
        region = "   "
        """,
    )
    with pytest.raises(ValueError):
        StaticTenantEngineRegistry.from_file(str(cfg))


def test_from_file_rejects_non_string_region(tmp_path: Path) -> None:
    """A non-string ``region`` value (e.g. int) is rejected — TOML
    typing is loose, so we enforce the string contract at load."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://x/y"
        region = 42
        """,
    )
    with pytest.raises(ValueError):
        StaticTenantEngineRegistry.from_file(str(cfg))


# ---------------------------------------------------------------------------
# Per-tenant HNSW tuning (next-pass #6, 2026-05-13) — additive
# ``hnsw_m`` / ``hnsw_ef_construction`` fields on TOML +
# ``resolve_hnsw_params`` lookup.
#
# Data-model only: the Phase 3+4 admin migration tool will consume
# these values at migration-apply time per tenant engine. Until that
# tool ships, the registry surfaces them as forward-compat record.
# Default ``(None, None)`` means "use env globals
# (``WORMBASE_HNSW_M`` / ``WORMBASE_HNSW_EF_CONSTRUCTION``) as wired
# by the v019 migration." Ranges match the v019 env-knob ranges
# (m ∈ [4, 64], ef_construction ∈ [16, 256]).
# ---------------------------------------------------------------------------


def test_from_file_parses_hnsw_params_when_present(tmp_path: Path) -> None:
    """When the TOML carries ``hnsw_m`` / ``hnsw_ef_construction`` the
    registry surfaces them via :meth:`resolve_hnsw_params`."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"
        hnsw_m = 24
        hnsw_ef_construction = 128

        [tenants.globex]
        dsn_secret_ref = "vault://wormbase/tenants/globex/engine_dsn"
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    assert registry.resolve_hnsw_params("acme") == (24, 128)
    # No overrides → (None, None) (use env globals).
    assert registry.resolve_hnsw_params("globex") == (None, None)


def test_from_file_hnsw_params_absent_yields_none(tmp_path: Path) -> None:
    """A tenant entry without HNSW fields resolves to ``(None, None)``
    — preserves byte-identity with the pre-tuning registry shape."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://wormbase/tenants/acme/engine_dsn"
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    assert registry.resolve_hnsw_params("acme") == (None, None)


def test_resolve_hnsw_params_unmapped_slug_yields_none() -> None:
    """For an unmapped slug, the resolved tuple is ``(None, None)`` —
    every Shape A tenant honors the env-globals fallback at the
    consumer site."""
    registry = StaticTenantEngineRegistry(mappings=[])
    assert registry.resolve_hnsw_params("not-mapped") == (None, None)


def test_from_file_parses_hnsw_params_independently(tmp_path: Path) -> None:
    """Each HNSW field is independently optional — overriding ``m``
    only (or ``ef_construction`` only) is supported because v019's
    env globals are read independently too."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://x/y"
        hnsw_m = 32
        # hnsw_ef_construction intentionally absent
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    assert registry.resolve_hnsw_params("acme") == (32, None)


def test_from_file_rejects_hnsw_m_below_range(tmp_path: Path) -> None:
    """``hnsw_m`` below the v019 range [4, 64] fails at boot — silent
    coercion would degrade graph quality at migration-apply time."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://x/y"
        hnsw_m = 3
        """,
    )
    with pytest.raises(ValueError):
        StaticTenantEngineRegistry.from_file(str(cfg))


def test_from_file_rejects_hnsw_m_above_range(tmp_path: Path) -> None:
    """``hnsw_m`` above the v019 range [4, 64] fails at boot."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://x/y"
        hnsw_m = 65
        """,
    )
    with pytest.raises(ValueError):
        StaticTenantEngineRegistry.from_file(str(cfg))


def test_from_file_rejects_hnsw_ef_construction_below_range(
    tmp_path: Path,
) -> None:
    """``hnsw_ef_construction`` below v019 range [16, 256] fails at boot."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://x/y"
        hnsw_ef_construction = 15
        """,
    )
    with pytest.raises(ValueError):
        StaticTenantEngineRegistry.from_file(str(cfg))


def test_from_file_rejects_hnsw_ef_construction_above_range(
    tmp_path: Path,
) -> None:
    """``hnsw_ef_construction`` above v019 range [16, 256] fails at boot."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://x/y"
        hnsw_ef_construction = 257
        """,
    )
    with pytest.raises(ValueError):
        StaticTenantEngineRegistry.from_file(str(cfg))


def test_from_file_rejects_non_int_hnsw_m(tmp_path: Path) -> None:
    """A non-int ``hnsw_m`` (e.g. string) is rejected — TOML typing
    is loose, so we enforce int contract at load. Catches typos like
    ``hnsw_m = "24"``."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://x/y"
        hnsw_m = "24"
        """,
    )
    with pytest.raises(ValueError):
        StaticTenantEngineRegistry.from_file(str(cfg))


def test_from_file_rejects_bool_hnsw_m(tmp_path: Path) -> None:
    """TOML loads ``true`` / ``false`` as ``bool`` (Python ``bool`` is
    a subclass of ``int``). We reject ``bool`` explicitly so a typo
    like ``hnsw_m = true`` does not silently coerce to ``1``."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.acme]
        dsn_secret_ref = "vault://x/y"
        hnsw_m = true
        """,
    )
    with pytest.raises(ValueError):
        StaticTenantEngineRegistry.from_file(str(cfg))


def test_from_file_hnsw_range_boundaries_accepted(tmp_path: Path) -> None:
    """Boundary values ``m=4``, ``m=64``, ``ef=16``, ``ef=256`` are
    inclusively valid at boot — pins the v019 range contract exactly."""
    cfg = tmp_path / "engines.toml"
    _write_toml(
        cfg,
        """
        [tenants.lo]
        dsn_secret_ref = "vault://x/lo"
        hnsw_m = 4
        hnsw_ef_construction = 16

        [tenants.hi]
        dsn_secret_ref = "vault://x/hi"
        hnsw_m = 64
        hnsw_ef_construction = 256
        """,
    )
    registry = StaticTenantEngineRegistry.from_file(str(cfg))
    assert registry.resolve_hnsw_params("lo") == (4, 16)
    assert registry.resolve_hnsw_params("hi") == (64, 256)


def test_static_registry_satisfies_protocol_with_hnsw_method() -> None:
    """Post-#6 promotion: the Protocol now carries
    :meth:`resolve_hnsw_params` alongside :meth:`resolve_engine`,
    :meth:`get_dsn_secret_ref`, and :meth:`resolve_engine_region`.
    The static impl satisfies all four."""
    registry = StaticTenantEngineRegistry()
    assert isinstance(registry, TenantEngineRegistry)
    assert callable(getattr(registry, "resolve_hnsw_params", None))


def test_fake_registry_with_hardcoded_hnsw_satisfies_protocol() -> None:
    """A minimal fake impl that models HNSW overrides but no real
    engines structurally satisfies the post-#6 Protocol. Pins the
    forward-compat contract: future :class:`TenantEngineRegistry`
    impls (``LedgerTenantEngineRegistry`` Phase 4, remote / vault-
    backed impls) honor :meth:`resolve_hnsw_params` from day one."""

    class _FakeHnswRegistry:
        """Test-only impl: hardcoded HNSW map, no real engines."""

        def __init__(
            self, params: dict[str, tuple[int | None, int | None]],
        ) -> None:
            self._params = {k.strip().lower(): v for k, v in params.items()}

        async def resolve_engine(self, slug: str) -> Any | None:
            return None  # no engine modeling — HNSW-only fake

        def get_dsn_secret_ref(self, slug: str) -> str | None:
            return None

        def resolve_engine_region(self, slug: str) -> str | None:
            return None

        def resolve_hnsw_params(
            self, slug: str,
        ) -> tuple[int | None, int | None]:
            return self._params.get(slug.strip().lower(), (None, None))

    fake = _FakeHnswRegistry(
        {"acme": (24, 128), "globex": (32, None)},
    )
    assert isinstance(fake, TenantEngineRegistry)
    assert fake.resolve_hnsw_params("acme") == (24, 128)
    assert fake.resolve_hnsw_params("GLOBEX") == (32, None)
    assert fake.resolve_hnsw_params("unmapped") == (None, None)
