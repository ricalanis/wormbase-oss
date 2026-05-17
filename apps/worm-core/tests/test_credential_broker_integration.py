"""CredentialBroker integration — opaque-secret connector sampler unblock.

Pins the additive 2026-06-10 behavior on
:class:`wormbase_core.source_handle_provider.LedgerSourceHandleProvider`:

  * Default-OFF byte-identical: with no broker, opaque-secret connectors
    return ``None`` (same as Sampler activation Wave default).
  * Broker wired + credential_ref present + per-kind assembler →
    productive :class:`SourceHandleRecord` with a real AuthHandle.
  * Broker wired but credential_ref absent → ``None`` (honest fallback).
  * Broker.hold_data_account raises → ``None`` (defensive boundary).
  * Per-kind assembler shape verified for stripe / salesforce / hubspot /
    gsheets against their connector ``authenticate()`` contracts.
  * Construction-site env knob matrix for
    ``WORMBASE_CREDENTIAL_BROKER_KIND`` (none / vault / env / unknown).
  * End-to-end integration: opaque-secret connector becomes sampler-
    productive when broker + credential_ref are both wired.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_ledger.entries import (
    SourceConnectedPayload,
    SourceProposedPayload,
)

from wormbase_core.source_handle_provider import (
    NON_OPAQUE_CONNECTOR_KINDS,
    OPAQUE_AUTH_HANDLE_ASSEMBLERS,
    LedgerSourceHandleProvider,
    SourceHandleRecord,
)


_TENANT_A = UUID("00000000-0000-0000-0000-000000000aaa")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeAccountHandle:
    """Mirrors ``AccountHandle`` from agent-gateway: only ``.payload`` matters."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload


class FakeCredentialBroker:
    """In-memory broker. Lookups keyed by ``(install_id, upstream_kind)``."""

    kind: str = "fake"

    def __init__(self, secrets: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._secrets = secrets
        self.calls: list[tuple[str, str]] = []

    async def hold_data_account(
        self, install_id: str, *, upstream_kind: str,
    ) -> _FakeAccountHandle:
        self.calls.append((install_id, upstream_kind))
        payload = self._secrets.get((install_id, upstream_kind))
        if payload is None:
            raise KeyError(
                f"no fake secret for install_id={install_id} "
                f"upstream_kind={upstream_kind}",
            )
        return _FakeAccountHandle(payload=dict(payload))


class RaisingCredentialBroker:
    """Broker that always raises — pins the defensive-boundary path."""

    kind: str = "raising"

    async def hold_data_account(
        self, install_id: str, *, upstream_kind: str,
    ) -> Any:
        raise RuntimeError(
            f"simulated broker outage for {install_id}/{upstream_kind}",
        )


# ---------------------------------------------------------------------------
# Ledger seed helpers (mirror test_source_handle_provider.py)
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


async def _emit_source_connected(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: UUID,
    connection_ref: str = "test-connection",
    credential_ref: str | None = None,
) -> None:
    payload = SourceConnectedPayload(
        source_id=source_id,
        connection_ref=connection_ref,
        connected_at=datetime.now(UTC),
        credential_ref=credential_ref,
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
# A. Default-OFF preservation: no broker → opaque kinds still None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_broker_opaque_kind_returns_none_byte_identical() -> None:
    """Without a broker wired, opaque-secret kinds stay honest-empty.

    This pins the Sampler-activation-Wave default-OFF byte-identical
    contract: even with the credential_ref additive field set, the
    provider must return None when no broker is supplied.
    """
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000a0001")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="stripe", uri="stripe://acct_test",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="stripe-prod",  # even with ref set
    )
    provider = LedgerSourceHandleProvider(ledger=ledger)
    assert provider.credential_broker is None
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is None


@pytest.mark.asyncio
async def test_no_broker_csv_local_still_productive() -> None:
    """URI-shaped kinds are unaffected by broker wiring.

    csv_local reconstructs from URI alone — provider must keep returning
    a real SourceHandleRecord whether broker is wired or not.
    """
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000a0002")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="csv_local", uri="/tmp/x.csv",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
    )
    provider = LedgerSourceHandleProvider(ledger=ledger)
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert isinstance(result, SourceHandleRecord)
    assert result.connector_kind == "csv_local"


