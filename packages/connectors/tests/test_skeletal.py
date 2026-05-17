"""Tests for the skeletal SaaS connectors.

These connectors prove the abstraction without full implementations.
We test that:
- Each one is Protocol-compliant.
- ``authenticate`` validates the secret bundle shape.
- ``discover`` returns ``[]`` (TODO until production impl).
- ``profile`` / ``sample`` / ``watch`` raise NotImplementedError.
- ``config_schema()`` produces a JSON-schema with ``required`` keys
  the dashboard's connector picker (D4) can render.
"""

from __future__ import annotations

import pytest

from wormbase_connectors.base import Connector
from wormbase_connectors.bigquery import BigQueryConnector
from wormbase_connectors.gsheets import GsheetsConnector
from wormbase_connectors.hubspot import HubspotConnector
from wormbase_connectors.linear import LinearConnector
from wormbase_connectors.notion import NotionConnector
from wormbase_connectors.salesforce import SalesforceConnector
from wormbase_connectors.types import SecretBundle

ALL_SKELETAL = [
    BigQueryConnector,
    SalesforceConnector,
    HubspotConnector,
    GsheetsConnector,
    NotionConnector,
    LinearConnector,
]

# Minimum-viable secret bundle per skeleton — must include every
# required key with a non-empty placeholder value.
_MINIMAL_SECRETS: dict[str, dict[str, str]] = {
    "bigquery": {"project": "p", "service_account_json": "{}"},
    "salesforce": {
        "instance_url": "https://test.salesforce.com",
        "access_token": "tok",
    },
    "hubspot": {"access_token": "tok"},
    "gsheets": {"service_account_json": "{}"},
    "notion": {"integration_token": "tok"},
    "linear": {"api_key": "lin_xxx"},
}


@pytest.mark.parametrize("cls", ALL_SKELETAL)
def test_skeletal_implements_protocol(cls: type) -> None:
    c = cls()
    assert isinstance(c, Connector)
    assert isinstance(c.kind, str) and c.kind != ""
    assert "discover" in c.capability


@pytest.mark.parametrize("cls", ALL_SKELETAL)
def test_skeletal_declares_capability_honesty_status(cls: type) -> None:
    """Each skeletal connector advertises ``coming_soon`` status with a note."""
    assert cls.status == "coming_soon", (
        f"{cls.__name__} should declare status='coming_soon'"
    )
    assert isinstance(cls.status_note, str) and cls.status_note, (
        f"{cls.__name__} should declare a non-empty status_note"
    )


@pytest.mark.parametrize("cls", ALL_SKELETAL)
@pytest.mark.asyncio
async def test_skeletal_authenticate_rejects_missing_secrets(
    cls: type,
) -> None:
    c = cls()
    with pytest.raises(ValueError, match="missing"):
        await c.authenticate(SecretBundle(payload={}))


@pytest.mark.parametrize("cls", ALL_SKELETAL)
@pytest.mark.asyncio
async def test_skeletal_authenticate_returns_handle(cls: type) -> None:
    c = cls()
    payload = _MINIMAL_SECRETS[c.kind]
    handle = await c.authenticate(SecretBundle(payload=payload))
    assert handle.connector_kind == c.kind


@pytest.mark.parametrize("cls", ALL_SKELETAL)
@pytest.mark.asyncio
async def test_skeletal_discover_returns_empty(cls: type) -> None:
    c = cls()
    payload = _MINIMAL_SECRETS[c.kind]
    handle = await c.authenticate(SecretBundle(payload=payload))
    assert await c.discover(handle) == []


@pytest.mark.parametrize("cls", ALL_SKELETAL)
@pytest.mark.asyncio
async def test_skeletal_profile_raises(cls: type) -> None:
    c = cls()
    payload = _MINIMAL_SECRETS[c.kind]
    handle = await c.authenticate(SecretBundle(payload=payload))
    with pytest.raises(NotImplementedError):
        await c.profile(handle, "x")


@pytest.mark.parametrize("cls", ALL_SKELETAL)
@pytest.mark.asyncio
async def test_skeletal_sample_raises(cls: type) -> None:
    c = cls()
    payload = _MINIMAL_SECRETS[c.kind]
    handle = await c.authenticate(SecretBundle(payload=payload))
    with pytest.raises(NotImplementedError):
        await c.sample(handle, "x", 5)


@pytest.mark.parametrize("cls", ALL_SKELETAL)
def test_skeletal_config_schema_has_required(cls: type) -> None:
    schema = cls.config_schema()
    assert schema["type"] == "object"
    assert "required" in schema
    assert len(schema["required"]) == len(cls.required_secrets)
    for key in cls.required_secrets:
        assert key in schema["properties"]
        # Required secrets are rendered with format=password so the
        # dashboard masks the input.
        assert schema["properties"][key].get("format") == "password"


def test_all_skeletals_self_register() -> None:
    """Every skeletal is in the default registry under its `kind`."""
    from wormbase_connectors.registry import default_registry

    reg = default_registry()
    for cls in ALL_SKELETAL:
        assert reg.get(cls.kind) is cls


def test_notion_and_linear_are_in_registry() -> None:
    """Day-one promotion: Notion + Linear are part of the picker."""
    from wormbase_connectors.registry import default_registry

    kinds = default_registry().all_kinds()
    assert "notion" in kinds
    assert "linear" in kinds
