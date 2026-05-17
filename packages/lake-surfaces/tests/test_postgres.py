"""Tests for PostgresSurfaceDriver — uses an asyncpg mock so CI doesn't need pg."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wormbase_lake_surfaces.base import SurfaceDriver
from wormbase_lake_surfaces.postgres import (
    PostgresSurfaceDriver,
    _dsn_from_secrets,
    _normalize_dsn,
)
from wormbase_lake_surfaces.types import AuthHandle, SecretBundle


def test_postgres_implements_protocol() -> None:
    c = PostgresSurfaceDriver()
    assert isinstance(c, SurfaceDriver)
    assert c.kind == "postgres"


def test_dsn_normalize_strips_sqlalchemy_driver() -> None:
    assert (
        _normalize_dsn("postgresql+asyncpg://u:p@h/db")
        == "postgresql://u:p@h/db"
    )
    assert _normalize_dsn("postgresql://u:p@h/db") == "postgresql://u:p@h/db"


def test_dsn_from_secrets_with_dsn() -> None:
    assert (
        _dsn_from_secrets({"dsn": "postgresql://u@h/db"})
        == "postgresql://u@h/db"
    )


def test_dsn_from_secrets_with_components() -> None:
    dsn = _dsn_from_secrets(
        {
            "host": "db",
            "port": 5432,
            "user": "wormbase",
            "password": "secret",
            "database": "wb",
        }
    )
    assert dsn == "postgresql://wormbase:secret@db:5432/wb"


def test_dsn_from_secrets_missing_required() -> None:
    with pytest.raises(ValueError, match="dsn"):
        _dsn_from_secrets({})


@pytest.fixture
def mock_asyncpg() -> Any:
    """Patch asyncpg.connect to return a mock connection."""
    fake_conn = MagicMock()
    fake_conn.close = AsyncMock()
    fake_conn.fetchval = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=[])
    with patch("asyncpg.connect", new=AsyncMock(return_value=fake_conn)):
        yield fake_conn


@pytest.mark.asyncio
async def test_postgres_authenticate_returns_handle(mock_asyncpg: Any) -> None:
    mock_asyncpg.fetchval.return_value = "PostgreSQL 16.0"
    c = PostgresSurfaceDriver()
    handle = await c.authenticate(
        SecretBundle(payload={"dsn": "postgresql://wb:wb@db/wb"}),
    )
    assert handle.connector_kind == "postgres"
    assert handle.extra["dsn"] == "postgresql://wb:wb@db/wb"
    assert handle.extra["version"] == "PostgreSQL 16.0"
    mock_asyncpg.close.assert_awaited()


@pytest.mark.asyncio
async def test_postgres_authenticate_normalizes_sa_dsn(mock_asyncpg: Any) -> None:
    mock_asyncpg.fetchval.return_value = "PG"
    c = PostgresSurfaceDriver()
    handle = await c.authenticate(
        SecretBundle(payload={"dsn": "postgresql+asyncpg://wb:wb@db/wb"}),
    )
    assert handle.extra["dsn"] == "postgresql://wb:wb@db/wb"


@pytest.mark.asyncio
async def test_postgres_discover_lists_user_tables(mock_asyncpg: Any) -> None:
    mock_asyncpg.fetch.return_value = [
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
    c = PostgresSurfaceDriver()
    handle = AuthHandle(
        connector_kind="postgres",
        handle_id="x",
        extra={"dsn": "postgresql://wb@db/wb"},
    )
    resources = await c.discover(handle)
    assert len(resources) == 2
    names = {r.name for r in resources}
    assert "public.ledger" in names
    assert "public.people" in names
    for r in resources:
        assert r.kind == "table"
        assert r.metadata["schema"] == "public"


@pytest.mark.asyncio
async def test_postgres_profile_returns_columns(mock_asyncpg: Any) -> None:
    mock_asyncpg.fetch.return_value = [
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
    mock_asyncpg.fetchval.return_value = 1234
    c = PostgresSurfaceDriver()
    handle = AuthHandle(
        connector_kind="postgres",
        handle_id="x",
        extra={"dsn": "postgresql://wb@db/wb"},
    )
    profile = await c.profile(handle, "public.ledger")
    assert profile.row_count == 1234
    assert profile.column_count == 2
    assert profile.columns[0]["name"] == "id"
    assert profile.columns[0]["dtype"] == "uuid"
    assert profile.columns[0]["nullable"] is False
    assert profile.schema_hash != ""


@pytest.mark.asyncio
async def test_postgres_profile_rejects_unqualified_id(mock_asyncpg: Any) -> None:
    c = PostgresSurfaceDriver()
    handle = AuthHandle(
        connector_kind="postgres",
        handle_id="x",
        extra={"dsn": "postgresql://wb@db/wb"},
    )
    with pytest.raises(ValueError, match="schema.table"):
        await c.profile(handle, "ledger")


@pytest.mark.asyncio
async def test_postgres_sample_returns_tsv_bytes(mock_asyncpg: Any) -> None:
    # asyncpg.Record has .keys() and .values() — fake with a class.
    class _FakeRecord:
        def __init__(self, d: dict[str, Any]) -> None:
            self._d = d

        def keys(self) -> list[str]:
            return list(self._d.keys())

        def values(self) -> list[Any]:
            return list(self._d.values())

    mock_asyncpg.fetch.return_value = [
        _FakeRecord({"id": 1, "name": "Alice"}),
        _FakeRecord({"id": 2, "name": None}),
    ]
    c = PostgresSurfaceDriver()
    handle = AuthHandle(
        connector_kind="postgres",
        handle_id="x",
        extra={"dsn": "postgresql://wb@db/wb"},
    )
    out = await c.sample(handle, "public.users", 2)
    text = out.decode()
    assert text.startswith("id\tname\n")
    assert "1\tAlice" in text
    assert "2\t\n" in text  # NULL rendered as empty


@pytest.mark.asyncio
async def test_postgres_sample_empty_returns_empty_bytes(
    mock_asyncpg: Any,
) -> None:
    mock_asyncpg.fetch.return_value = []
    c = PostgresSurfaceDriver()
    handle = AuthHandle(
        connector_kind="postgres",
        handle_id="x",
        extra={"dsn": "postgresql://wb@db/wb"},
    )
    assert await c.sample(handle, "public.users", 5) == b""


@pytest.mark.asyncio
async def test_postgres_watch_yields_nothing() -> None:
    c = PostgresSurfaceDriver()
    handle = AuthHandle(
        connector_kind="postgres",
        handle_id="x",
        extra={"dsn": "postgresql://wb@db/wb"},
    )
    items = [item async for item in c.watch(handle, "public.users")]
    assert items == []