# ---------------------------------------------------------------------------
# B. Broker wired but credential_ref missing → None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broker_wired_but_no_credential_ref_returns_none() -> None:
    """Provider gracefully returns None when credential_ref is missing.

    Pre-2026-06-10 ledger entries lack credential_ref entirely (defaults
    to None). Provider must not crash; honest-empty fallback preserved.
    """
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000b0001")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="stripe", uri="stripe://acct_test",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref=None,
    )
    broker = FakeCredentialBroker(secrets={})
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is None
    # Provider must not have called the broker when ref is missing.
    assert broker.calls == []


# ---------------------------------------------------------------------------
# C. Broker raises → defensive None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broker_raises_returns_none() -> None:
    """Broker outage must degrade to honest-empty, not propagate."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000c0001")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="stripe", uri="stripe://acct_test",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="stripe-prod",
    )
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=RaisingCredentialBroker(),
    )
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is None


# ---------------------------------------------------------------------------
# D. Per-kind productive path — stripe / salesforce / hubspot / gsheets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stripe_handle_assembled_via_broker() -> None:
    """stripe: broker payload → AuthHandle with api_key + auth_header."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000d0001")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="stripe", uri="stripe://acct_test",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="stripe-acme",
    )
    broker = FakeCredentialBroker(secrets={
        ("stripe-acme", "stripe"): {
            "api_key": "sk_test_fakefake",
            "api_version": "2023-10-16",
        },
    })
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert isinstance(result, SourceHandleRecord)
    assert result.connector_kind == "stripe"
    auth = result.auth_handle
    # AuthHandle shape from wormbase_lake_surfaces.types
    assert getattr(auth, "connector_kind", None) == "stripe"
    extra = getattr(auth, "extra", {})
    assert extra.get("api_key") == "sk_test_fakefake"
    assert extra.get("api_version") == "2023-10-16"
    # auth_header is precomputed Basic header
    assert isinstance(extra.get("auth_header"), str)
    assert extra["auth_header"].startswith("Basic ")
    assert broker.calls == [("stripe-acme", "stripe")]


@pytest.mark.asyncio
async def test_stripe_broker_payload_missing_api_key_returns_none() -> None:
    """stripe: broker payload without api_key falls back to None."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000d0002")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="stripe", uri="stripe://acct_test",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="stripe-malformed",
    )
    broker = FakeCredentialBroker(secrets={
        ("stripe-malformed", "stripe"): {"not_an_api_key": "x"},
    })
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is None


@pytest.mark.asyncio
async def test_salesforce_handle_assembled_via_broker() -> None:
    """salesforce: broker payload → AuthHandle with instance_url + access_token."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000d0003")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="salesforce", uri="salesforce://acme",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="sfdc-acme",
    )
    broker = FakeCredentialBroker(secrets={
        ("sfdc-acme", "salesforce"): {
            "instance_url": "https://acme.my.salesforce.com",
            "access_token": "00D-FAKE",
            "refresh_token": "RT-FAKE",
        },
    })
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert isinstance(result, SourceHandleRecord)
    assert result.connector_kind == "salesforce"
    extra = getattr(result.auth_handle, "extra", {})
    assert extra.get("instance_url") == "https://acme.my.salesforce.com"
    assert extra.get("access_token") == "00D-FAKE"


@pytest.mark.asyncio
async def test_salesforce_missing_instance_url_returns_none() -> None:
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000d0004")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="salesforce", uri="salesforce://acme",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="sfdc-partial",
    )
    broker = FakeCredentialBroker(secrets={
        ("sfdc-partial", "salesforce"): {"access_token": "TOKEN"},
    })
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is None


