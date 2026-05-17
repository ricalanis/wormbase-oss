"""Tests for StripeConnector — uses pytest-httpx for the Stripe REST API."""

from __future__ import annotations

import base64
import json

import pytest
from pytest_httpx import HTTPXMock

from wormbase_lake_surfaces.base import Connector
from wormbase_lake_surfaces.stripe import (
    STRIPE_OBJECTS,
    StripeConnector,
    _basic_auth_header,
)
from wormbase_lake_surfaces.types import SecretBundle

_API_KEY = "sk_test_abc123"


def test_stripe_implements_protocol() -> None:
    c = StripeConnector()
    assert isinstance(c, Connector)
    assert c.kind == "stripe"
    assert "discover" in c.capability


def test_stripe_basic_auth_header() -> None:
    h = _basic_auth_header("sk_test_abc")
    expected = "Basic " + base64.b64encode(b"sk_test_abc:").decode()
    assert h == expected


@pytest.mark.asyncio
async def test_stripe_authenticate_requires_api_key() -> None:
    c = StripeConnector()
    with pytest.raises(ValueError, match="api_key"):
        await c.authenticate(SecretBundle(payload={}))


@pytest.mark.asyncio
async def test_stripe_authenticate_returns_handle() -> None:
    c = StripeConnector()
    handle = await c.authenticate(SecretBundle(payload={"api_key": _API_KEY}))
    assert handle.connector_kind == "stripe"
    assert handle.extra["api_key"] == _API_KEY
    assert handle.extra["auth_header"].startswith("Basic ")


@pytest.mark.asyncio
async def test_stripe_discover_returns_canonical_objects() -> None:
    c = StripeConnector()
    handle = await c.authenticate(SecretBundle(payload={"api_key": _API_KEY}))
    resources = await c.discover(handle)
    names = {r.name for r in resources}
    assert "charges" in names
    assert "customers" in names
    assert "payouts" in names
    assert "subscriptions" in names
    assert "invoices" in names
    assert "balance_transactions" in names
    by_name = {r.name: r for r in resources}
    assert by_name["customers"].classification_hint == "pii"
    assert by_name["payouts"].classification_hint is None


@pytest.mark.asyncio
async def test_stripe_profile_introspects_first_record(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.stripe.com/v1/charges?limit=1",
        json={
            "data": [
                {
                    "id": "ch_1",
                    "amount": 1000,
                    "currency": "usd",
                    "captured": True,
                    "metadata": {"order_id": "o-1"},
                }
            ],
            "has_more": True,
        },
    )
    c = StripeConnector()
    handle = await c.authenticate(SecretBundle(payload={"api_key": _API_KEY}))
    profile = await c.profile(handle, "charges")
    assert profile.column_count == 5
    by_name = {col["name"]: col for col in profile.columns}
    assert by_name["id"]["dtype"] == "str"
    assert by_name["amount"]["dtype"] == "int"
    assert by_name["captured"]["dtype"] == "bool"
    assert by_name["metadata"]["dtype"] == "object"
    assert profile.extra["has_more"] is True


@pytest.mark.asyncio
async def test_stripe_profile_sends_basic_auth(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.stripe.com/v1/customers?limit=1",
        json={"data": []},
    )
    c = StripeConnector()
    handle = await c.authenticate(SecretBundle(payload={"api_key": _API_KEY}))
    await c.profile(handle, "customers")
    request = httpx_mock.get_request()
    assert request is not None
    auth = request.headers["Authorization"]
    assert auth.startswith("Basic ")
    decoded = base64.b64decode(auth[6:]).decode()
    assert decoded == f"{_API_KEY}:"


@pytest.mark.asyncio
async def test_stripe_profile_rejects_unknown_object() -> None:
    c = StripeConnector()
    handle = await c.authenticate(SecretBundle(payload={"api_key": _API_KEY}))
    with pytest.raises(ValueError, match="unknown stripe object"):
        await c.profile(handle, "not_a_thing")


@pytest.mark.asyncio
async def test_stripe_sample_returns_jsonl_bytes(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.stripe.com/v1/payouts?limit=2",
        json={
            "data": [
                {"id": "po_1", "amount": 1000},
                {"id": "po_2", "amount": 2500},
            ],
        },
    )
    c = StripeConnector()
    handle = await c.authenticate(SecretBundle(payload={"api_key": _API_KEY}))
    sample = await c.sample(handle, "payouts", 2)
    lines = sample.decode().rstrip("\n").split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "po_1"
    assert json.loads(lines[1])["id"] == "po_2"


@pytest.mark.asyncio
async def test_stripe_sample_caps_limit_at_100(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.stripe.com/v1/charges?limit=100",
        json={"data": []},
    )
    c = StripeConnector()
    handle = await c.authenticate(SecretBundle(payload={"api_key": _API_KEY}))
    await c.sample(handle, "charges", 5000)


@pytest.mark.asyncio
async def test_stripe_watch_yields_nothing() -> None:
    c = StripeConnector()
    handle = await c.authenticate(SecretBundle(payload={"api_key": _API_KEY}))
    items = [item async for item in c.watch(handle, "charges")]
    assert items == []


@pytest.mark.asyncio
async def test_stripe_authenticate_propagates_api_version(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.stripe.com/v1/charges?limit=1",
        json={"data": []},
    )
    c = StripeConnector()
    handle = await c.authenticate(
        SecretBundle(
            payload={"api_key": _API_KEY, "api_version": "2024-04-10"},
        ),
    )
    assert handle.extra["api_version"] == "2024-04-10"
    await c.profile(handle, "charges")
    request = httpx_mock.get_request()
    assert request is not None
    assert request.headers["Stripe-Version"] == "2024-04-10"


def test_stripe_objects_constant_unchanged() -> None:
    """Guard against accidental reordering — the dashboard connector
    picker depends on this stable order."""
    assert STRIPE_OBJECTS == (
        "charges",
        "customers",
        "payouts",
        "subscriptions",
        "invoices",
        "balance_transactions",
    )
