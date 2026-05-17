"""MCP integration payload tests (Phase 0 spike).

Per ``docs/superpowers/specs/2026-04-27-mcp-integration.md`` §10.1.
The new ``mcp_call_received`` payload must:

* construct from valid args,
* reject extras (Pydantic ``extra='forbid'`` on EntryPayload),
* round-trip via ``model_dump`` → ``model_validate`` byte-equivalently,
* enforce kind registration in ``KIND_REGISTRY``,
* enforce tz-aware ``started_at``,
* enforce outcome ∈ {ok, error, denied, timeout}.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from wormbase_ledger import entries as E

CALL_ID = UUID("0190a0a0-0000-7000-8000-0000000000d1")
TENANT_ID = UUID("0190a0a0-0000-7000-8000-0000000000d2")
PERSON_ID = UUID("0190a0a0-0000-7000-8000-0000000000d3")


def _valid_args() -> dict:
    return {
        "mcp_call_id": CALL_ID,
        "tenant_id": TENANT_ID,
        "caller_person_id": PERSON_ID,
        "tool_name": "query_ledger",
        "args_hash": "deadbeef" * 8,  # 64 hex chars (sha256)
        "client_ua": "claude-desktop/1.2.3",
        "started_at": datetime(2026, 4, 27, 14, 0, 0, tzinfo=UTC),
        "outcome": "ok",
        "latency_ms": 42,
    }


def test_mcp_call_received_constructs() -> None:
    p = E.MCPCallReceivedPayload(**_valid_args())
    assert p.kind == "mcp_call_received"
    assert p.kind in E.KIND_REGISTRY
    assert E.KIND_REGISTRY[p.kind] is E.MCPCallReceivedPayload
    assert p.tool_name == "query_ledger"
    assert p.outcome == "ok"
    assert p.latency_ms == 42
    assert p.caller_person_id == PERSON_ID


def test_mcp_call_received_rejects_extras() -> None:
    bad = {**_valid_args(), "not_allowed": True}
    with pytest.raises(ValidationError):
        E.MCPCallReceivedPayload(**bad)


def test_mcp_call_received_roundtrips() -> None:
    p = E.MCPCallReceivedPayload(**_valid_args())
    again = E.MCPCallReceivedPayload.model_validate(p.model_dump())
    assert again == p


def test_mcp_call_received_caller_person_optional() -> None:
    """Anonymous bearer-token callers (no resolvable Person) still audit."""
    args = _valid_args()
    args["caller_person_id"] = None
    p = E.MCPCallReceivedPayload(**args)
    assert p.caller_person_id is None


def test_mcp_call_received_started_at_must_be_tz_aware() -> None:
    args = _valid_args()
    args["started_at"] = datetime(2026, 4, 27, 14, 0, 0)  # naive
    with pytest.raises(ValidationError):
        E.MCPCallReceivedPayload(**args)


def test_mcp_call_received_outcome_validated() -> None:
    args = _valid_args()
    args["outcome"] = "explosion"  # not in the enum
    with pytest.raises(ValidationError):
        E.MCPCallReceivedPayload(**args)


@pytest.mark.parametrize("outcome", ["ok", "error", "denied", "timeout"])
def test_mcp_call_received_each_outcome_accepted(outcome: str) -> None:
    args = _valid_args()
    args["outcome"] = outcome
    p = E.MCPCallReceivedPayload(**args)
    assert p.outcome == outcome


def test_mcp_call_received_latency_ms_must_be_non_negative() -> None:
    args = _valid_args()
    args["latency_ms"] = -1
    with pytest.raises(ValidationError):
        E.MCPCallReceivedPayload(**args)