@pytest.mark.asyncio
async def test_hubspot_handle_assembled_via_broker() -> None:
    """hubspot: broker payload → AuthHandle with access_token."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000d0005")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="hubspot", uri="hubspot://acme",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="hubspot-acme",
    )
    broker = FakeCredentialBroker(secrets={
        ("hubspot-acme", "hubspot"): {
            "access_token": "pat-na1-FAKE",
        },
    })
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert isinstance(result, SourceHandleRecord)
    assert result.connector_kind == "hubspot"
    extra = getattr(result.auth_handle, "extra", {})
    assert extra.get("access_token") == "pat-na1-FAKE"


@pytest.mark.asyncio
async def test_hubspot_missing_access_token_returns_none() -> None:
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000d0006")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="hubspot", uri="hubspot://acme",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="hubspot-empty",
    )
    broker = FakeCredentialBroker(secrets={
        ("hubspot-empty", "hubspot"): {},
    })
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is None


@pytest.mark.asyncio
async def test_gsheets_handle_assembled_via_broker() -> None:
    """gsheets: broker payload → AuthHandle with service_account_json."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000d0007")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="gsheets", uri="gsheets://spreadsheet_id_x",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="gsheets-acme",
    )
    sa_json_blob = '{"type":"service_account","client_email":"x@y.iam"}'
    broker = FakeCredentialBroker(secrets={
        ("gsheets-acme", "gsheets"): {
            "service_account_json": sa_json_blob,
        },
    })
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert isinstance(result, SourceHandleRecord)
    assert result.connector_kind == "gsheets"
    extra = getattr(result.auth_handle, "extra", {})
    assert extra.get("service_account_json") == sa_json_blob


# ---------------------------------------------------------------------------
# E. install_id override (multi-tenant SaaS use case)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_id_override_threads_to_broker() -> None:
    """When the provider carries an install_id, it overrides credential_ref."""
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000e0001")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="stripe", uri="stripe://acct_test",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="ref-X",
    )
    broker = FakeCredentialBroker(secrets={
        ("install-saas", "stripe"): {"api_key": "sk_test_OVERRIDE"},
    })
    provider = LedgerSourceHandleProvider(
        ledger=ledger,
        credential_broker=broker,
        install_id="install-saas",  # overrides credential_ref for broker lookup
    )
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert isinstance(result, SourceHandleRecord)
    assert getattr(result.auth_handle, "extra", {}).get("api_key") == (
        "sk_test_OVERRIDE"
    )
    assert broker.calls == [("install-saas", "stripe")]


# ---------------------------------------------------------------------------
# F. Unknown opaque kinds (mcp:*, etc.) — None even with broker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_opaque_kind_returns_none_even_with_broker() -> None:
    """kinds outside both classifications return None.

    mcp:* server presets are deliberately not in OPAQUE_AUTH_HANDLE_ASSEMBLERS
    (deferred until MCP broker integration lands). They surface None
    here regardless of broker wiring.
    """
    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000f0001")
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="mcp:custom_server", uri="https://mcp.example/sse",
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="mcp-cred",
    )
    broker = FakeCredentialBroker(secrets={
        ("mcp-cred", "mcp:custom_server"): {"bearer_token": "BT"},
    })
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )
    result = await provider.get_handle(
        company_id=_TENANT_A, source_id=str(source_id),
    )
    assert result is None


# ---------------------------------------------------------------------------
# G. Classification constants — pins NON_OPAQUE vs OPAQUE coverage
# ---------------------------------------------------------------------------


def test_non_opaque_connector_kinds_cover_uri_shaped_kinds() -> None:
    """The frozenset of URI-shaped kinds matches Sampler-Wave coverage."""
    assert NON_OPAQUE_CONNECTOR_KINDS == frozenset({
        "csv_local", "postgres", "snowflake", "bigquery", "s3_csv", "http_csv",
    })


def test_opaque_assemblers_cover_initial_saas_set() -> None:
    """The per-kind assembler registry covers the initial productive SaaS set."""
    assert set(OPAQUE_AUTH_HANDLE_ASSEMBLERS.keys()) == {
        "stripe", "salesforce", "hubspot", "gsheets",
    }


