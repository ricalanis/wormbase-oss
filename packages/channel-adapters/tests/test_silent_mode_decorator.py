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


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class _FakeSlackAdapter:
    platform = "slack-silent-mode-test"

    def __init__(self) -> None: ...

    async def authenticate(self, secrets):  # pragma: no cover
        return "h"

    async def install(self, handle):  # pragma: no cover
        return "i"

    def listen(self, handle):  # pragma: no cover
        return iter([])

    async def send(self, handle, channel, msg):  # pragma: no cover
        return "m"

    async def list_workspace_members(self, handle):  # pragma: no cover
        return []


@pytest.fixture
def _register_fake_adapter():
    """Register the fake adapter for the test, unregister after."""
    from wormbase_channel_adapters import registry as registry_mod

    reg = registry_mod.default_registry()
    reg.register(_FakeSlackAdapter)
    yield
    reg.unregister(_FakeSlackAdapter.platform)


@pytest.mark.asyncio
async def test_registry_wraps_adapter_under_silent_mode(
    monkeypatch: pytest.MonkeyPatch, _register_fake_adapter,
) -> None:
    monkeypatch.setenv("WORMBASE_SILENT_MODE", "1")
    from wormbase_channel_adapters import registry as registry_mod

    adapter = registry_mod.build_adapter(
        platform=_FakeSlackAdapter.platform,
        ledger=AsyncMock(),
        company_id=uuid4(),
    )
    assert isinstance(adapter, SilentModeChannelAdapter)


@pytest.mark.asyncio
async def test_registry_returns_raw_adapter_when_not_silent(
    monkeypatch: pytest.MonkeyPatch, _register_fake_adapter,
) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    from wormbase_channel_adapters import registry as registry_mod

    adapter = registry_mod.build_adapter(
        platform=_FakeSlackAdapter.platform,
        ledger=AsyncMock(),
        company_id=uuid4(),
    )
    assert not isinstance(adapter, SilentModeChannelAdapter)
    assert isinstance(adapter, _FakeSlackAdapter)


def test_build_adapter_raises_on_unknown_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WORMBASE_SILENT_MODE", raising=False)
    from wormbase_channel_adapters import registry as registry_mod

    with pytest.raises(KeyError):
        registry_mod.build_adapter(
            platform="not-a-real-platform",
            ledger=AsyncMock(),
            company_id=uuid4(),
        )
