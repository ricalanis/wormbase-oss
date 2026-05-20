"""record_suppressed writes a reply_suppressed ledger entry.

Failure-path: if the ledger raises, the call MUST NOT re-raise and MUST
log ERROR with the full payload. The invariant "no outbound" outranks
trigger-capture completeness.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from wormbase_core import silent_mode


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


@pytest.mark.asyncio
async def test_record_suppressed_writes_ledger_entry() -> None:
    ledger = AsyncMock()
    company_id = uuid4()
    await silent_mode.record_suppressed(
        ledger,
        company_id=company_id,
        surface="chat",
        tool="channel_adapter.send",
        args={"channel_id": "C123", "text": "hi"},
        channel_id="C123",
        presence_reason="dm_always_respond",
    )
    ledger.write.assert_awaited_once()
    call = ledger.write.await_args.kwargs
    assert call["company_id"] == company_id
    assert call["propose"]["target_kind"] == "reply_suppressed"
    execute_payload = call["execute_fn"]()
    assert execute_payload["tool"] == "channel_adapter.send"
    assert execute_payload["args"]["surface"] == "chat"
    assert execute_payload["args"]["presence_reason"] == "dm_always_respond"
    assert execute_payload["args"]["silent_mode_source"] == "env"
    assert execute_payload["args"]["channel_id"] == "C123"
    UUID(execute_payload["args"]["ref_id"])  # parseable uuid4


@pytest.mark.asyncio
async def test_record_suppressed_ledger_failure_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ledger = AsyncMock()
    ledger.write.side_effect = RuntimeError("ledger down")
    with caplog.at_level(logging.ERROR, logger="wormbase_core.silent_mode"):
        await silent_mode.record_suppressed(
            ledger,
            company_id=uuid4(),
            surface="mcp_write",
            tool="record_decision",
            args={"k": "v"},
            presence_reason="mcp_invocation",
        )
    assert any("record_suppressed failed" in r.message for r in caplog.records)


def test_suppressed_result_shape() -> None:
    r = silent_mode.SuppressedResult.new()
    assert r.ok is True
    assert r.suppressed is True
    UUID(str(r.ref_id))


def test_suppressed_tool_result_shape() -> None:
    r = silent_mode.SuppressedToolResult.new()
    assert r.ok is True
    assert r.suppressed is True
    UUID(str(r.ref_id))