def test_classifications_disjoint() -> None:
    """A connector kind must not be in BOTH classification sets."""
    overlap = NON_OPAQUE_CONNECTOR_KINDS & set(
        OPAQUE_AUTH_HANDLE_ASSEMBLERS.keys(),
    )
    assert overlap == set()


# ---------------------------------------------------------------------------
# H. Construction-site env-knob matrix
# ---------------------------------------------------------------------------


def test_build_credential_broker_for_sampler_unset_returns_none() -> None:
    """``WORMBASE_CREDENTIAL_BROKER_KIND`` unset → no broker."""
    from wormbase_core.agent_gateway_construction import (
        _build_credential_broker_for_sampler,
    )
    with patch.dict("os.environ", {}, clear=False):
        # Make sure the knob is unset for this test
        import os as _os
        _os.environ.pop("WORMBASE_CREDENTIAL_BROKER_KIND", None)
        broker = _build_credential_broker_for_sampler()
    assert broker is None


def test_build_credential_broker_for_sampler_none_returns_none() -> None:
    """``WORMBASE_CREDENTIAL_BROKER_KIND=none`` → no broker."""
    from wormbase_core.agent_gateway_construction import (
        _build_credential_broker_for_sampler,
    )
    with patch.dict(
        "os.environ",
        {"WORMBASE_CREDENTIAL_BROKER_KIND": "none"},
        clear=False,
    ):
        broker = _build_credential_broker_for_sampler()
    assert broker is None


def test_build_credential_broker_for_sampler_unknown_kind_returns_none() -> None:
    """Unknown broker-kind value → defensive None + warning."""
    from wormbase_core.agent_gateway_construction import (
        _build_credential_broker_for_sampler,
    )
    with patch.dict(
        "os.environ",
        {"WORMBASE_CREDENTIAL_BROKER_KIND": "aws_sm_v1_1"},
        clear=False,
    ):
        broker = _build_credential_broker_for_sampler()
    assert broker is None


def test_build_credential_broker_for_sampler_vault_without_addr() -> None:
    """vault kind without VAULT_ADDR/TOKEN → None."""
    from wormbase_core.agent_gateway_construction import (
        _build_credential_broker_for_sampler,
    )
    import os as _os
    # Snapshot + clear VAULT env so the test runs hermetically
    snapshot = {
        k: _os.environ.get(k)
        for k in (
            "VAULT_ADDR", "VAULT_TOKEN",
            "WORMBASE_VAULT_ADDR", "WORMBASE_VAULT_TOKEN",
        )
    }
    try:
        for k in snapshot:
            _os.environ.pop(k, None)
        _os.environ["WORMBASE_CREDENTIAL_BROKER_KIND"] = "vault"
        broker = _build_credential_broker_for_sampler()
    finally:
        for k, v in snapshot.items():
            if v is not None:
                _os.environ[k] = v
            else:
                _os.environ.pop(k, None)
        _os.environ.pop("WORMBASE_CREDENTIAL_BROKER_KIND", None)
    assert broker is None


def test_build_credential_broker_for_sampler_env_without_secrets_dir() -> None:
    """env kind without secrets_dir env knob → None."""
    from wormbase_core.agent_gateway_construction import (
        _build_credential_broker_for_sampler,
    )
    import os as _os
    snapshot = {
        k: _os.environ.get(k)
        for k in (
            "WORMBASE_CREDENTIAL_ENV_PREFIX",
            "WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR",
        )
    }
    try:
        for k in snapshot:
            _os.environ.pop(k, None)
        _os.environ["WORMBASE_CREDENTIAL_BROKER_KIND"] = "env"
        broker = _build_credential_broker_for_sampler()
    finally:
        for k, v in snapshot.items():
            if v is not None:
                _os.environ[k] = v
            else:
                _os.environ.pop(k, None)
        _os.environ.pop("WORMBASE_CREDENTIAL_BROKER_KIND", None)
    assert broker is None


