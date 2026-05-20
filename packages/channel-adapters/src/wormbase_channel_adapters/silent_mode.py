"""SilentModeChannelAdapter — wraps an inner ChannelAdapter and gates send().

When WORMBASE_SILENT_MODE is on, send() never touches the inner adapter;
it records reply_suppressed and returns a SuppressedResult. All other
Protocol methods pass through.

The decorator is applied in the adapter registry (registry.py) when the
env var is set at boot. The same decorator handles every concrete
adapter (slack, whatsapp, discord, teams) without per-adapter changes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from wormbase_core import silent_mode

from wormbase_channel_adapters.base import ChannelAdapter


class SilentModeChannelAdapter:
    """Wrap an inner ChannelAdapter; intercept send() under silent mode."""

    def __init__(
        self,
        *,
        inner: ChannelAdapter,
        ledger: Any,
        company_id: UUID,
    ) -> None:
        self._inner = inner
        self._ledger = ledger
        self._company_id = company_id

    # ---- intercepted ------------------------------------------------------

    async def send(
        self,
        handle: Any,
        channel: Any,
        msg: Any,
    ) -> Any:
        if silent_mode.is_silent_mode_enabled():
            await silent_mode.record_suppressed(
                self._ledger,
                company_id=self._company_id,
                surface="chat",
                tool=f"{type(self._inner).__name__}.send",
                args={"channel": _to_jsonable(channel), "msg": _to_jsonable(msg)},
                channel_id=_extract_channel_id(channel),
                presence_reason="channel_egress",
            )
            return silent_mode.SuppressedResult.new()
        return await self._inner.send(handle, channel, msg)

    # ---- passthroughs -----------------------------------------------------

    async def authenticate(self, secrets: Any) -> Any:
        return await self._inner.authenticate(secrets)

    async def install(self, handle: Any) -> Any:
        return await self._inner.install(handle)

    def listen(self, handle: Any) -> Any:
        return self._inner.listen(handle)

    async def list_workspace_members(self, handle: Any) -> Any:
        return await self._inner.list_workspace_members(handle)


def _extract_channel_id(channel: Any) -> str | None:
    if isinstance(channel, dict):
        for k in ("platform_channel_id", "channel_id", "id"):
            if k in channel:
                return str(channel[k])
        return None
    for attr in ("platform_channel_id", "channel_id", "id"):
        if hasattr(channel, attr):
            return str(getattr(channel, attr))
    return None


def _to_jsonable(value: Any) -> Any:
    """Best-effort coercion so the ledger payload survives JSON encoding."""
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


__all__ = ["SilentModeChannelAdapter"]
