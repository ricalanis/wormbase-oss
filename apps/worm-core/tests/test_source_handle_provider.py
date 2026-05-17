"""Sampler activation Wave — ``LedgerSourceHandleProvider`` tests.

Pins the ledger-fold contract for the
:class:`wormbase_core.source_handle_provider.SourceHandleProvider`
Protocol:

  * Empty ledger / no entries for tenant → None.
  * ``source_proposed`` only (not yet connected) → None.
  * ``source_connected`` for a different source_id → None (tenant
    isolation via ``company_id`` argument).
  * Full ``proposed → connected`` cycle for a known connector kind →
    :class:`SourceHandleRecord` with reconstructed AuthHandle.
  * SurfaceDriver kind unknown to the reconstructor (opaque secret) →
    None (honest stub).
  * Multi-source isolation in same tenant.
  * Multi-tenant isolation: source_id collision across tenants does
    not leak handles.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import (
    SourceConfirmedPayload,
    SourceConnectedPayload,
    SourceProposedPayload,
)

from wormbase_core.source_handle_provider import (
    LedgerSourceHandleProvider,
    SourceHandleProvider,
    SourceHandleRecord,
)


_TENANT_A = UUID("00000000-0000-0000-0000-000000000aaa")
_TENANT_B = UUID("00000000-0000-0000-0000-000000000bbb")


# ---------------------------------------------------------------------------
# Test helpers — write source-pipeline entries through the ledger PEVR
# primitive so the entries look exactly like production
# (`source_builder.SourceBuilder` writes the same shape).
# ---------------------------------------------------------------------------


async def _emit_source_proposed(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: UUID,
    source_kind: str,
    uri: str,
) -> None:
    payload = SourceProposedPayload(
        source_id=source_id,
        source_kind=source_kind,
        uri=uri,
        added_via_flow="drop_and_profile",
        suggested_domain="finance",
        suggested_classification="internal",
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "source_proposed",
            "ref_id": str(source_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_proposed",
            "args": payload.model_dump(mode="json"),
            "result_ref": str(source_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
    )


async def _emit_source_confirmed(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: UUID,
) -> None:
    payload = SourceConfirmedPayload(
        source_id=source_id,
        confirmed_by_person=UUID("00000000-0000-0000-0000-0000000000c1"),
        domain_id=UUID("00000000-0000-0000-0000-0000000000d1"),
        classification="internal",
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "source_confirmed",
            "ref_id": str(source_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_confirmed",
            "args": payload.model_dump(mode="json"),
            "result_ref": str(source_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
    )


async def _emit_source_connected(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: UUID,
    connection_ref: str = "test-connection",
) -> None:
    payload = SourceConnectedPayload(
        source_id=source_id,
        connection_ref=connection_ref,
        connected_at=datetime.now(UTC),
    )
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "source_connected",
            "ref_id": str(source_id),
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_connected",
            "args": payload.model_dump(mode="json"),
            "result_ref": str(source_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "ok", "ok": True}], "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "test"},
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_ledger_source_handle_provider_implements_protocol() -> None:
    """LedgerSourceHandleProvider satisfies the SourceHandleProvider Protocol."""
    provider = LedgerSourceHandleProvider(ledger=InMemoryLedger())
    assert isinstance(provider, SourceHandleProvider)


# ---------------------------------------------------------------------------
# Empty-ledger / not-yet-connected paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_ledger_returns_none() -> None:
    provider = LedgerSourceHandleProvider(ledger=InMemoryLedger())
    result = await provider.get_handle(
        company_id=_TENANT_A,
        source_id="00000000-0000-0000-0000-000000000001",
    )
    assert result is None


@pytest.mark.asyncio
async def test_proposed_only_returns_none() -> None:
    """A source in ``proposed`` (not ``connected``) yields no handle."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-000000000001")
    await _emit_source_proposed(
        ledger,
        company_id=_TENANT_A,
        source_id=source_id,
        source_kind="csv_local",
        uri="/tmp/test.csv",
    )
    provider = LedgerSourceHandleProvider(ledger=ledger)
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is None