def test_build_credential_broker_for_sampler_env_with_secrets_dir(
    tmp_path: Any,
) -> None:
    """env kind WITH secrets_dir → real EnvCredentialBroker shipped."""
    from wormbase_core.agent_gateway_construction import (
        _build_credential_broker_for_sampler,
    )
    import os as _os
    secrets_dir = tmp_path / "broker-secrets"
    secrets_dir.mkdir()
    snapshot = {
        k: _os.environ.get(k)
        for k in (
            "WORMBASE_CREDENTIAL_BROKER_KIND",
            "WORMBASE_CREDENTIAL_ENV_PREFIX",
            "WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR",
        )
    }
    try:
        _os.environ["WORMBASE_CREDENTIAL_BROKER_KIND"] = "env"
        _os.environ["WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR"] = str(secrets_dir)
        broker = _build_credential_broker_for_sampler()
    finally:
        for k, v in snapshot.items():
            if v is not None:
                _os.environ[k] = v
            else:
                _os.environ.pop(k, None)
    # EnvCredentialBroker satisfies the Protocol structurally
    assert broker is not None
    assert broker.__class__.__name__ == "EnvCredentialBroker"


# ---------------------------------------------------------------------------
# I. _build_active_sampler_if_enabled — broker threaded into provider
# ---------------------------------------------------------------------------


def test_active_sampler_threads_broker_to_handle_provider(
    tmp_path: Any,
) -> None:
    """When both Sampler activation AND broker knob are on, the provider
    receives the broker instance."""
    from wormbase_core.agent_gateway_construction import (
        _build_active_sampler_if_enabled,
    )
    import os as _os

    snapshot = {
        k: _os.environ.get(k)
        for k in (
            "WORMBASE_SAMPLER_ACTIVATION_ENABLED",
            "WORMBASE_CREDENTIAL_BROKER_KIND",
            "WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR",
        )
    }
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    try:
        _os.environ["WORMBASE_SAMPLER_ACTIVATION_ENABLED"] = "true"
        _os.environ["WORMBASE_CREDENTIAL_BROKER_KIND"] = "env"
        _os.environ["WORMBASE_CREDENTIAL_BROKER_SECRETS_DIR"] = str(secrets_dir)
        sampler = _build_active_sampler_if_enabled(
            ledger=InMemoryLedger(), company_id=_TENANT_A,
        )
    finally:
        for k, v in snapshot.items():
            if v is not None:
                _os.environ[k] = v
            else:
                _os.environ.pop(k, None)

    # The ConnectorSampler must carry a LedgerSourceHandleProvider whose
    # credential_broker is the EnvCredentialBroker we constructed above.
    handle_provider = getattr(sampler, "handle_provider", None)
    assert handle_provider is not None
    assert handle_provider.credential_broker is not None
    assert handle_provider.credential_broker.__class__.__name__ == (
        "EnvCredentialBroker"
    )


def test_active_sampler_no_broker_when_knob_unset() -> None:
    """Sampler activation ON but broker knob unset → provider broker is None."""
    from wormbase_core.agent_gateway_construction import (
        _build_active_sampler_if_enabled,
    )
    import os as _os

    snapshot = {
        k: _os.environ.get(k)
        for k in (
            "WORMBASE_SAMPLER_ACTIVATION_ENABLED",
            "WORMBASE_CREDENTIAL_BROKER_KIND",
        )
    }
    try:
        _os.environ["WORMBASE_SAMPLER_ACTIVATION_ENABLED"] = "true"
        _os.environ.pop("WORMBASE_CREDENTIAL_BROKER_KIND", None)
        sampler = _build_active_sampler_if_enabled(
            ledger=InMemoryLedger(), company_id=_TENANT_A,
        )
    finally:
        for k, v in snapshot.items():
            if v is not None:
                _os.environ[k] = v
            else:
                _os.environ.pop(k, None)

    handle_provider = getattr(sampler, "handle_provider", None)
    assert handle_provider is not None
    assert handle_provider.credential_broker is None


# ---------------------------------------------------------------------------
# J. End-to-end integration — ConnectorSampler.sample_column productive
# ---------------------------------------------------------------------------


