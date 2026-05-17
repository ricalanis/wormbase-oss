"""CredentialBroker Protocol-conformance suite — runs against every impl.

Per Wave 2 plan §Task 2 Step 3. The same test bodies run against both
`EnvCredentialBroker` and `VaultCredentialBroker`; the Vault entry skips
automatically when `VAULT_ADDR` / `VAULT_TOKEN` are not set.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest

from wormbase_agent_gateway.credential_broker import (
    CredentialBroker,
    DataScope,
    EnvCredentialBroker,
    ModelScope,
    VaultCredentialBroker,
)


def _vault_available() -> bool:
    return bool(os.environ.get("VAULT_ADDR")) and bool(os.environ.get("VAULT_TOKEN"))


_BROKERS: list[pytest.param] = [
    pytest.param("env", id="env"),
]
if _vault_available():
    _BROKERS.append(pytest.param("vault", id="vault"))


@pytest.fixture
def broker(request: pytest.FixtureRequest, tmp_path):
    kind = request.param
    if kind == "env":
        return EnvCredentialBroker(secrets_dir=tmp_path)
    if kind == "vault":
        return VaultCredentialBroker(
            addr=os.environ["VAULT_ADDR"],
            token=os.environ["VAULT_TOKEN"],
        )
    raise ValueError(kind)


@pytest.fixture
def install_id() -> str:
    """Per-test unique install_id so Vault state doesn't collide across runs."""
    return f"install-{uuid.uuid4()}"


@pytest.mark.parametrize("broker", _BROKERS, indirect=True)
def test_satisfies_protocol(broker) -> None:
    assert isinstance(broker, CredentialBroker)


@pytest.mark.parametrize("broker", _BROKERS, indirect=True)
@pytest.mark.asyncio
async def test_hold_data_account_returns_handle_with_kind_and_install(
    broker, install_id
) -> None:
    await broker.put_secret(
        f"data/snowflake/{install_id}",
        {"user": "alice", "password": "secret"},
    )
    h = await broker.hold_data_account(install_id, upstream_kind="snowflake")
    assert h.kind == "data"
    assert h.upstream_kind == "snowflake"
    assert h.install_id == install_id
    assert h.payload.get("user") == "alice"


@pytest.mark.parametrize("broker", _BROKERS, indirect=True)
@pytest.mark.asyncio
async def test_hold_model_account_returns_handle_with_kind_model(
    broker, install_id
) -> None:
    await broker.put_secret(
        f"data/kimi/{install_id}",
        {"api_key": "ollama-token-xyz"},
    )
    h = await broker.hold_model_account(install_id, model_kind="kimi")
    assert h.kind == "model"
    assert h.upstream_kind == "kimi"
    assert h.install_id == install_id
    assert h.payload.get("api_key") == "ollama-token-xyz"


@pytest.mark.parametrize("broker", _BROKERS, indirect=True)
@pytest.mark.asyncio
async def test_issue_data_token_is_time_and_scope_bounded(broker) -> None:
    token = await broker.issue_data_token(
        agent_id="claude_research",
        scope=DataScope(resource_id="WORMBASE_SPIKE.PUBLIC.REVENUE_BY_REGION"),
        ttl_s=60,
    )
    assert token.expires_at - token.issued_at == 60
    assert token.kind == "data"
    assert isinstance(token.scope, DataScope)
    assert token.scope.resource_id == "WORMBASE_SPIKE.PUBLIC.REVENUE_BY_REGION"


@pytest.mark.parametrize("broker", _BROKERS, indirect=True)
@pytest.mark.asyncio
async def test_issue_model_token_carries_budget(broker) -> None:
    token = await broker.issue_model_token(
        agent_id="claude_research",
        scope=ModelScope(model_kind="kimi", budget_usd=Decimal("0.50")),
        ttl_s=300,
    )
    assert isinstance(token.scope, ModelScope)
    assert token.scope.budget_usd == Decimal("0.50")
    assert token.kind == "model"


@pytest.mark.parametrize("broker", _BROKERS, indirect=True)
@pytest.mark.asyncio
async def test_revoke_marks_invalid(broker) -> None:
    token = await broker.issue_data_token(
        agent_id="agent-1",
        scope=DataScope(resource_id="x"),
        ttl_s=600,
    )
    assert await broker.is_valid(token.token_id) is True
    await broker.revoke(token.token_id)
    assert await broker.is_valid(token.token_id) is False
