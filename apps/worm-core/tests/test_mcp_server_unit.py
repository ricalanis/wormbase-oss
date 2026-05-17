"""Unit tests for the MCP server module (Phase 0 spike).

End-to-end Streamable HTTP integration is in test_mcp_server_e2e.py;
this file covers the cheap deterministic bits: helpers, env-gating,
the build_mcp_server factory.
"""

from __future__ import annotations

import pytest
from wormbase_core.mcp_server import (
    DEFAULT_MCP_PORT,
    MCP_TOOL_NAME,
    _canonical_args_hash,
    build_mcp_server,
    is_mcp_enabled,
    read_mcp_port,
)
from wormbase_ledger import InMemoryLedger


def test_canonical_args_hash_is_stable() -> None:
    """Sorted-keys + no-whitespace produce identical hashes regardless of dict order."""
    a = {"company_id": "baseworm", "limit": 10, "since": None}
    b = {"limit": 10, "since": None, "company_id": "baseworm"}
    assert _canonical_args_hash(a) == _canonical_args_hash(b)
    assert len(_canonical_args_hash(a)) == 64  # sha256 hex


def test_canonical_args_hash_distinguishes_values() -> None:
    a = {"company_id": "baseworm", "limit": 10}
    c = {"company_id": "baseworm", "limit": 11}
    assert _canonical_args_hash(a) != _canonical_args_hash(c)


def test_is_mcp_enabled_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORMBASE_MCP_ENABLED", raising=False)
    assert is_mcp_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "ON"])
def test_is_mcp_enabled_truthy(
    value: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_MCP_ENABLED", value)
    assert is_mcp_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "", "no"])
def test_is_mcp_enabled_falsy(
    value: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_MCP_ENABLED", value)
    assert is_mcp_enabled() is False


def test_read_mcp_port_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORMBASE_MCP_PORT", raising=False)
    assert read_mcp_port() == DEFAULT_MCP_PORT


def test_read_mcp_port_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORMBASE_MCP_PORT", "12345")
    assert read_mcp_port() == 12345


def test_read_mcp_port_invalid_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_MCP_PORT", "not-an-int")
    assert read_mcp_port() == DEFAULT_MCP_PORT


def test_build_mcp_server_requires_token() -> None:
    ledger = InMemoryLedger()
    with pytest.raises(ValueError, match="api_token must be non-empty"):
        build_mcp_server(ledger=ledger, api_token="")


def test_build_mcp_server_registers_tool() -> None:
    """The single MCP tool, query_ledger, registers under the canonical name."""
    import asyncio

    ledger = InMemoryLedger()
    server = build_mcp_server(ledger=ledger, api_token="dev-token")
    tools = asyncio.run(server.list_tools())
    tool_names = [t.name for t in tools]
    assert MCP_TOOL_NAME in tool_names
    assert MCP_TOOL_NAME == "query_ledger"
