"""ChannelAdapter registry.

Mirrors :mod:`wormbase_lake_surfaces.registry` in shape: a global registry
plus a decorator for self-registration:

    @register_channel_adapter
    class MySlackAdapter:
        platform = "slack"
        ...

The dashboard's ``/channels`` page reads from :func:`default_registry`
to populate its install-platform picker, so adding a new channel
adapter is purely additive — no core code path changes.
"""

from __future__ import annotations

from typing import TypeVar

from .base import ChannelAdapter

A = TypeVar("A", bound=type)


class ChannelAdapterRegistry:
    """Holds the (platform -> ChannelAdapter class) map."""

    def __init__(self) -> None:
        self._by_platform: dict[str, type[ChannelAdapter]] = {}

    def register(self, cls: type[ChannelAdapter]) -> None:
        platform = getattr(cls, "platform", None)
        if not isinstance(platform, str) or not platform:
            raise ValueError(
                f"channel-adapter class {cls!r} must declare a "
                f"non-empty `platform` str"
            )
        if platform in self._by_platform:
            raise ValueError(
                f"channel-adapter {platform!r} already registered"
            )
        self._by_platform[platform] = cls

    def unregister(self, platform: str) -> None:
        self._by_platform.pop(platform, None)

    def get(self, platform: str) -> type[ChannelAdapter] | None:
        return self._by_platform.get(platform)

    def all_platforms(self) -> list[str]:
        return sorted(self._by_platform.keys())

    def __len__(self) -> int:
        return len(self._by_platform)

    def __contains__(self, platform: object) -> bool:
        return (
            isinstance(platform, str) and platform in self._by_platform
        )


_default = ChannelAdapterRegistry()


def register_channel_adapter(cls: A) -> A:
    """Decorator: register a ChannelAdapter class with the default registry."""
    _default.register(cls)  # type: ignore[arg-type]
    return cls


def default_registry() -> ChannelAdapterRegistry:
    """Return the process-wide default registry."""
    return _default


def build_adapter(
    *,
    platform: str,
    ledger: object,
    company_id: object,
) -> object:
    """Instantiate the registered adapter for ``platform``; optionally wrap.

    When ``WORMBASE_SILENT_MODE`` is on, returns a ``SilentModeChannelAdapter``
    wrapping the concrete adapter so its ``send()`` is gated. Otherwise
    returns the raw adapter instance.

    The adapter class is instantiated with no arguments — the
    self-registration contract is that adapters carry their config via
    classmethods / handles passed at call time, not at construction.

    Raises ``KeyError`` if no adapter is registered for ``platform``.
    """
    from wormbase_core import silent_mode
    from wormbase_channel_adapters.silent_mode import SilentModeChannelAdapter

    inner_cls = default_registry().get(platform)
    if inner_cls is None:
        raise KeyError(f"no channel adapter registered for platform={platform!r}")
    inner = inner_cls()
    if silent_mode.is_silent_mode_enabled():
        return SilentModeChannelAdapter(
            inner=inner, ledger=ledger, company_id=company_id  # type: ignore[arg-type]
        )
    return inner


__all__ = [
    "ChannelAdapterRegistry",
    "build_adapter",
    "default_registry",
    "register_channel_adapter",
]
