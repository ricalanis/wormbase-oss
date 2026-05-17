"""Unit tests for ``identity/credential.py`` — issue/revoke lifecycle.

Per doctrine Addendum 3: ``credential`` is ONE kind with a status field;
issue → status="active", revoke → status="revoked". The helpers delegate
to the CredentialBroker for token mint/revoke and emit a degenerate PEVR
cycle for audit (matching lake-maintainer._emit_signal).
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from wormbase_agent_gateway.credential_broker import (
    DataScope,
    EnvCredentialBroker,
    ModelScope,
)
from wormbase_agent_gateway.identity import (
    issue_data_credential,
    issue_model_credential,
    revoke_credential,
)
from wormbase_inference import AgentID
from wormbase_ledger.ledger_api import InMemoryLedger


@pytest.mark.asyncio
async def test_issue_data_credential_mints_token_and_emits_active_entry(
    tmp_path,
) -> None:
    """Two-step transaction:
        1. Broker issues a ScopedToken.
        2. Ledger records credential(status="active") with ttl_expires_at
           matching the token.
    """
    broker = EnvCredentialBroker(secrets_dir=tmp_path)
    ledger = InMemoryLedger()
    company_id = uuid4()
    agent = AgentID.from_legacy_string("agent-uuid-1")
    scope = DataScope(resource_id="snowflake://WORMBASE_SPIKE.PUBLIC.REVENUE_BY_REGION")

    token = await issue_data_credential(
        broker=broker,
        ledger=ledger,
        company_id=company_id,
        agent_id=agent,
        scope=scope,
        ttl_s=600,
    )

    # Broker side.
    assert token.kind == "data"
    assert token.scope == scope
    assert await broker.is_valid(token.token_id) is True

    # Ledger side — 4-entry degenerate PEVR cycle (audit only).
    entries = await ledger.fetch(company_id)
    assert len(entries) == 4
    propose = entries[0]["payload"]
    assert propose["agent_id"] == "agent-uuid-1"
    assert propose["credential_kind"] == "data"
    assert propose["target"] == scope.resource_id
    assert propose["status"] == "active"
    assert propose["issued_by"] == "agent-gateway"
    # Token's expires_at flows into ttl_expires_at as ISO-8601.
    assert "T" in propose["ttl_expires_at"]


@pytest.mark.asyncio
async def test_issue_model_credential_uses_model_kind_as_target(
    tmp_path,
) -> None:
    """Model credentials carry model_kind in target (e.g. "kimi")."""
    broker = EnvCredentialBroker(secrets_dir=tmp_path)
    ledger = InMemoryLedger()
    company_id = uuid4()
    agent = AgentID.from_legacy_string("agent-uuid-1")
    scope = ModelScope(model_kind="kimi", budget_usd=Decimal("5.00"))

    token = await issue_model_credential(
        broker=broker,
        ledger=ledger,
        company_id=company_id,
        agent_id=agent,
        scope=scope,
        ttl_s=600,
    )

    assert token.kind == "model"
    entries = await ledger.fetch(company_id)
    assert len(entries) == 4
    payload = entries[0]["payload"]
    assert payload["credential_kind"] == "model"
    assert payload["target"] == "kimi"
    assert payload["status"] == "active"


@pytest.mark.asyncio
async def test_revoke_credential_revokes_broker_and_emits_revoked_entry(
    tmp_path,
) -> None:
    """Revoking emits a credential entry with status="revoked" while also
    revoking the broker token."""
    broker = EnvCredentialBroker(secrets_dir=tmp_path)
    ledger = InMemoryLedger()
    company_id = uuid4()
    agent = AgentID.from_legacy_string("agent-uuid-1")
    scope = DataScope(resource_id="resource-uuid")

    token = await issue_data_credential(
        broker=broker,
        ledger=ledger,
        company_id=company_id,
        agent_id=agent,
        scope=scope,
        ttl_s=600,
    )
    # After issue: 4 entries (active).
    entries_before = await ledger.fetch(company_id)
    assert len(entries_before) == 4

    await revoke_credential(
        broker=broker,
        ledger=ledger,
        company_id=company_id,
        agent_id=agent,
        token_id=token.token_id,
        credential_kind="data",
        target=scope.resource_id,
        ttl_expires_at=entries_before[0]["payload"]["ttl_expires_at"],
    )

    # Broker side — token no longer valid.
    assert await broker.is_valid(token.token_id) is False

    # Ledger side — 8 entries total (issue cycle + revoke cycle).
    entries_after = await ledger.fetch(company_id)
    assert len(entries_after) == 8
    revoke_propose = entries_after[4]["payload"]
    assert revoke_propose["status"] == "revoked"
    assert revoke_propose["agent_id"] == "agent-uuid-1"
    assert revoke_propose["credential_kind"] == "data"
    assert revoke_propose["target"] == "resource-uuid"
