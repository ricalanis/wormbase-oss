"""Tests for S3CsvConnector — uses an aioboto3 client mock.

Why not moto: moto's `mock_aws` patches the synchronous `botocore`
endpoint, but aioboto3 routes through `aiobotocore` whose response
loop awaits a streaming body. The two layers don't compose cleanly,
so we mock the aioboto3 session directly and assert on the call
arguments + handle the returned shapes manually.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wormbase_connectors.base import Connector
from wormbase_connectors.s3_csv import S3CsvConnector
from wormbase_connectors.types import SecretBundle

_BUCKET = "wb-test-bucket"
_REGION = "us-east-1"


def test_s3_csv_implements_protocol() -> None:
    c = S3CsvConnector()
    assert isinstance(c, Connector)
    assert c.kind == "s3_csv"


@pytest.mark.asyncio
async def test_s3_authenticate_requires_bucket() -> None:
    c = S3CsvConnector()
    with pytest.raises(ValueError, match="bucket"):
        await c.authenticate(SecretBundle(payload={}))


@pytest.mark.asyncio
async def test_s3_authenticate_returns_handle() -> None:
    c = S3CsvConnector()
    handle = await c.authenticate(
        SecretBundle(
            payload={
                "bucket": _BUCKET,
                "prefix": "data/",
                "aws_access_key_id": "test",
                "aws_secret_access_key": "test",
                "region_name": _REGION,
            }
        )
    )
    assert handle.connector_kind == "s3_csv"
    assert handle.extra["bucket"] == _BUCKET
    assert handle.extra["prefix"] == "data/"
    assert handle.extra["client_kwargs"]["region_name"] == _REGION


def _make_mock_s3_client(responses: dict[str, Any]) -> Any:
    """Build a MagicMock that imitates an aioboto3 client context manager."""
    inner = MagicMock()
    if "list_objects_v2" in responses:
        inner.list_objects_v2 = AsyncMock(
            return_value=responses["list_objects_v2"],
        )
    if "get_object" in responses:
        # get_object response has a Body with .read() coroutine.
        body_bytes = responses["get_object"]
        body = MagicMock()
        body.read = AsyncMock(return_value=body_bytes)
        inner.get_object = AsyncMock(
            return_value={"Body": body, "ContentLength": len(body_bytes)},
        )

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=inner)
    cm.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.client = MagicMock(return_value=cm)
    return session


@pytest.mark.asyncio
async def test_s3_discover_lists_csv_keys() -> None:
    fake_session = _make_mock_s3_client(
        {
            "list_objects_v2": {
                "Contents": [
                    {
                        "Key": "data/sales.csv",
                        "Size": 100,
                        "LastModified": datetime.now(timezone.utc),
                        "ETag": '"abc"',
                    },
                    {
                        "Key": "data/notes.txt",
                        "Size": 2,
                        "LastModified": datetime.now(timezone.utc),
                        "ETag": '"def"',
                    },
                    {
                        "Key": "data/payouts.csv.gz",
                        "Size": 50,
                        "LastModified": datetime.now(timezone.utc),
                        "ETag": '"ghi"',
                    },
                ]
            }
        }
    )

    c = S3CsvConnector()
    handle = await c.authenticate(
        SecretBundle(
            payload={
                "bucket": _BUCKET,
                "prefix": "data/",
                "aws_access_key_id": "test",
                "aws_secret_access_key": "test",
                "region_name": _REGION,
            }
        )
    )
    with patch.object(c, "_session", AsyncMock(return_value=fake_session)):
        resources = await c.discover(handle)

    keys = sorted(r.resource_id for r in resources)
    assert keys == ["data/payouts.csv.gz", "data/sales.csv"]
    by_key = {r.resource_id: r for r in resources}
    assert by_key["data/sales.csv"].kind == "file"
    assert by_key["data/sales.csv"].metadata["bucket"] == _BUCKET
    assert by_key["data/sales.csv"].metadata["size_bytes"] == 100


@pytest.mark.asyncio
async def test_s3_profile_infers_columns() -> None:
    body = b"name,age\nAlice,30\nBob,25\nCarol,42\n"
    fake_session = _make_mock_s3_client({"get_object": body})
    c = S3CsvConnector()
    handle = await c.authenticate(
        SecretBundle(
            payload={
                "bucket": _BUCKET,
                "aws_access_key_id": "test",
                "aws_secret_access_key": "test",
                "region_name": _REGION,
            }
        )
    )
    with patch.object(c, "_session", AsyncMock(return_value=fake_session)):
        profile = await c.profile(handle, "people.csv")

    assert profile.column_count == 2
    by_name = {col["name"]: col for col in profile.columns}
    assert by_name["age"]["dtype"] == "int"
    assert by_name["name"]["dtype"] == "str"
    assert profile.row_count is None  # head-bytes profile cannot count
    assert profile.schema_hash != ""


@pytest.mark.asyncio
async def test_s3_sample_returns_n_bytes() -> None:
    body = b"a,b\n1,2\n3,4\n"
    fake_session = _make_mock_s3_client({"get_object": body})
    c = S3CsvConnector()
    handle = await c.authenticate(
        SecretBundle(
            payload={
                "bucket": _BUCKET,
                "aws_access_key_id": "test",
                "aws_secret_access_key": "test",
                "region_name": _REGION,
            }
        )
    )
    with patch.object(c, "_session", AsyncMock(return_value=fake_session)):
        sample = await c.sample(handle, "x.csv", 100)
    assert sample == body


@pytest.mark.asyncio
async def test_s3_watch_yields_nothing() -> None:
    c = S3CsvConnector()
    handle = await c.authenticate(
        SecretBundle(
            payload={
                "bucket": _BUCKET,
                "aws_access_key_id": "test",
                "aws_secret_access_key": "test",
                "region_name": _REGION,
            }
        )
    )
    items = [item async for item in c.watch(handle, "x.csv")]
    assert items == []
