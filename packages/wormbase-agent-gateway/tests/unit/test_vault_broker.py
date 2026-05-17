"""VaultCredentialBroker impl-specific tests.

Protocol-conformance is covered in test_credential_broker_protocol.py. This
module covers behavior unique to Vault: state-reload from KV at startup
(S4 spike improvement) and broker-restart token-validity recovery.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest

from wormbase_agent_gateway.credential_broker import (
    DataScope,
    ModelScope,
    VaultCredentialBroker,
)


def _vault_available() -> bool:
    return bool(os.environ.get("VAULT_ADDR")) and bool(os.environ.get("VAULT_TOKEN"))


pytestmark = pytest.mark.skipif(
    not _vault_available(),
    reason="VAULT_ADDR / VAULT_TOKEN not set",
)


@pytest.fixture
def vault_broker() -> VaultCredentialBroker:
    return VaultCredentialBroker(
        addr=os.environ["VAULT_ADDR"],
        token=os.environ["VAULT_TOKEN"],
    )


@pytest.mark.asyncio
async def test_auth_failure_raises(monkeypatch) -> None:
    from wormbase_agent_gateway.credential_broker import AuthenticationError

    with pytest.raises(AuthenticationError):
        VaultCredentialBroker(
            addr=os.environ["VAULT_ADDR"],
            token="definitely-not-a-real-token",
        )


@pytest.mark.asyncio
async def test_issued_state_reloads_after_restart(vault_broker) -> None:
    """S4 spike finding: in-memory _issued didn't survive restart.

    Productionized broker reloads from Vault KV at __init__ so token validity
    persists across process boundaries.
    """
    token = await vault_broker.issue_data_token(
        agent_id="restart-agent",
        scope=DataScope(resource_id=f"resource-{uuid.uuid4()}"),
        ttl_s=600,
    )
    assert await vault_broker.is_valid(token.token_id) is True

    # Simulate restart: new broker instance, same Vault.
    fresh = VaultCredentialBroker(
        addr=os.environ["VAULT_ADDR"],
        token=os.environ["VAULT_TOKEN"],
    )
    # New broker should see the token as still valid via reload-from-Vault.
    assert await fresh.is_valid(token.token_id) is True

    # Cleanup
    await fresh.revoke(token.token_id)


@pytest.mark.asyncio
async def test_model_token_reload_preserves_budget(vault_broker) -> None:
    token = await vault_broker.issue_model_token(
        agent_id="restart-agent",
        scope=ModelScope(model_kind="kimi", budget_usd=Decimal("1.25")),
        ttl_s=600,
    )

    fresh = VaultCredentialBroker(
        addr=os.environ["VAULT_ADDR"],
        token=os.environ["VAULT_TOKEN"],
    )
    assert await fresh.is_valid(token.token_id) is True
    reloaded = fresh._issued[token.token_id]
    assert reloaded.kind == "model"
    assert isinstance(reloaded.scope, ModelScope)
    assert reloaded.scope.model_kind == "kimi"
    assert reloaded.scope.budget_usd == Decimal("1.25")

    await fresh.revoke(token.token_id)


@pytest.mark.asyncio
async def test_revoke_deletes_from_vault(vault_broker) -> None:
    """After revoke, a fresh broker reload should NOT see the token as valid."""
    token = await vault_broker.issue_data_token(
        agent_id="revoke-agent",
        scope=DataScope(resource_id=f"resource-{uuid.uuid4()}"),
        ttl_s=600,
    )
    await vault_broker.revoke(token.token_id)

    fresh = VaultCredentialBroker(
        addr=os.environ["VAULT_ADDR"],
        token=os.environ["VAULT_TOKEN"],
    )
    # Token deleted from Vault, so reload doesn't repopulate.
    assert await fresh.is_valid(token.token_id) is False
