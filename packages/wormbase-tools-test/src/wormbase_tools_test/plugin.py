"""pytest plugin — adds ``--connector`` and parametrizes a conformance class.

Usage:

    pytest --connector my_pkg.my_module:MyConnector

The plugin imports ``MyConnector`` from ``my_pkg.my_module``, builds
six tests (one per Connector Protocol invariant), and runs them. To
override the secrets shape or the known resource id, declare fixtures
in your ``conftest.py``:

    @pytest.fixture
    def connector_valid_secrets():
        from my_pkg.my_module import SecretBundle
        return SecretBundle({"key": "value"})

    @pytest.fixture
    def connector_invalid_secrets():
        from my_pkg.my_module import SecretBundle
        return SecretBundle({})  # missing required keys

    @pytest.fixture
    def connector_known_resource_id():
        return "known-resource-id"

    @pytest.fixture
    def connector_is_skeletal():
        return False  # set True for status='coming_soon' connectors
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from .invariants import (
    assert_authenticate_invalid_raises,
    assert_authenticate_valid_returns_authhandle,
    assert_discover_stable_ordering,
    assert_profile_idempotent,
    assert_sample_deterministic,
    assert_watch_cancellable,
)


# ---------------------------------------------------------------------------
# CLI flag registration
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """When --connector is set, register our conformance module so pytest
    collects its tests even if the user invokes pytest from a directory
    that contains no test files of its own.
    """
    spec = config.getoption("wormbase_connector_spec")
    if spec:
        # Mark a flag the collection hook reads.
        config._wormbase_collect_conformance = True  # type: ignore[attr-defined]


def pytest_collection(session: pytest.Session) -> None:
    """If --connector is set and no items collected, inject this module."""
    if not getattr(session.config, "_wormbase_collect_conformance", False):
        return
    # Force-collect this plugin module so the TestConnectorProtocolConformance
    # class is visible to the runner.
    import wormbase_tools_test.plugin as _plugin_mod
    plugin_path = _plugin_mod.__file__
    if plugin_path and plugin_path not in [str(a) for a in session.config.args]:
        session.config.args.append(plugin_path)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup(
        "wormbase-tools-test",
        "WormBase Connector Protocol conformance harness",
    )
    group.addoption(
        "--connector",
        action="store",
        dest="wormbase_connector_spec",
        default=None,
        metavar="MODULE:CLASS",
        help=(
            "Connector class to test, given as 'module.path:ClassName'. "
            "When set, the harness runs six invariant tests against the "
            "named class. Override secrets/resource via the "
            "connector_valid_secrets, connector_invalid_secrets, and "
            "connector_known_resource_id fixtures."
        ),
    )
    group.addoption(
        "--connector-sample-n",
        action="store",
        dest="wormbase_connector_sample_n",
        default="32",
        help="Value passed as ``n`` to ``sample()`` (default 32).",
    )
    group.addoption(
        "--connector-byte-cap-strict",
        action="store_true",
        dest="wormbase_connector_byte_cap_strict",
        default=False,
        help=(
            "Treat ``n`` as a strict byte cap (assert len(sample) <= n). "
            "Set for byte-streaming connectors (s3_csv, http_csv, MCP)."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_connector_class(spec: str) -> type[Any]:
    """Resolve 'module.path:ClassName' to the class object."""
    if ":" not in spec:
        raise pytest.UsageError(
            f"--connector spec {spec!r} must be 'module.path:ClassName'"
        )
    module_path, class_name = spec.split(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise pytest.UsageError(
            f"--connector spec {spec!r}: cannot import {module_path!r}: {e}"
        ) from e
    try:
        return getattr(module, class_name)
    except AttributeError as e:
        raise pytest.UsageError(
            f"--connector spec {spec!r}: "
            f"module {module_path!r} has no attribute {class_name!r}"
        ) from e


# ---------------------------------------------------------------------------
# Fixtures users can override
# ---------------------------------------------------------------------------


@pytest.fixture
def connector_class(request: pytest.FixtureRequest) -> type[Any] | None:
    """Resolve the --connector CLI flag to an importable class."""
    spec = request.config.getoption("wormbase_connector_spec")
    if not spec:
        return None
    return _load_connector_class(spec)


@pytest.fixture
def connector_instance(connector_class: type[Any] | None) -> Any:
    """Build a fresh connector instance per test."""
    if connector_class is None:
        pytest.skip(
            "no --connector specified (run with --connector module:ClassName)"
        )
    return connector_class()


@pytest.fixture
def connector_valid_secrets(connector_instance: Any) -> Any:
    """Default valid secrets — best-effort.

    The harness probes a few common payload shapes. Most connectors
    will want to override this fixture in their own conftest.
    """
    # Attempt to get a SecretBundle-shaped object from the same module
    # the connector lives in (mirrors how csv_local imports its types
    # from wormbase_lake_surfaces.types).
    SecretBundle = _resolve_secret_bundle(connector_instance)
    return SecretBundle(payload={})


@pytest.fixture
def connector_invalid_secrets(connector_instance: Any) -> Any:
    """Default invalid secrets — empty payload."""
    SecretBundle = _resolve_secret_bundle(connector_instance)
    return SecretBundle(payload={})


@pytest.fixture
def connector_known_resource_id() -> str | None:
    """Override to pin the resource_id used for profile/sample tests."""
    return None


@pytest.fixture
def connector_is_skeletal(connector_instance: Any) -> bool:
    """Skeletal connectors raise NotImplementedError from profile/sample/watch."""
    status = getattr(connector_instance, "status", "production")
    return status == "coming_soon"


@pytest.fixture
def connector_sample_n(request: pytest.FixtureRequest) -> int:
    return int(request.config.getoption("wormbase_connector_sample_n"))


@pytest.fixture
def connector_byte_cap_strict(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("wormbase_connector_byte_cap_strict"))


def _resolve_secret_bundle(connector_instance: Any) -> Any:
    """Look up the SecretBundle dataclass the connector expects.

    Searches in this order:

    1. The module the connector class is defined in (its ``SecretBundle``).
    2. ``wormbase_lake_surfaces.types.SecretBundle`` (monorepo).
    3. A fallback dataclass with a ``payload`` attribute.
    """
    cls = type(connector_instance)
    module = importlib.import_module(cls.__module__)
    sb = getattr(module, "SecretBundle", None)
    if sb is not None:
        return sb
    try:
        types_mod = importlib.import_module("wormbase_lake_surfaces.types")
        return types_mod.SecretBundle
    except ImportError:
        pass

    # Last resort: a stand-in dataclass.
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _SecretBundle:
        payload: dict[str, Any]

    return _SecretBundle


# ---------------------------------------------------------------------------
# The conformance test class — auto-discovered by pytest
# ---------------------------------------------------------------------------


class TestConnectorProtocolConformance:
    """Six tests asserting the Connector Protocol contract.

    Each method maps 1:1 to an invariant in
    :mod:`wormbase_tools_test.invariants`. The pytest plugin ensures
    they run only when ``--connector`` is set; otherwise they skip.
    """

    @pytest.mark.asyncio
    async def test_authenticate_valid_returns_authhandle(
        self,
        connector_instance: Any,
        connector_valid_secrets: Any,
    ) -> None:
        await assert_authenticate_valid_returns_authhandle(
            connector_instance, connector_valid_secrets
        )

    @pytest.mark.asyncio
    async def test_authenticate_invalid_raises(
        self,
        connector_instance: Any,
        connector_invalid_secrets: Any,
    ) -> None:
        await assert_authenticate_invalid_raises(
            connector_instance, connector_invalid_secrets
        )

    @pytest.mark.asyncio
    async def test_discover_stable_ordering(
        self,
        connector_instance: Any,
        connector_valid_secrets: Any,
    ) -> None:
        handle = await connector_instance.authenticate(connector_valid_secrets)
        await assert_discover_stable_ordering(connector_instance, handle)

    @pytest.mark.asyncio
    async def test_profile_idempotent(
        self,
        connector_instance: Any,
        connector_valid_secrets: Any,
        connector_known_resource_id: str | None,
        connector_is_skeletal: bool,
    ) -> None:
        handle = await connector_instance.authenticate(connector_valid_secrets)
        rid = connector_known_resource_id
        if rid is None and not connector_is_skeletal:
            proposals = await connector_instance.discover(handle)
            if proposals:
                rid = proposals[0].resource_id
        if rid is None and not connector_is_skeletal:
            pytest.skip(
                "no connector_known_resource_id and discover returned []; "
                "set the fixture to test profile()"
            )
        await assert_profile_idempotent(
            connector_instance,
            handle,
            rid or "",
            is_skeletal=connector_is_skeletal,
        )

    @pytest.mark.asyncio
    async def test_sample_deterministic(
        self,
        connector_instance: Any,
        connector_valid_secrets: Any,
        connector_known_resource_id: str | None,
        connector_is_skeletal: bool,
        connector_sample_n: int,
        connector_byte_cap_strict: bool,
    ) -> None:
        handle = await connector_instance.authenticate(connector_valid_secrets)
        rid = connector_known_resource_id
        if rid is None and not connector_is_skeletal:
            proposals = await connector_instance.discover(handle)
            if proposals:
                rid = proposals[0].resource_id
        if rid is None and not connector_is_skeletal:
            pytest.skip(
                "no connector_known_resource_id and discover returned []; "
                "set the fixture to test sample()"
            )
        await assert_sample_deterministic(
            connector_instance,
            handle,
            rid or "",
            n=connector_sample_n,
            is_skeletal=connector_is_skeletal,
            byte_cap_strict=connector_byte_cap_strict,
        )

    @pytest.mark.asyncio
    async def test_watch_cancellable(
        self,
        connector_instance: Any,
        connector_valid_secrets: Any,
        connector_known_resource_id: str | None,
        connector_is_skeletal: bool,
    ) -> None:
        handle = await connector_instance.authenticate(connector_valid_secrets)
        rid = connector_known_resource_id
        if rid is None and not connector_is_skeletal:
            proposals = await connector_instance.discover(handle)
            if proposals:
                rid = proposals[0].resource_id
        await assert_watch_cancellable(
            connector_instance,
            handle,
            rid or "",
            is_skeletal=connector_is_skeletal,
        )
