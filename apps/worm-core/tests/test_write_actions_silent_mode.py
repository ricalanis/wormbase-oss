"""Silent mode short-circuits _pevr before the real ledger.write fires.

Picks one representative caller (`record_decision`) because all PEVR
write tools fan through the same helper — a green test here certifies
the whole family.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from wormbase_core import silent_mode, write_actions


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


@pytest.mark.asyncio
async def test_pevr_short_circuits_when_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    ledger = AsyncMock()
    company_id = uuid4()

    # Use the lowest-level test target: _pevr itself, with a fake payload class.
    class _StubPayload:
        def __init__(self, **_kwargs: object) -> None: ...

    result = await write_actions._pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="decision_recorded",
        ref_id=uuid4(),
        reason="t",
        proposed_by="test",
        tool="record_decision",
        args={"k": "v"},
        result_ref="r",
        payload_cls=_StubPayload,
        rationale="t",
    )
    # Exactly one ledger.write — for the reply_suppressed entry, not the real one.
    assert ledger.write.await_count == 1
    suppressed_call = ledger.write.await_args.kwargs
    assert suppressed_call["propose"]["target_kind"] == "reply_suppressed"
    # Caller gets a SuppressedToolResult.
    assert isinstance(result, silent_mode.SuppressedToolResult)
    assert result.ok is True and result.suppressed is True
    UUID(str(result.ref_id))


@pytest.mark.asyncio
async def test_pevr_passthrough_when_not_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    ledger = AsyncMock()
    ledger.write.return_value = "ok"
    company_id = uuid4()

    class _StubPayload:
        def __init__(self, **_kwargs: object) -> None: ...

    result = await write_actions._pevr(
        ledger=ledger,
        company_id=company_id,
        target_kind="decision_recorded",
        ref_id=uuid4(),
        reason="t",
        proposed_by="test",
        tool="record_decision",
        args={"k": "v"},
        result_ref="r",
        payload_cls=_StubPayload,
        rationale="t",
    )
    assert result == "ok"
    real_call = ledger.write.await_args.kwargs
    assert real_call["propose"]["target_kind"] == "decision_recorded"
