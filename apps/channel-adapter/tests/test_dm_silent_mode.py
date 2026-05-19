"""send_resource_conversation_dm short-circuits under silent mode.

The sender's open_dm / send_dm MUST NOT be called. A reply_suppressed
ledger entry is recorded (when ledger+company_id are provided) and a
DMRef with synthetic ids is returned so callers expecting a DMRef do
not crash.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from wormbase_channel_adapter import dm
from wormbase_core import silent_mode


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


@pytest.mark.asyncio
async def test_dm_suppressed_when_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    sender = AsyncMock()
    sender.open_dm = AsyncMock()
    sender.send_dm = AsyncMock()
    sender.platform = "slack"
    ledger = AsyncMock()
    ref = await dm.send_resource_conversation_dm(
        sender,
        owner_platform_id="U123",
        topic={"id": "t1"},
        statement={"text": "hi", "speaker_label": "ana", "channel_label": "#x", "ts": None},
        resources={"items": []},
        ledger=ledger,
        company_id=uuid4(),
    )
    sender.open_dm.assert_not_called()
    sender.send_dm.assert_not_called()
    ledger.write.assert_awaited_once()
    assert ledger.write.await_args.kwargs["propose"]["target_kind"] == "reply_suppressed"
    # Caller still gets a DMRef-shaped object.
    assert ref.platform == "slack"
    assert ref.platform_channel_id.startswith("suppressed:")
    assert ref.platform_message_id.startswith("suppressed:")


@pytest.mark.asyncio
async def test_dm_passthrough_when_not_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    sender = AsyncMock()
    sender.open_dm = AsyncMock(return_value="D456")
    sender.send_dm = AsyncMock(return_value="M789")
    sender.platform = "slack"
    ref = await dm.send_resource_conversation_dm(
        sender,
        owner_platform_id="U123",
        topic={"id": "t1"},
        statement={"text": "hi", "speaker_label": "ana", "channel_label": "#x", "ts": None},
        resources={"items": []},
        ledger=None,
        company_id=None,
    )
    assert ref.platform_channel_id == "D456"
    assert ref.platform_message_id == "M789"


@pytest.mark.asyncio
async def test_dm_suppressed_without_ledger_still_returns_synthetic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If silent mode is on but ledger or company_id is missing, the send is
    still suppressed (no real network call) and a synthetic DMRef is
    returned. The ledger receives no write — only the egress invariant is
    load-bearing here, trigger capture is best-effort."""
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    sender = AsyncMock()
    sender.open_dm = AsyncMock()
    sender.send_dm = AsyncMock()
    sender.platform = "slack"
    ledger = AsyncMock()
    ref = await dm.send_resource_conversation_dm(
        sender,
        owner_platform_id="U123",
        topic={"id": "t1"},
        statement={"text": "hi", "speaker_label": "ana", "channel_label": "#x", "ts": None},
        resources={"items": []},
        ledger=ledger,
        company_id=None,
    )
    sender.open_dm.assert_not_called()
    sender.send_dm.assert_not_called()
    ledger.write.assert_not_called()
    assert ref.platform_channel_id.startswith("suppressed:")
