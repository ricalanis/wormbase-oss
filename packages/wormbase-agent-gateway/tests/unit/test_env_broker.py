"""EnvCredentialBroker impl-specific tests.

Protocol-conformance is covered in test_credential_broker_protocol.py. This
module covers behavior unique to the file-backed broker (persistence to disk,
fresh-dir bootstrap, missing-secret error).
"""
from __future__ import annotations

import pytest

from wormbase_agent_gateway.credential_broker import (
    DataScope,
    EnvCredentialBroker,
)


@pytest.mark.asyncio
async def test_init_creates_tokens_and_revoked_files(tmp_path) -> None:
    broker = EnvCredentialBroker(secrets_dir=tmp_path)
    assert (tmp_path / "_tokens.json").exists()
    assert (tmp_path / "_revoked.json").exists()
    # broker still usable
    assert broker.kind == "env"


@pytest.mark.asyncio
async def test_hold_data_account_raises_on_missing_secret(tmp_path) -> None:
    broker = EnvCredentialBroker(secrets_dir=tmp_path)
    with pytest.raises(KeyError):
        await broker.hold_data_account("nope", upstream_kind="snowflake")


@pytest.mark.asyncio
async def test_token_state_persists_across_broker_instances(tmp_path) -> None:
    """File-store brokers should see each other's tokens through the directory."""
    b1 = EnvCredentialBroker(secrets_dir=tmp_path)
    token = await b1.issue_data_token(
        agent_id="agent-1",
        scope=DataScope(resource_id="r"),
        ttl_s=600,
    )
    # Fresh broker instance pointing at same dir
    b2 = EnvCredentialBroker(secrets_dir=tmp_path)
    assert await b2.is_valid(token.token_id) is True
    await b2.revoke(token.token_id)
    # Original broker also sees the revocation (since both read JSON files)
    assert await b1.is_valid(token.token_id) is False