class _FakeOpaqueConnector:
    """A tiny opaque-secret connector for the e2e test.

    Mirrors StripeSurfaceDriver's shape just enough that ConnectorSampler can
    drive it: ``authenticate`` is bypassed (the provider hand-assembled
    the handle), and ``sample`` returns CSV bytes built from the handle's
    extra.api_key — proving the broker-resolved secret reached the
    connector via the handle.
    """

    kind = "fake_opaque"

    async def sample(
        self, handle: Any, resource_id: str, n: int,
    ) -> bytes:
        api_key = getattr(handle, "extra", {}).get("api_key", "MISSING")
        # Emit a CSV whose values prove the api_key flowed through.
        lines = ["id"]
        for i in range(min(n, 3)):
            lines.append(f"{api_key}_{resource_id}_{i}")
        return "\n".join(lines).encode("utf-8")


@pytest.mark.asyncio
async def test_e2e_opaque_secret_connector_productive_when_wired() -> None:
    """End-to-end: opaque kind + broker + credential_ref → sampler returns values.

    Wires:
      1. LedgerSourceHandleProvider with a FakeCredentialBroker that
         returns ``{"api_key": "sk_known"}`` for a stripe slot.
      2. ConnectorSampler over a stub registry that maps "stripe" to
         FakeOpaqueConnector (which reads handle.extra.api_key).
      3. Seed source_proposed + source_connected for a stripe source
         with credential_ref set.
      4. sample_column → returns the api_key-encoded values.

    Pins the entire chain: ledger fold → broker resolve → per-kind
    assembler → AuthHandle → SurfaceDriver.sample → CSV parse → set[str].
    """
    from wormbase_core.connector_sampler import ConnectorSampler

    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000e2e01")
    table_uri = "stripe://acme/charges"
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="stripe", uri=table_uri,
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="stripe-acme",
    )
    broker = FakeCredentialBroker(secrets={
        ("stripe-acme", "stripe"): {"api_key": "sk_known"},
    })
    provider = LedgerSourceHandleProvider(
        ledger=ledger, credential_broker=broker,
    )

    # Stub the registry — return FakeOpaqueConnector for "stripe".
    class _StubRegistry:
        def get(self, kind: str) -> Any:
            return _FakeOpaqueConnector if kind == "stripe" else None

    sampler = ConnectorSampler(
        handle_provider=provider,
        company_id=_TENANT_A,
        connector_registry=_StubRegistry(),
    )
    # table_id maps to the source URI (single-resource convention from
    # the provider's resource_map).
    result = await sampler.sample_column(table_uri, column="id", n=3)
    # FakeOpaqueConnector emitted ``sk_known_<resource_id>_<i>`` rows;
    # ConnectorSampler parsed them via CSV with "id" header.
    assert result == {
        f"sk_known_{table_uri}_0",
        f"sk_known_{table_uri}_1",
        f"sk_known_{table_uri}_2",
    }
    # Verify broker was actually called — pins the wiring path.
    assert broker.calls == [("stripe-acme", "stripe")]


@pytest.mark.asyncio
async def test_e2e_without_broker_returns_empty_set() -> None:
    """Same setup, broker omitted → sample_column returns empty set."""
    from wormbase_core.connector_sampler import ConnectorSampler

    ledger = InMemoryLedger()
    source_id = UUID("00000000-0000-0000-0000-0000000e2e02")
    table_uri = "stripe://acme/charges"
    await _emit_source_proposed(
        ledger, company_id=_TENANT_A, source_id=source_id,
        source_kind="stripe", uri=table_uri,
    )
    await _emit_source_connected(
        ledger, company_id=_TENANT_A, source_id=source_id,
        credential_ref="stripe-acme",
    )
    provider = LedgerSourceHandleProvider(ledger=ledger)  # no broker

    class _StubRegistry:
        def get(self, kind: str) -> Any:
            return _FakeOpaqueConnector if kind == "stripe" else None

    sampler = ConnectorSampler(
        handle_provider=provider,
        company_id=_TENANT_A,
        connector_registry=_StubRegistry(),
    )
    result = await sampler.sample_column(table_uri, column="id", n=3)
    assert result == set()
