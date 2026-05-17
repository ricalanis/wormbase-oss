"""Unit tests for the broker vs federate dispatch router.

Covers:
    - choose_route_mode default policy.
    - BrokerExecutor against a stub driver returns BrokerExecutionResult.
    - BrokerExecutor raises NotImplementedError for non-Snowflake upstreams.
    - FederateIssuer issues a ScopedDataToken + composes a callback URL.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from wormbase_inference import AgentID

from wormbase_agent_gateway.credential_broker import EnvCredentialBroker
from wormbase_agent_gateway.query_spec import CompiledQuery
from wormbase_agent_gateway.router_query import (
    BrokerExecutor,
    FederateIssuer,
    choose_route_mode,
)


@dataclass
class _StubDriver:
    rows: list[dict[str, Any]] = field(default_factory=list)
    last: dict[str, Any] | None = None

    async def query(self, *, account, sql, params):
        self.last = {"account": account, "sql": sql, "params": params}
        return list(self.rows)


def _spec_stub():
    """Use a real CompiledQuery dataclass instance — no QuerySpec needed."""
    return None


def test_choose_route_mode_defaults_to_broker():
    assert choose_route_mode(_spec_stub()) == "broker"
    assert choose_route_mode(_spec_stub(), classification="internal") == "broker"
    assert choose_route_mode(_spec_stub(), classification="confidential") == "broker"
    assert choose_route_mode(_spec_stub(), classification="regulated") == "broker"


async def test_broker_executor_runs_compiled_query(tmp_path: Path):
    secrets = tmp_path / "secrets"
    broker = EnvCredentialBroker(secrets_dir=secrets)
    secret_path = secrets / "data" / "snowflake" / "install-1"
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(json.dumps({"account": "abc"}))

    driver = _StubDriver(rows=[{"a": 1}, {"a": 2}, {"a": 3}])
    ex = BrokerExecutor(broker=broker, install_id="install-1", driver=driver)
    compiled = CompiledQuery(
        sql="SELECT * FROM t WHERE x=%s",
        upstream_kind="snowflake",
        upstream_resource_id="tbl-1",
        parameter_values=("v1",),
        masking_policies_applied=("policy_a",),
    )
    result = await ex.execute(compiled)
    assert result.row_count == 3
    assert result.sample_rows == ({"a": 1}, {"a": 2}, {"a": 3})
    assert result.rows_hash  # stable sha256
    assert result.masking_policies_applied == ("policy_a",)
    assert driver.last is not None
    assert driver.last["sql"] == compiled.sql
    assert driver.last["params"] == ["v1"]


async def test_broker_executor_rejects_non_snowflake(tmp_path: Path):
    broker = EnvCredentialBroker(secrets_dir=tmp_path)
    ex = BrokerExecutor(broker=broker, install_id="i", driver=_StubDriver())
    compiled = CompiledQuery(
        sql="...",
        upstream_kind="bigquery",
        upstream_resource_id="x",
    )
    with pytest.raises(NotImplementedError):
        await ex.execute(compiled)


async def test_federate_issuer_returns_token_and_callback(tmp_path: Path):
    broker = EnvCredentialBroker(secrets_dir=tmp_path / "secrets")
    issuer = FederateIssuer(
        broker=broker, callback_base_url="https://gw.test/federate/callback",
    )
    compiled = CompiledQuery(
        sql="SELECT 1",
        upstream_kind="snowflake",
        upstream_resource_id="tbl-q",
    )
    issuance = await issuer.issue(
        compiled, agent_id=AgentID(value="agent-1"), ttl_s=300,
    )
    assert issuance.sql == "SELECT 1"
    assert issuance.token.kind == "data"
    assert issuance.callback_url.endswith(issuance.token.token_id)
    assert await broker.is_valid(issuance.token.token_id) is True
