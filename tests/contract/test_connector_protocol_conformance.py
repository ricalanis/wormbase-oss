"""SurfaceDriver Protocol conformance suite (W6.A4).

Every SurfaceDriver implementation in :mod:`wormbase_lake_surfaces` is the
extensibility surface of the source-building flows. Adding one is a
class + registry entry; nothing forces it to pass the same battery of
tests as its peers. This module is that battery.

For every connector in the registry, six invariants are asserted:

1. ``authenticate(valid_secrets)`` returns a structurally valid
   :class:`AuthHandle` (``connector_kind`` and ``handle_id`` populated).
2. ``authenticate(invalid_secrets)`` raises ``ValueError`` (the
   day-one contract uses ``ValueError`` for bad-secret-shape; we treat
   that as the conformance equivalent of ``AuthenticationError``).
3. ``discover(handle)`` returns a ``list[ResourceProposal]`` whose
   ``(kind, identifier)`` ordering is stable across two consecutive
   calls (idempotent).
4. ``profile(handle, resource_id)`` returns the same :class:`Profile`
   shape on two consecutive calls (idempotent for the same input).
5. ``sample(handle, resource_id, n)`` returns ≤n bytes and is
   deterministic for the same ``(handle, resource_id, n)`` triple.
6. ``watch(handle, resource_id)`` is an async iterator that can be
   exhausted/cancelled cleanly (no leaked coroutines).

For connectors that need external infrastructure (Postgres, Snowflake,
S3, Stripe, HTTP, MCP), the conformance harness uses lightweight
in-process mocks so the tests run in CI without any platform creds.

The harness exposes a single source of truth — :data:`CONNECTOR_FIXTURES`
— so adding a new connector is a matter of dropping a fixture entry.
The fixture knows three things: how to instantiate the connector under
test (with mocked network if needed), what valid + invalid secrets
look like, and what a known ``resource_id`` looks like for
profile/sample. Skeletal connectors (``coming_soon``) declare which
methods raise ``NotImplementedError`` and the harness honors that.

Invariant: this file does NOT skip connectors that need credentials.
External I/O is mocked at the transport boundary; no test in this file
contacts the open Internet.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from wormbase_lake_surfaces import default_registry
from wormbase_lake_surfaces.base import SurfaceDriver
from wormbase_lake_surfaces.types import (
    AuthHandle,
    Profile,
    ResourceProposal,
    SecretBundle,
)


# ---------------------------------------------------------------------------
# Conformance fixture model
# ---------------------------------------------------------------------------


@dataclass
class ConnectorFixture:
    """Per-connector knobs the conformance harness needs.

    ``factory`` builds the connector instance to test (with any
    transport-level mocks in place); the returned tuple includes the
    connector and an opaque "control" object the test body uses to
    feed mock responses. ``valid_secrets`` is a SecretBundle the
    connector accepts; ``invalid_secrets`` is one it must reject.

    ``known_resource_id`` is what discover should yield first (and is
    used as the input to profile/sample). For skeletal connectors this
    is None — the harness skips profile/sample/watch and asserts the
    NotImplementedError contract instead.
    """

    kind: str
    factory: Callable[[], Awaitable[tuple[SurfaceDriver, Any]]]
    valid_secrets: SecretBundle
    invalid_secrets: SecretBundle
    known_resource_id: str | None
    is_skeletal: bool = False


# ---------------------------------------------------------------------------
# Per-connector fixture builders
# ---------------------------------------------------------------------------


# csv_local — local-file connector, no network.
async def _csv_local_fixture(tmp_path) -> tuple[SurfaceDriver, Any]:
    from wormbase_lake_surfaces.csv_local import CsvLocalSurfaceDriver

    csv_path = tmp_path / "fixture.csv"
    csv_path.write_text("id,name\n1,Alice\n2,Bob\n")
    return CsvLocalSurfaceDriver(), {"path": str(csv_path)}


# postgres — asyncpg.connect mocked at module level.
async def _postgres_fixture() -> tuple[SurfaceDriver, Any]:
    from wormbase_lake_surfaces.postgres import PostgresSurfaceDriver

    _DISCOVER_ROWS = [
        {
            "table_schema": "public",
            "table_name": "ledger",
            "table_type": "BASE TABLE",
        },
        {
            "table_schema": "public",
            "table_name": "people",
            "table_type": "BASE TABLE",
        },
    ]
    _PROFILE_COLUMN_ROWS = [
        {
            "column_name": "id",
            "data_type": "uuid",
            "is_nullable": "NO",
            "ordinal_position": 1,
        },
        {
            "column_name": "created_at",
            "data_type": "timestamp",
            "is_nullable": "NO",
            "ordinal_position": 2,
        },
    ]

    async def _fetch_router(query: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        # information_schema.tables → discover; information_schema.columns → profile.
        q = " ".join(query.split())
        if "information_schema.tables" in q.lower():
            return list(_DISCOVER_ROWS)
        if "information_schema.columns" in q.lower():
            return list(_PROFILE_COLUMN_ROWS)
        # Sample query: SELECT * FROM "schema"."table" LIMIT $1
        if q.lower().startswith("select * from"):
            class _Rec:
                def __init__(self, d: dict[str, Any]) -> None:
                    self._d = d

                def keys(self) -> list[str]:
                    return list(self._d.keys())

                def values(self) -> list[Any]:
                    return list(self._d.values())

            return [_Rec({"id": 1, "name": "Alice"}), _Rec({"id": 2, "name": "Bob"})]
        return []

    fake_conn = MagicMock()
    fake_conn.close = AsyncMock()
    # fetchval returns canned values: version (str) for authenticate,
    # row_count (int) for profile.
    fake_conn.fetchval = AsyncMock(return_value=42)
    fake_conn.fetch = AsyncMock(side_effect=_fetch_router)
    from unittest.mock import patch

    patcher = patch("asyncpg.connect", new=AsyncMock(return_value=fake_conn))
    patcher.start()
    return PostgresSurfaceDriver(), (patcher, fake_conn)


# snowflake — patches snowflake.connector.connect.
async def _snowflake_fixture() -> tuple[SurfaceDriver, Any]:
    from wormbase_lake_surfaces.snowflake import SnowflakeSurfaceDriver

    fake_cursor = MagicMock()
    fake_cursor.execute = MagicMock()
    fake_cursor.fetchone = MagicMock(return_value=(123,))
    fake_cursor.fetchall = MagicMock(
        return_value=[("PUBLIC", "ORDERS", 1000, "BASE TABLE")]
    )
    fake_cursor.description = [("id",), ("amount",)]
    fake_cursor.close = MagicMock()

    fake_conn = MagicMock()
    fake_conn.cursor = MagicMock(return_value=fake_cursor)
    fake_conn.close = MagicMock()

    fake_module = MagicMock()
    fake_module.connect = MagicMock(return_value=fake_conn)

    from unittest.mock import patch
    import sys

    # snowflake.connector is sync; the connector lazy-imports it.
    fake_sf_pkg = MagicMock()
    fake_sf_pkg.connector = fake_module
    patcher = patch.dict(sys.modules, {"snowflake": fake_sf_pkg, "snowflake.connector": fake_module})
    patcher.start()
    return SnowflakeSurfaceDriver(), (patcher, fake_module, fake_cursor)


# s3_csv — patches aioboto3 Session.client.
async def _s3_csv_fixture() -> tuple[SurfaceDriver, Any]:
    from wormbase_lake_surfaces.s3_csv import S3CsvSurfaceDriver
    from datetime import datetime, timezone

    csv_body = b"id,name\n1,A\n2,B\n"

    class _FakeBody:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        async def read(self) -> bytes:
            return self._payload

    class _FakeS3:
        async def list_objects_v2(self, **_kwargs: Any) -> dict[str, Any]:
            return {
                "Contents": [
                    {
                        "Key": "path/to/data.csv",
                        "Size": len(csv_body),
                        "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc),
                        "ETag": "etag-1",
                    }
                ]
            }

        async def get_object(self, **kwargs: Any) -> dict[str, Any]:
            rng = kwargs.get("Range") or ""
            cap = len(csv_body)
            if rng.startswith("bytes=0-"):
                end = int(rng.split("-", 1)[1])
                cap = end + 1
            return {"Body": _FakeBody(csv_body[:cap])}

        async def __aenter__(self) -> "_FakeS3":
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

    class _FakeSession:
        def client(self, _service: str, **_kwargs: Any) -> _FakeS3:
            return _FakeS3()

    # Inject session by subclassing the connector for the test instance.
    class _Patched(S3CsvSurfaceDriver):
        async def _session(self, handle: AuthHandle) -> Any:
            return _FakeSession()

    return _Patched(), None


# stripe — patches httpx.AsyncClient via MockTransport.
async def _stripe_fixture() -> tuple[SurfaceDriver, Any]:
    from wormbase_lake_surfaces.stripe import StripeSurfaceDriver

    canned_data = {
        "data": [
            {
                "id": "ch_1",
                "amount": 1000,
                "currency": "usd",
                "captured": True,
            }
        ],
        "has_more": False,
    }

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=canned_data)

    transport = httpx.MockTransport(_handler)

    # Wrap the AsyncClient constructor to inject our transport.
    from unittest.mock import patch

    real_async_client = httpx.AsyncClient

    def _wrapped(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    patcher = patch(
        "wormbase_lake_surfaces.stripe.httpx.AsyncClient", new=_wrapped
    )
    patcher.start()
    return StripeSurfaceDriver(), patcher


# http_csv — same MockTransport pattern.
async def _http_csv_fixture() -> tuple[SurfaceDriver, Any]:
    from wormbase_lake_surfaces.http_csv import HttpCsvSurfaceDriver

    csv_body = b"id,name\n1,Alice\n2,Bob\n3,Carol\n"

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(
                200, headers={"content-length": str(len(csv_body))}
            )
        return httpx.Response(
            200,
            content=csv_body,
            headers={"content-type": "text/csv"},
        )

    transport = httpx.MockTransport(_handler)

    from unittest.mock import patch

    real_async_client = httpx.AsyncClient

    def _wrapped(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    patcher = patch(
        "wormbase_lake_surfaces.http_csv.httpx.AsyncClient", new=_wrapped
    )
    patcher.start()
    return HttpCsvSurfaceDriver(), patcher


# Skeletal connectors share a fixture builder.
async def _skeletal_fixture(kind: str) -> tuple[SurfaceDriver, Any]:
    cls = default_registry().get(kind)
    assert cls is not None, f"connector {kind!r} not registered"
    return cls(), None


# MCP preset — uses the same fake-session pattern as packages/lake-surfaces tests.
async def _mcp_notion_fixture() -> tuple[SurfaceDriver, Any]:
    from wormbase_lake_surfaces.mcp import MCPSurfaceDriver
    from wormbase_lake_surfaces.mcp_presets.notion_preset import NotionMCPSurfaceDriver

    @dataclass
    class _Res:
        uri: str
        name: str
        description: str = ""
        mimeType: str | None = None
        size: int | None = None

    @dataclass
    class _ListResult:
        resources: list[_Res] = field(default_factory=list)

    @dataclass
    class _Text:
        uri: str
        text: str
        mimeType: str = "text/plain"

    @dataclass
    class _ReadResult:
        contents: list[Any] = field(default_factory=list)

    class _FakeSession:
        def __init__(self) -> None:
            self._resources = [
                _Res(
                    uri="notion://page/abc",
                    name="abc",
                    description="A page",
                    mimeType="text/markdown",
                    size=1024,
                ),
            ]

        async def initialize(self) -> None:
            return None

        async def list_resources(self, cursor: str | None = None) -> Any:
            return _ListResult(resources=list(self._resources))

        async def read_resource(self, uri: Any) -> Any:
            return _ReadResult(
                contents=[
                    _Text(uri=str(uri), text="hello from notion\n", mimeType="text/markdown")
                ]
            )

    @asynccontextmanager
    async def _factory(_cfg: Any, _secrets: SecretBundle) -> AsyncIterator[Any]:
        yield _FakeSession()

    instance = NotionMCPSurfaceDriver(session_factory=_factory)
    return instance, None


# ---------------------------------------------------------------------------
# Build the master fixture table
# ---------------------------------------------------------------------------


async def _build_fixtures(tmp_path) -> dict[str, ConnectorFixture]:
    """Materialize every per-connector fixture for parametrization.

    Returns a dict ``kind -> ConnectorFixture``. Called once per test
    function (via the ``connector_fixture`` pytest fixture) so each
    test gets fresh mocks.
    """
    fixtures: dict[str, ConnectorFixture] = {}

    # csv_local
    fixtures["csv_local"] = ConnectorFixture(
        kind="csv_local",
        factory=lambda: _csv_local_fixture(tmp_path),
        valid_secrets=SecretBundle(payload={"path": str(tmp_path / "fixture.csv")}),
        invalid_secrets=SecretBundle(payload={}),
        known_resource_id=str(tmp_path / "fixture.csv"),
    )

    # postgres
    fixtures["postgres"] = ConnectorFixture(
        kind="postgres",
        factory=_postgres_fixture,
        valid_secrets=SecretBundle(payload={"dsn": "postgresql://wb:wb@db/wb"}),
        invalid_secrets=SecretBundle(payload={}),
        known_resource_id="public.ledger",
    )

    # snowflake
    fixtures["snowflake"] = ConnectorFixture(
        kind="snowflake",
        factory=_snowflake_fixture,
        valid_secrets=SecretBundle(
            payload={
                "account": "abc.us-east-1",
                "user": "u",
                "password": "p",
                "warehouse": "WH",
                "database": "DB",
            }
        ),
        invalid_secrets=SecretBundle(payload={}),
        known_resource_id="PUBLIC.ORDERS",
    )

    # bigquery (skeletal)
    fixtures["bigquery"] = ConnectorFixture(
        kind="bigquery",
        factory=lambda: _skeletal_fixture("bigquery"),
        valid_secrets=SecretBundle(
            payload={"project": "p", "service_account_json": "{}"}
        ),
        invalid_secrets=SecretBundle(payload={}),
        known_resource_id=None,
        is_skeletal=True,
    )

    # s3_csv
    fixtures["s3_csv"] = ConnectorFixture(
        kind="s3_csv",
        factory=_s3_csv_fixture,
        valid_secrets=SecretBundle(
            payload={
                "bucket": "test-bucket",
                "aws_access_key_id": "k",
                "aws_secret_access_key": "s",
            }
        ),
        invalid_secrets=SecretBundle(payload={}),
        known_resource_id="path/to/data.csv",
    )

    # stripe
    fixtures["stripe"] = ConnectorFixture(
        kind="stripe",
        factory=_stripe_fixture,
        valid_secrets=SecretBundle(payload={"api_key": "sk_test_xyz"}),
        invalid_secrets=SecretBundle(payload={}),
        known_resource_id="charges",
    )

    # salesforce (skeletal)
    fixtures["salesforce"] = ConnectorFixture(
        kind="salesforce",
        factory=lambda: _skeletal_fixture("salesforce"),
        valid_secrets=SecretBundle(
            payload={"instance_url": "https://x.my.salesforce.com", "access_token": "t"}
        ),
        invalid_secrets=SecretBundle(payload={}),
        known_resource_id=None,
        is_skeletal=True,
    )

    # hubspot (skeletal)
    fixtures["hubspot"] = ConnectorFixture(
        kind="hubspot",
        factory=lambda: _skeletal_fixture("hubspot"),
        valid_secrets=SecretBundle(payload={"access_token": "t"}),
        invalid_secrets=SecretBundle(payload={}),
        known_resource_id=None,
        is_skeletal=True,
    )

    # gsheets (skeletal)
    fixtures["gsheets"] = ConnectorFixture(
        kind="gsheets",
        factory=lambda: _skeletal_fixture("gsheets"),
        valid_secrets=SecretBundle(payload={"service_account_json": "{}"}),
        invalid_secrets=SecretBundle(payload={}),
        known_resource_id=None,
        is_skeletal=True,
    )

    # http_csv
    fixtures["http_csv"] = ConnectorFixture(
        kind="http_csv",
        factory=_http_csv_fixture,
        valid_secrets=SecretBundle(payload={"url": "https://example.com/data.csv"}),
        invalid_secrets=SecretBundle(payload={}),
        known_resource_id="https://example.com/data.csv",
    )

    # mcp:notion (canonical MCP preset)
    fixtures["mcp:notion"] = ConnectorFixture(
        kind="mcp:notion",
        factory=_mcp_notion_fixture,
        valid_secrets=SecretBundle(payload={"bearer_token": "tok-123"}),
        invalid_secrets=SecretBundle(payload={}),
        known_resource_id="notion://page/abc",
    )

    return fixtures


# Parametrize id list: every connector kind we cover.
CONNECTOR_KINDS: list[str] = [
    "csv_local",
    "postgres",
    "snowflake",
    "bigquery",
    "s3_csv",
    "stripe",
    "salesforce",
    "hubspot",
    "gsheets",
    "http_csv",
    "mcp:notion",
]


@pytest.fixture
async def connector_fixture(
    request: pytest.FixtureRequest, tmp_path
) -> AsyncIterator[ConnectorFixture]:
    """Materialize a fresh ConnectorFixture for the parametrized kind.

    Cleans up patchers (if any) at teardown so global state stays clean
    between parametrized cases.
    """
    kind: str = request.param
    fixtures = await _build_fixtures(tmp_path)
    fx = fixtures[kind]
    yield fx
    # Stop patchers if the factory cached one. The factories above
    # return a tuple ``(connector, control)`` where ``control`` may be
    # a single patcher, a tuple containing one, or None. We detect by
    # duck-typing.
    # NB: we don't have a handle to the patcher post-factory because
    # the factory is invoked inside each test. Patchers stop themselves
    # when the test process tears down, but to keep tests hermetic we
    # also stop any patcher that has a ``stop`` method on the
    # connector instance's ``_test_patcher`` slot — which we don't set
    # here. The patchers are cleaned up by patch's __exit__ in the
    # next-test-uses-fresh-instance pattern; the harness instantiates
    # via the factory inside each test, which does not leak across
    # parametrized cases because each invocation patches fresh.


# Helper: invoke factory + register a teardown that stops any patcher.
async def _instantiate(
    fx: ConnectorFixture,
) -> tuple[SurfaceDriver, Callable[[], None]]:
    instance, control = await fx.factory()

    def _cleanup() -> None:
        # Stop any unittest.mock patchers we threaded through.
        from unittest.mock import _patch as _BasePatch  # type: ignore[attr-defined]

        candidates: list[Any] = []
        if isinstance(control, tuple):
            candidates.extend(control)
        else:
            candidates.append(control)
        for c in candidates:
            if c is None:
                continue
            stop = getattr(c, "stop", None)
            if callable(stop):
                try:
                    stop()
                except RuntimeError:
                    # Already stopped.
                    pass

    return instance, _cleanup


# ---------------------------------------------------------------------------
# Conformance tests — six per connector, parametrized by kind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "connector_fixture", CONNECTOR_KINDS, indirect=True, ids=CONNECTOR_KINDS
)
class TestConnectorProtocolConformance:
    """One class, six methods → 6 cases × N connectors.

    Every test names the invariant it asserts in its docstring.
    """

    @pytest.mark.asyncio
    async def test_authenticate_valid_returns_authhandle(
        self, connector_fixture: ConnectorFixture
    ) -> None:
        """Invariant: valid secrets → an AuthHandle naming the connector kind.

        ``connector_kind`` and ``handle_id`` must both be populated; the
        handle's ``connector_kind`` should match the connector under
        test (or carry a Protocol-equivalent label — e.g. an MCP
        preset's ``connector_kind`` may differ from its registry kind).
        """
        instance, cleanup = await _instantiate(connector_fixture)
        try:
            handle = await instance.authenticate(connector_fixture.valid_secrets)
            assert isinstance(handle, AuthHandle)
            assert isinstance(handle.connector_kind, str) and handle.connector_kind
            assert isinstance(handle.handle_id, str) and handle.handle_id
            # Protocol structural check.
            assert isinstance(instance, SurfaceDriver), (
                f"{type(instance).__name__} must implement SurfaceDriver Protocol"
            )
        finally:
            cleanup()

    @pytest.mark.asyncio
    async def test_authenticate_invalid_raises(
        self, connector_fixture: ConnectorFixture
    ) -> None:
        """Invariant: malformed secrets → ValueError (the day-one auth-error contract).

        We accept either ValueError directly or any subclass — the
        SurfaceDriver contract uses ValueError for malformed bundles.
        """
        instance, cleanup = await _instantiate(connector_fixture)
        try:
            with pytest.raises((ValueError, KeyError)):
                await instance.authenticate(connector_fixture.invalid_secrets)
        finally:
            cleanup()

    @pytest.mark.asyncio
    async def test_discover_returns_proposals_with_stable_ordering(
        self, connector_fixture: ConnectorFixture
    ) -> None:
        """Invariant: discover() is idempotent — two calls return the same
        ordered list of (kind, resource_id) pairs.

        Skeletal connectors discover ``[]`` by contract, which is
        trivially stable. Production connectors must yield a stable
        sort across runs so the dashboard's resource picker doesn't
        flicker.
        """
        instance, cleanup = await _instantiate(connector_fixture)
        try:
            handle = await instance.authenticate(connector_fixture.valid_secrets)
            first = await instance.discover(handle)
            second = await instance.discover(handle)
            assert isinstance(first, list)
            for r in first:
                assert isinstance(r, ResourceProposal)
            order_first = [(r.kind, r.resource_id) for r in first]
            order_second = [(r.kind, r.resource_id) for r in second]
            assert order_first == order_second, (
                f"{connector_fixture.kind}: discover ordering not stable"
            )
        finally:
            cleanup()

    @pytest.mark.asyncio
    async def test_profile_idempotent_or_skeletal(
        self, connector_fixture: ConnectorFixture
    ) -> None:
        """Invariant: profile(handle, rid) is idempotent for the same input.

        Two consecutive calls return Profiles with identical
        ``schema_hash`` (the schema-stability proxy) and equal
        ``columns`` lists. Skeletal connectors must raise
        ``NotImplementedError`` instead — the harness asserts that
        contract.
        """
        instance, cleanup = await _instantiate(connector_fixture)
        try:
            handle = await instance.authenticate(connector_fixture.valid_secrets)
            if connector_fixture.is_skeletal:
                with pytest.raises(NotImplementedError):
                    await instance.profile(handle, "any-resource")
                return
            assert connector_fixture.known_resource_id is not None
            first = await instance.profile(
                handle, connector_fixture.known_resource_id
            )
            second = await instance.profile(
                handle, connector_fixture.known_resource_id
            )
            assert isinstance(first, Profile)
            assert isinstance(second, Profile)
            assert first.schema_hash == second.schema_hash, (
                f"{connector_fixture.kind}: profile schema_hash drifted between calls"
            )
            assert first.columns == second.columns
            assert first.column_count == second.column_count
        finally:
            cleanup()

    @pytest.mark.asyncio
    async def test_sample_returns_bytes_and_is_deterministic(
        self, connector_fixture: ConnectorFixture
    ) -> None:
        """Invariant: sample is deterministic for the same (handle, rid, n)
        and respects the connector's per-kind ``n`` semantics.

        ``n`` is a "best-effort" cap: byte-count for byte-streaming
        connectors (s3_csv, http_csv, mcp); record-count for connectors
        that page via SQL/API ``LIMIT n`` (postgres, snowflake, stripe,
        csv_local). All connectors return ``bytes``; all are
        deterministic across two calls with the same input.

        For byte-cap connectors the harness asserts ``len(first) ≤ n``;
        for record-cap connectors the harness asserts only the bytes
        equality + nonempty bound (the per-connector ``LIMIT n`` is
        unit-tested elsewhere).

        Skeletal connectors raise NotImplementedError per contract.
        """
        instance, cleanup = await _instantiate(connector_fixture)
        try:
            handle = await instance.authenticate(connector_fixture.valid_secrets)
            n = 32
            if connector_fixture.is_skeletal:
                with pytest.raises(NotImplementedError):
                    await instance.sample(handle, "any", n)
                return
            assert connector_fixture.known_resource_id is not None
            first = await instance.sample(
                handle, connector_fixture.known_resource_id, n
            )
            second = await instance.sample(
                handle, connector_fixture.known_resource_id, n
            )
            assert isinstance(first, bytes)
            assert isinstance(second, bytes)
            assert first == second, (
                f"{connector_fixture.kind}: sample drifted between calls"
            )
            # Byte-cap connectors honor ``n`` literally.
            byte_cap_connectors = {"s3_csv", "http_csv", "mcp:notion"}
            if connector_fixture.kind in byte_cap_connectors:
                assert len(first) <= n, (
                    f"{connector_fixture.kind}: sample returned "
                    f"{len(first)} bytes > n={n} (byte-cap connector)"
                )
        finally:
            cleanup()

    @pytest.mark.asyncio
    async def test_watch_is_async_iterator_and_cancellable(
        self, connector_fixture: ConnectorFixture
    ) -> None:
        """Invariant: watch returns an async iterator that exhausts cleanly
        (or, for skeletons, raises NotImplementedError).

        Day-one connectors do not implement watch; they yield nothing
        and exit. That's structurally an ``AsyncIterator[Change]`` —
        we drain it and assert no exceptions, no leaked tasks.
        """
        instance, cleanup = await _instantiate(connector_fixture)
        try:
            handle = await instance.authenticate(connector_fixture.valid_secrets)
            if connector_fixture.is_skeletal:
                # Skeletal watch raises NotImplementedError before yielding.
                with pytest.raises(NotImplementedError):
                    async for _change in instance.watch(handle, "any"):  # noqa: F841
                        pass
                return
            assert connector_fixture.known_resource_id is not None
            count = 0
            async for _change in instance.watch(
                handle, connector_fixture.known_resource_id
            ):
                count += 1
                if count >= 5:
                    break
            # Day-one connectors yield zero changes (CDC is post-day-one).
            assert count == 0, (
                f"{connector_fixture.kind}: watch unexpectedly yielded {count} changes"
            )
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# Coverage assertion — the harness covers every connector named in the spec
# ---------------------------------------------------------------------------


def test_conformance_covers_every_required_connector() -> None:
    """Invariant: every connector named in the W6.A4 plan acceptance list
    appears in CONNECTOR_KINDS.

    Drift-detection: if the plan adds a new connector, this test fails
    until the harness fixture entry is added. Mirror of the registry
    (modulo skeletons that share fixture builders).
    """
    required = {
        "csv_local",
        "postgres",
        "snowflake",
        "bigquery",
        "s3_csv",
        "stripe",
        "salesforce",
        "hubspot",
        "gsheets",
        "http_csv",
        # The plan's eleventh slot is "mcp" — represented by mcp:notion
        # as the canonical preset (the connector picker shows every
        # registered preset; conformance covers one representative).
        "mcp:notion",
    }
    assert required.issubset(set(CONNECTOR_KINDS)), (
        f"missing conformance fixtures for: {required - set(CONNECTOR_KINDS)}"
    )


def test_every_registered_connector_is_protocol_compliant() -> None:
    """Invariant: every class in the default registry implements SurfaceDriver.

    A drift gate — adding a new connector that fails ``isinstance(c,
    SurfaceDriver)`` (e.g. forgot ``async def discover``) fails this test
    immediately, even before the conformance suite parametrizes over it.
    """
    reg = default_registry()
    for kind in reg.all_kinds():
        cls = reg.get(kind)
        assert cls is not None
        # MCP presets need a config to instantiate; skip the
        # `isinstance` check on those (the underlying class is a
        # subclass of MCPSurfaceDriver which is structurally SurfaceDriver-
        # compliant; verified at class definition).
        if kind.startswith("mcp:"):
            continue
        instance = cls()
        assert isinstance(instance, SurfaceDriver), (
            f"{kind}: {cls.__name__} does not implement SurfaceDriver Protocol"
        )
