"""Tests for the LocalLakeConnector — the default lake every tenant gets.

The lake is unique among connectors: it is auto-provisioned on install
(no user input), it advertises a fixed canonical resource catalog
(seven medallion tables), and it sources rows from the tenant's ledger
projections rather than an external system. These tests cover all
three method surfaces (discover / profile / sample) and the auth
handle creation, including the optional row-count and sample query
injection points used by production.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from wormbase_lake_surfaces.base import Connector
from wormbase_lake_surfaces.local_lake import (
    LOCAL_LAKE_RESOURCE_IDS,
    LocalLakeConnector,
)
from wormbase_lake_surfaces.types import SecretBundle


# ---------------------------------------------------------------------------
# Protocol compliance + capability honesty
# ---------------------------------------------------------------------------


def test_local_lake_implements_connector_protocol() -> None:
    c = LocalLakeConnector()
    assert isinstance(c, Connector)
    assert c.kind == "local_lake"
    assert "discover" in c.capability
    assert "profile" in c.capability
    assert "sample" in c.capability
    # No watch — the lake updates via worm activity, not external polling.
    assert "watch" not in c.capability


def test_local_lake_advertises_production_status() -> None:
    """The lake is the default; it ships at production fidelity from
    minute zero, not as a preview or skeletal connector."""
    assert LocalLakeConnector.status == "production"
    assert "default" in LocalLakeConnector.status_note.lower()
    assert "minute zero" in LocalLakeConnector.status_note.lower()


def test_local_lake_self_registers() -> None:
    """The connector must appear in the default registry under its kind
    so the dashboard's connector picker (D4) can list it."""
    from wormbase_lake_surfaces.registry import default_registry

    reg = default_registry()
    assert reg.get("local_lake") is LocalLakeConnector


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_creates_store_root(tmp_path: Path) -> None:
    tenant_id = str(uuid4())
    store_root = tmp_path / "lake-root"
    c = LocalLakeConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": tenant_id, "store_root": str(store_root)}),
    )
    assert handle.connector_kind == "local_lake"
    assert handle.handle_id == tenant_id
    assert handle.extra["tenant_id"] == tenant_id
    assert handle.extra["store_root"] == str(store_root)
    assert store_root.is_dir()


@pytest.mark.asyncio
async def test_authenticate_defaults_store_root_to_var_lib() -> None:
    """When ``store_root`` is omitted the connector falls back to the
    canonical ``/var/lib/wormbase/{tenant_id}/local-lake/`` location."""
    tenant_id = str(uuid4())
    c = LocalLakeConnector()
    handle = await c.authenticate(SecretBundle(payload={"tenant_id": tenant_id}))
    assert (
        handle.extra["store_root"]
        == f"/var/lib/wormbase/{tenant_id}/local-lake"
    )


@pytest.mark.asyncio
async def test_authenticate_rejects_missing_tenant_id() -> None:
    c = LocalLakeConnector()
    with pytest.raises(ValueError, match="tenant_id"):
        await c.authenticate(SecretBundle(payload={}))


@pytest.mark.asyncio
async def test_authenticate_rejects_non_string_tenant_id() -> None:
    c = LocalLakeConnector()
    with pytest.raises(ValueError, match="tenant_id"):
        await c.authenticate(SecretBundle(payload={"tenant_id": 12345}))


