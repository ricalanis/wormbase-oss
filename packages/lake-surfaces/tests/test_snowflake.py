"""Tests for SnowflakeSurfaceDriver — uses an in-process mock cursor.

snowflake-connector-python is sync-only. The connector bridges to
async via asyncio.to_thread, so these tests patch the underlying
connect() / cursor() pair and assert on the executed SQL + the
async wrapper behavior.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from wormbase_lake_surfaces.base import SurfaceDriver
from wormbase_lake_surfaces.snowflake import SnowflakeSurfaceDriver, _connect_kwargs
from wormbase_lake_surfaces.types import AuthHandle, SecretBundle

_KWARGS = {
    "account": "abc.us-east-1",
    "user": "wb",
    "password": "secret",
    "warehouse": "WB_WH",
    "database": "WB_DB",
}


def test_snowflake_implements_protocol() -> None:
    c = SnowflakeSurfaceDriver()
    assert isinstance(c, SurfaceDriver)
    assert c.kind == "snowflake"


def test_connect_kwargs_requires_password_or_key() -> None:
    payload = {
        "account": "x",
        "user": "y",
        "warehouse": "w",
        "database": "d",
    }
    with pytest.raises(ValueError, match="password.*private_key"):
        _connect_kwargs(payload)


def test_connect_kwargs_missing_required() -> None:
    with pytest.raises(ValueError, match="missing"):
        _connect_kwargs({"account": "x"})


def test_connect_kwargs_picks_optional_fields() -> None:
    kwargs = _connect_kwargs(
        {
            "account": "x",
            "user": "y",
            "password": "z",
            "warehouse": "w",
            "database": "d",
            "role": "ANALYST",
            "schema": "PUBLIC",
        }
    )
    assert kwargs["role"] == "ANALYST"
    assert kwargs["schema"] == "PUBLIC"
    assert kwargs["password"] == "z"


@pytest.fixture
def fake_connect() -> Any:
    """Stub snowflake.connector.connect with a MagicMock conn/cursor."""
    fake_cur = MagicMock()
    fake_cur.fetchone = MagicMock(return_value=("9.5.1",))
    fake_cur.fetchall = MagicMock(return_value=[])
    fake_cur.description = []

    fake_conn = MagicMock()
    fake_conn.cursor = MagicMock(return_value=fake_cur)
    fake_conn.close = MagicMock()
    fake_cur.close = MagicMock()

    with patch("snowflake.connector.connect", return_value=fake_conn) as m:
        yield m, fake_conn, fake_cur


@pytest.mark.asyncio
async def test_snowflake_authenticate(fake_connect: Any) -> None:
    _, _, cur = fake_connect
    c = SnowflakeSurfaceDriver()
    handle = await c.authenticate(SecretBundle(payload=dict(_KWARGS)))
    assert handle.connector_kind == "snowflake"
    assert handle.extra["connect_kwargs"]["account"] == "abc.us-east-1"
    cur.execute.assert_any_call("SELECT CURRENT_VERSION()")


@pytest.mark.asyncio
async def test_snowflake_authenticate_missing_creds() -> None:
    c = SnowflakeSurfaceDriver()
    bad = dict(_KWARGS)
    bad.pop("password")
    with pytest.raises(ValueError):
        await c.authenticate(SecretBundle(payload=bad))


@pytest.mark.asyncio
async def test_snowflake_discover(fake_connect: Any) -> None:
    _, _, cur = fake_connect
    cur.fetchall.return_value = [
        ("PUBLIC", "USERS", 1234, "BASE TABLE"),
        ("PUBLIC", "ORDERS", 999, "BASE TABLE"),
    ]
    c = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _KWARGS},
    )
    resources = await c.discover(handle)
    assert len(resources) == 2
    names = {r.name for r in resources}
    assert "PUBLIC.USERS" in names
    by_name = {r.name: r for r in resources}
    assert by_name["PUBLIC.USERS"].kind == "table"
    assert by_name["PUBLIC.USERS"].metadata["row_count"] == 1234


@pytest.mark.asyncio
async def test_snowflake_profile(fake_connect: Any) -> None:
    _, _, cur = fake_connect
    # First fetchall: DESCRIBE TABLE rows. Second fetchone: row_count.
    cur.fetchall.return_value = [
        ("ID", "NUMBER", "N", None),
        ("EMAIL", "VARCHAR", "Y", None),
    ]
    cur.fetchone.return_value = (4242,)
    c = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _KWARGS},
    )
    profile = await c.profile(handle, "PUBLIC.USERS")
    assert profile.row_count == 4242
    assert profile.column_count == 2
    by_name = {col["name"]: col for col in profile.columns}
    assert by_name["ID"]["dtype"] == "NUMBER"
    assert by_name["ID"]["nullable"] is False
    assert by_name["EMAIL"]["nullable"] is True
    assert profile.schema_hash != ""


@pytest.mark.asyncio
async def test_snowflake_profile_rejects_unqualified_id(
    fake_connect: Any,
) -> None:
    c = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _KWARGS},
    )
    with pytest.raises(ValueError, match="schema.table"):
        await c.profile(handle, "USERS")


@pytest.mark.asyncio
async def test_snowflake_sample(fake_connect: Any) -> None:
    _, _, cur = fake_connect
    cur.description = [("ID",), ("EMAIL",)]
    cur.fetchall.return_value = [
        (1, "alice@example.com"),
        (2, None),
    ]
    c = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _KWARGS},
    )
    out = await c.sample(handle, "PUBLIC.USERS", 5)
    text = out.decode()
    assert text.startswith("ID\tEMAIL\n")
    assert "1\talice@example.com" in text
    assert "2\t\n" in text


@pytest.mark.asyncio
async def test_snowflake_sample_empty_returns_empty(fake_connect: Any) -> None:
    _, _, cur = fake_connect
    cur.description = []
    cur.fetchall.return_value = []
    c = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _KWARGS},
    )
    assert await c.sample(handle, "PUBLIC.USERS", 5) == b""


@pytest.mark.asyncio
async def test_snowflake_watch_yields_nothing() -> None:
    c = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _KWARGS},
    )
    items = [item async for item in c.watch(handle, "PUBLIC.USERS")]
    assert items == []
