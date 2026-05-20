# silent-mode: not-an-egress — package re-exports
"""WormBase ChannelAdapter Protocol + day-one channel adapters.

A ``ChannelAdapter`` is the only abstraction the channel-adapter
service knows about. Adding a new channel platform is a class
registration via ``@register_channel_adapter``; no core wire-handling
code ever changes.

Public surface:
    * Protocol:  :class:`ChannelAdapter`
    * Types:     :class:`InfraEvent`, :class:`OutMessage`,
                 :class:`MessageRef`, :class:`InstallRecord`,
                 :class:`ChannelRef`, :class:`PlatformMember`,
                 :class:`ChannelCap`, :class:`Platform`,
                 :class:`SecretBundle`, :class:`AuthHandle`
    * Registry:  :class:`ChannelAdapterRegistry`,
                 :func:`register_channel_adapter`,
                 :func:`default_registry`

Importing this package eagerly imports every shipped adapter so the
@register_channel_adapter decorators fire — the dashboard's /channels
picker can iterate ``default_registry().all_platforms()`` and surface
every connected-or-connectable platform.
"""

from __future__ import annotations

from .base import ChannelAdapter
from .registry import (
    ChannelAdapterRegistry,
    default_registry,
    register_channel_adapter,
)
from .types import (
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

# Eager imports — each module's @register_channel_adapter decorator
# runs at import time. Order: the production-grade Slack adapter first,
# then the preview WhatsApp adapter (Phase 3 of the 2026-05-05
# WhatsApp+provenance build), then the stub Discord/Teams skeletons.
from . import (  # noqa: F401
    slack,
    whatsapp,
    discord,
    teams,
)
from .whatsapp import WhatsAppChannelAdapter
from .whatsapp_rate_limit import (
    ExponentialBackoff,
    RateLimitTimeoutError,
    RateLimitedError,
    TokenBucketRateLimiter,
    with_whatsapp_rate_limit,
)

__all__ = [
    "AuthHandle",
    "ChannelAdapter",
    "ChannelAdapterRegistry",
    "ChannelCap",
    "ChannelRef",
    "ExponentialBackoff",
    "InfraEvent",
    "InstallRecord",
    "MessageRef",
    "OutMessage",
    "Platform",
    "PlatformMember",
    "RateLimitTimeoutError",
    "RateLimitedError",
    "SecretBundle",
    "TokenBucketRateLimiter",
    "WhatsAppChannelAdapter",
    "default_registry",
    "register_channel_adapter",
    "with_whatsapp_rate_limit",
]