@pytest.mark.asyncio
async def test_authenticate_tolerates_uncreatable_store_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read-only mounts are common in test/CI environments; authenticate
    must not raise when the directory cannot be created."""

    def _fail_mkdir(self, *a, **k):  # type: ignore[no-untyped-def]
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "mkdir", _fail_mkdir)
    c = LocalLakeConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "t", "store_root": str(tmp_path / "x")}),
    )
    assert handle.handle_id == "t"


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_returns_seven_canonical_resources(
    tmp_path: Path,
) -> None:
    """The catalog is fixed: every tenant's lake exposes the same seven
    medallion tables in the same bronze → silver → gold order."""
    c = LocalLakeConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "t", "store_root": str(tmp_path)}),
    )
    proposals = await c.discover(handle)
    assert [p.resource_id for p in proposals] == list(LOCAL_LAKE_RESOURCE_IDS)
    assert len(proposals) == 7
    for p in proposals:
        assert p.kind == "table"
        assert p.classification_hint == "internal"
        assert p.metadata["description"]
        assert p.metadata["tier"] in {"bronze", "silver", "gold"}


@pytest.mark.asyncio
async def test_discover_orders_layers_bronze_silver_gold(
    tmp_path: Path,
) -> None:
    c = LocalLakeConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "t", "store_root": str(tmp_path)}),
    )
    proposals = await c.discover(handle)
    tiers = [p.metadata["tier"] for p in proposals]
    # Bronze rows first, then silver, then gold.
    assert tiers == ["bronze", "bronze", "silver", "silver", "silver", "gold", "gold"]


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_returns_canonical_schema_for_each_resource(
    tmp_path: Path,
) -> None:
    c = LocalLakeConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "t", "store_root": str(tmp_path)}),
    )
    for rid in LOCAL_LAKE_RESOURCE_IDS:
        prof = await c.profile(handle, rid)
        assert prof.column_count >= 4
        assert prof.row_count == 0  # no row_count_query injected
        assert prof.schema_hash
        assert prof.extra["tenant_id"] == "t"
        assert prof.extra["resource_id"] == rid


@pytest.mark.asyncio
async def test_profile_bronze_conversations_canonical_columns(
    tmp_path: Path,
) -> None:
    """Bronze.conversations carries the chat_received column shape so the
    dashboard's resource browser can render the same column list the
    ledger projection exposes."""
    c = LocalLakeConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "t", "store_root": str(tmp_path)}),
    )
    prof = await c.profile(handle, "bronze.conversations")
    names = [col["name"] for col in prof.columns]
    assert {"channel_id", "message_id", "sender_person", "ts", "text", "classification"} <= set(names)


@pytest.mark.asyncio
async def test_profile_silver_persons_canonical_columns(
    tmp_path: Path,
) -> None:
    c = LocalLakeConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "t", "store_root": str(tmp_path)}),
    )
    prof = await c.profile(handle, "silver.persons")
    names = [col["name"] for col in prof.columns]
    assert {"person_id", "tenant_id", "name", "email", "position", "status"} <= set(names)


@pytest.mark.asyncio
async def test_profile_uses_row_count_query_when_provided(
    tmp_path: Path,
) -> None:
    """Production wires a row_count_query that hits the ledger; we
    verify the connector forwards through with the right arguments."""
    seen: list[tuple[str, str]] = []

    async def _row_count(tenant_id: str, resource_id: str) -> int:
        seen.append((tenant_id, resource_id))
        return 42

    c = LocalLakeConnector(row_count_query=_row_count)
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "abc", "store_root": str(tmp_path)}),
    )
    prof = await c.profile(handle, "silver.persons")
    assert prof.row_count == 42
    assert seen == [("abc", "silver.persons")]


@pytest.mark.asyncio
async def test_profile_rejects_unknown_resource(tmp_path: Path) -> None:
    c = LocalLakeConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "t", "store_root": str(tmp_path)}),
    )
    with pytest.raises(ValueError, match="unknown resource_id"):
        await c.profile(handle, "bronze.does_not_exist")


# ---------------------------------------------------------------------------
# sample
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sample_returns_empty_when_no_query_injected(
    tmp_path: Path,
) -> None:
    """A fresh-tenant lake has nothing to sample; sample returns b""."""
    c = LocalLakeConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "t", "store_root": str(tmp_path)}),
    )
    assert await c.sample(handle, "silver.persons", 5) == b""


@pytest.mark.asyncio
async def test_sample_serializes_rows_as_jsonl(tmp_path: Path) -> None:
    rows = [
        {"person_id": "p1", "name": "Alice", "status": "active"},
        {"person_id": "p2", "name": "Bob", "status": "active"},
    ]

    async def _sample(tenant_id: str, resource_id: str, n: int) -> list[dict]:
        return rows[:n]

    c = LocalLakeConnector(sample_query=_sample)
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "t", "store_root": str(tmp_path)}),
    )
    out = await c.sample(handle, "silver.persons", 5)
    lines = out.decode().rstrip("\n").split("\n")
    assert [json.loads(line) for line in lines] == rows


@pytest.mark.asyncio
async def test_sample_rejects_unknown_resource(tmp_path: Path) -> None:
    c = LocalLakeConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "t", "store_root": str(tmp_path)}),
    )
    with pytest.raises(ValueError, match="unknown resource_id"):
        await c.sample(handle, "gold.does_not_exist", 5)


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watch_yields_nothing(tmp_path: Path) -> None:
    """The lake doesn't poll externally; watch is a degenerate empty
    iterator."""
    c = LocalLakeConnector()
    handle = await c.authenticate(
        SecretBundle(payload={"tenant_id": "t", "store_root": str(tmp_path)}),
    )
    items = []
    async for change in c.watch(handle, "silver.persons"):
        items.append(change)
    assert items == []