@pytest.mark.asyncio
async def test_confirmed_but_not_connected_returns_none() -> None:
    """Even after confirm, the source is not yet ``connected``."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-000000000001")
    await _emit_source_proposed(
        ledger,
        company_id=_TENANT_A,
        source_id=source_id,
        source_kind="csv_local",
        uri="/tmp/test.csv",
    )
    await _emit_source_confirmed(
        ledger, company_id=_TENANT_A, source_id=source_id,
    )
    provider = LedgerSourceHandleProvider(ledger=ledger)
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is None


# ---------------------------------------------------------------------------
# Happy paths — per connector kind reconstruction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_local_returns_record() -> None:
    """csv_local: reconstructs AuthHandle with ``extra={'path': uri}``."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-000000000001")
    await _emit_source_proposed(
        ledger,
        company_id=_TENANT_A,
        source_id=source_id,
        source_kind="csv_local",
        uri="/tmp/test.csv",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
    )
    provider = LedgerSourceHandleProvider(ledger=ledger)
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert isinstance(result, SourceHandleRecord)
    assert result.source_id == str(source_id)
    assert result.connector_kind == "csv_local"
    # AuthHandle re-imported here to avoid module-level dep
    from wormbase_lake_surfaces.types import AuthHandle

    assert isinstance(result.auth_handle, AuthHandle)
    assert result.auth_handle.extra.get("path") == "/tmp/test.csv"
    assert result.resource_map.get("/tmp/test.csv") == "/tmp/test.csv"


@pytest.mark.asyncio
async def test_postgres_returns_record_with_dsn() -> None:
    """postgres: reconstructs AuthHandle with ``extra={'dsn': uri}``."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-000000000002")
    await _emit_source_proposed(
        ledger,
        company_id=_TENANT_A,
        source_id=source_id,
        source_kind="postgres",
        uri="postgresql://user:pass@localhost/db",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
    )
    provider = LedgerSourceHandleProvider(ledger=ledger)
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is not None
    assert result.connector_kind == "postgres"
    assert result.auth_handle.extra.get("dsn") == (
        "postgresql://user:pass@localhost/db"
    )


@pytest.mark.asyncio
async def test_http_csv_returns_record_with_url() -> None:
    """http_csv: reconstructs AuthHandle with ``extra={'url': uri}``."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-000000000003")
    await _emit_source_proposed(
        ledger,
        company_id=_TENANT_A,
        source_id=source_id,
        source_kind="http_csv",
        uri="https://example.com/data.csv",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
    )
    provider = LedgerSourceHandleProvider(ledger=ledger)
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is not None
    assert result.connector_kind == "http_csv"
    assert result.auth_handle.extra.get("url") == (
        "https://example.com/data.csv"
    )


# ---------------------------------------------------------------------------
# Opaque-secret connector kinds → None (honest stub)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stripe_returns_none_until_credential_broker_wired() -> None:
    """stripe needs API key; not on ledger → honest None today."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-000000000004")
    await _emit_source_proposed(
        ledger,
        company_id=_TENANT_A,
        source_id=source_id,
        source_kind="stripe",
        uri="stripe://account",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
    )
    provider = LedgerSourceHandleProvider(ledger=ledger)
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is None


@pytest.mark.asyncio
async def test_unknown_connector_kind_returns_none() -> None:
    """An unrecognised connector kind: honest None, no exception."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-000000000005")
    await _emit_source_proposed(
        ledger,
        company_id=_TENANT_A,
        source_id=source_id,
        source_kind="nonexistent_kind",
        uri="ignored",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
    )
    provider = LedgerSourceHandleProvider(ledger=ledger)
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is None


# ---------------------------------------------------------------------------
# Multi-source + multi-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_source_isolation_same_tenant() -> None:
    """Two sources in one tenant: get_handle returns the requested one only."""
    ledger = InMemoryLedger()
    sid_a = UUID("00000000-0000-0000-0000-00000000000a")
    sid_b = UUID("00000000-0000-0000-0000-00000000000b")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=sid_a,
        source_kind="csv_local", uri="/tmp/a.csv",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=sid_a,
    )
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=sid_b,
        source_kind="postgres", uri="postgresql://b",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=sid_b,
    )

    provider = LedgerSourceHandleProvider(ledger=ledger)
    record_a = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(sid_a),
    )
    record_b = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(sid_b),
    )
    assert record_a is not None
    assert record_a.connector_kind == "csv_local"
    assert record_b is not None
    assert record_b.connector_kind == "postgres"


@pytest.mark.asyncio
async def test_multi_tenant_isolation() -> None:
    """Same source_id in tenant A and tenant B → handles are isolated."""
    ledger = InMemoryLedger()
    sid_shared = UUID("00000000-0000-0000-0000-000000099999")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=sid_shared,
        source_kind="csv_local", uri="/tmp/a-tenant.csv",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=sid_shared,
    )
    # Tenant B never proposes or connects this source_id.
    provider = LedgerSourceHandleProvider(ledger=ledger)

    record_a = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(sid_shared),
    )
    record_b = await provider.get_handle(
        company_id=_TENANT_B, source_id=str(sid_shared),
    )
    assert record_a is not None
    assert record_a.connector_kind == "csv_local"
    assert record_b is None
