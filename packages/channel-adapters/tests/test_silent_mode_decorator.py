"""SilentModeChannelAdapter wraps an inner adapter and intercepts send().

All non-send methods (authenticate, install, listen, list_workspace_members)
pass through unchanged. send() never touches the inner adapter when silent
mode is on; it records reply_suppressed and returns a synthetic MessageRef.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from wormbase_channel_adapters.base import ChannelAdapter
from wormbase_channel_adapters.silent_mode import SilentModeChannelAdapter
from wormbase_core import silent_mode


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    silent_mode._reset_for_tests()
    yield
    silent_mode._reset_for_tests()


def _fake_inner() -> MagicMock:
    inner = MagicMock(spec=ChannelAdapter)
    inner.authenticate = AsyncMock(return_value="handle")
    inner.install = AsyncMock(return_value="install")
    inner.list_workspace_members = AsyncMock(return_value=[])
    inner.send = AsyncMock(return_value="real-msg-ref")
    inner.listen = MagicMock(return_value=iter([]))
    return inner


@pytest.mark.asyncio
async def test_send_suppressed_when_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    inner = _fake_inner()
    ledger = AsyncMock()
    company_id = uuid4()
    adapter = SilentModeChannelAdapter(
        inner=inner, ledger=ledger, company_id=company_id
    )
    result = await adapter.send(
        handle="h",
        channel={"platform_channel_id": "C123"},
        msg={"text": "hello"},
    )
    inner.send.assert_not_called()
    ledger.write.assert_awaited_once()
    assert ledger.write.await_args.kwargs["propose"]["target_kind"] == "reply_suppressed"
    # Result has the MessageRef-ish shape downstream callers expect.
    assert getattr(result, "suppressed", False) is True


@pytest.mark.asyncio
async def test_send_passthrough_when_not_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    inner = _fake_inner()
    adapter = SilentModeChannelAdapter(
        inner=inner, ledger=AsyncMock(), company_id=uuid4()
    )
    result = await adapter.send(handle="h", channel={"id": "C"}, msg={"text": "x"})
    assert result == "real-msg-ref"
    inner.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_send_methods_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    inner = _fake_inner()
    adapter = SilentModeChannelAdapter(
        inner=inner, ledger=AsyncMock(), company_id=uuid4()
    )
    assert await adapter.authenticate("secrets") == "handle"  # passthrough
    inner.authenticate.assert_awaited_once_with("secrets")
    assert await adapter.list_workspace_members("h") == []
    inner.list_workspace_members.assert_awaited_once()
