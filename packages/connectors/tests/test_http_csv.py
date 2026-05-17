"""Tests for HttpCsvConnector — uses pytest-httpx for HTTP-level fakes."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from wormbase_connectors.base import Connector
from wormbase_connectors.http_csv import HttpCsvConnector
from wormbase_connectors.types import SecretBundle

_URL = "https://data.example.com/sales.csv"


def test_http_csv_implements_protocol() -> None:
    c = HttpCsvConnector()
    assert isinstance(c, Connector)
    assert c.kind == "http_csv"


@pytest.mark.asyncio
async def test_http_authenticate_requires_url() -> None:
    c = HttpCsvConnector()
    with pytest.raises(ValueError, match="url"):
        await c.authenticate(SecretBundle(payload={}))


@pytest.mark.asyncio
async def test_http_authenticate_returns_handle() -> None:
    c = HttpCsvConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"url": _URL, "auth_header": "Bearer XYZ"}),
    )
    assert handle.connector_kind == "http_csv"
    assert handle.extra["url"] == _URL
    assert handle.extra["auth_header"] == "Bearer XYZ"


@pytest.mark.asyncio
async def test_http_discover_returns_one_resource(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="HEAD", url=_URL, headers={"content-length": "1234"},
    )
    c = HttpCsvConnector()
    handle = await c.authenticate(SecretBundle(payload={"url": _URL}))
    resources = await c.discover(handle)
    assert len(resources) == 1
    [resource] = resources
    assert resource.kind == "endpoint"
    assert resource.name == "sales.csv"
    assert resource.metadata["url"] == _URL
    assert resource.metadata["size_bytes"] == 1234


@pytest.mark.asyncio
async def test_http_discover_handles_no_head_support(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(method="HEAD", url=_URL, status_code=405)
    c = HttpCsvConnector()
    handle = await c.authenticate(SecretBundle(payload={"url": _URL}))
    [resource] = await c.discover(handle)
    assert resource.metadata["size_bytes"] is None


@pytest.mark.asyncio
async def test_http_profile_infers_columns(httpx_mock: HTTPXMock) -> None:
    body = b"region,amount\nEU,100\nUS,250\nAPAC,80\n"
    httpx_mock.add_response(method="GET", url=_URL, content=body)
    c = HttpCsvConnector()
    handle = await c.authenticate(SecretBundle(payload={"url": _URL}))
    profile = await c.profile(handle, _URL)
    assert profile.column_count == 2
    by_name = {col["name"]: col for col in profile.columns}
    assert by_name["amount"]["dtype"] == "int"
    assert by_name["region"]["dtype"] == "str"
    assert profile.row_count is None


@pytest.mark.asyncio
async def test_http_profile_sends_auth_header(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=_URL, content=b"a,b\n1,2\n")
    c = HttpCsvConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"url": _URL, "auth_header": "Bearer XYZ"}),
    )
    await c.profile(handle, _URL)
    request = httpx_mock.get_request(method="GET", url=_URL)
    assert request is not None
    assert request.headers["Authorization"] == "Bearer XYZ"
    assert request.headers["Range"].startswith("bytes=0-")


@pytest.mark.asyncio
async def test_http_sample_returns_n_bytes(httpx_mock: HTTPXMock) -> None:
    body = b"a,b\n1,2\n3,4\n"
    httpx_mock.add_response(method="GET", url=_URL, content=body)
    c = HttpCsvConnector()
    handle = await c.authenticate(SecretBundle(payload={"url": _URL}))
    sample = await c.sample(handle, _URL, 5)
    assert sample == body
    request = httpx_mock.get_request(method="GET", url=_URL)
    assert request is not None
    assert request.headers["Range"] == "bytes=0-4"


@pytest.mark.asyncio
async def test_http_sample_propagates_http_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=_URL, status_code=500)
    c = HttpCsvConnector()
    handle = await c.authenticate(SecretBundle(payload={"url": _URL}))
    with pytest.raises(Exception):
        await c.sample(handle, _URL, 100)


@pytest.mark.asyncio
async def test_http_watch_yields_nothing() -> None:
    c = HttpCsvConnector()
    handle = await c.authenticate(SecretBundle(payload={"url": _URL}))
    items = [item async for item in c.watch(handle, _URL)]
    assert items == []
