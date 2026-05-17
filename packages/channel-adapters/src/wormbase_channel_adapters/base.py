"""The :class:`ChannelAdapter` Protocol.

Every channel platform WormBase supports implements this Protocol.
The registry binds a ``platform`` string to a ChannelAdapter class;
the channel-adapter service looks adapters up by platform and calls
the methods declared here.

Per PRD §3.1. The Protocol is ``runtime_checkable`` so tests can use
``isinstance(a, ChannelAdapter)`` to assert structural conformance.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from .types import (
    AdapterStatus,
    AuthHandle,
    ChannelCap,
    ChannelRef,
    InfraEvent,
    InstallRecord,
    MessageRef,
    OutMessage,
    Platform,
    PlatformMember,
    SecretBundle,
)


@runtime_checkable
class ChannelAdapter(Protocol):
    """A pluggable channel-platform adapter.

    Implementations register themselves via
    :func:`register_channel_adapter` and live in
    :mod:`wormbase_channel_adapters.<platform>`.

    Capability-honesty: every adapter declares ``status`` and
    ``status_note`` so the dashboard's channels tab can render an
    accurate badge ("production" / "preview" / "coming_soon") + a short
    user-facing note. Stub-but-real adapters whose install + listen
    paths are wired but whose send/file_upload remain skeletal are
    "preview" — admins can connect them and the worm will lurk, just
    not yet reply.
    """

    platform: Platform
    capability: set[ChannelCap]
    status: AdapterStatus
    status_note: str

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle: ...

    async def install(self, handle: AuthHandle) -> InstallRecord: ...

    def listen(self, handle: AuthHandle) -> AsyncIterator[InfraEvent]: ...

    async def send(
        self,
        handle: AuthHandle,
        channel: ChannelRef,
        msg: OutMessage,
    ) -> MessageRef: ...

    async def list_workspace_members(
        self, handle: AuthHandle
    ) -> list[PlatformMember]: ...


__all__ = ["ChannelAdapter"]
