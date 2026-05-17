"""Shared helper for the Optional-Effect Injection doctrine.

See ``docs/superpowers/specs/2026-05-21-optional-effect-injection-doctrine.md``
(Addendum 2, 2026-05-27).

This is a parallel copy of ``wormbase_core.optional_effect`` — the helper
also lives in ``apps/worm-core/src/wormbase_core/optional_effect.py``. The
duplicate exists because the ``wormbase-agent-gateway`` package does not
(and should not) depend on ``wormbase-core``: agent-gateway is a lower
layer in the dependency graph. The class surface is identical; the
agent-gateway copy is consumed at this package's tenancy adoption sites
(Case 7 LedgerQuotaTracker, Case 8 TenantEngineRegistry).

The forward path (Addendum 2 future): promote the helper to a shared
lower-level package (e.g. ``wormbase-common`` if introduced, or extend
``wormbase-reactivities`` if it makes sense there) and drop the
duplicate. Until then, the two files stay byte-identical at the public
surface — any change to one MUST be mirrored to the other. Tests pin
both copies independently.

See :mod:`wormbase_core.optional_effect` for the canonical docstring.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


__all__ = ["OptionalEffectGuard", "OptionalEffectAbsent"]


class OptionalEffectAbsent(RuntimeError):
    """Raised when :meth:`OptionalEffectGuard.use` is called on an absent guard.

    The doctrine's canonical Optional-Effect Injection shape supports two
    consumer-side patterns: graceful fallback (use :meth:`take_path`) and
    require-the-service (use :meth:`use`). This exception fires on the
    latter when the service was not injected — typically a wiring bug.
    """


class OptionalEffectGuard(Generic[T]):
    """Wrapper around an Optional-Effect Injection service.

    See :class:`wormbase_core.optional_effect.OptionalEffectGuard` for the
    full docstring; this is a parallel copy maintained byte-identical at
    the public surface.

    Public API:
      * :meth:`is_present` — bool query for presence.
      * :meth:`use` — raises if absent.
      * :meth:`take_path` — async dispatch with telemetry.
      * :meth:`metrics` — per-path counters dict.
      * :attr:`case_name` — stable case identifier.
    """

    __slots__ = (
        "_service",
        "_case_name",
        "_present_path_count",
        "_absent_path_count",
    )

    def __init__(self, case_name: str, service: T | None) -> None:
        self._service: T | None = service
        self._case_name = case_name
        self._present_path_count: int = 0
        self._absent_path_count: int = 0

    def is_present(self) -> bool:
        """Return True iff a service was injected (non-None)."""
        return self._service is not None

    def use(self) -> T:
        """Return the service. Raise :class:`OptionalEffectAbsent` if absent."""
        if self._service is None:
            raise OptionalEffectAbsent(
                f"OptionalEffect case {self._case_name!r} was accessed via "
                f"use() but no service was injected. Use take_path() for "
                f"fallback semantics, or ensure the env knob is set.",
            )
        return self._service

    async def take_path(
        self,
        *,
        with_present: Callable[[T], Awaitable[R]],
        without: Callable[[], Awaitable[R]],
    ) -> R:
        """Dispatch to the active path and record telemetry."""
        if self._service is not None:
            self._present_path_count += 1
            logger.debug(
                "optional_effect.path_taken",
                extra={
                    "case_name": self._case_name,
                    "path": "present",
                    "count": self._present_path_count,
                },
            )
            return await with_present(self._service)
        self._absent_path_count += 1
        logger.debug(
            "optional_effect.path_taken",
            extra={
                "case_name": self._case_name,
                "path": "absent",
                "count": self._absent_path_count,
            },
        )
        return await without()

    def take_path_sync(
        self,
        *,
        with_present: Callable[[T], R],
        without: Callable[[], R],
    ) -> R:
        """Synchronous counterpart of :meth:`take_path`.

        For boot-time / composition-time decisions where the dispatch
        is naturally synchronous. Same counter / DEBUG-log contract.
        """
        if self._service is not None:
            self._present_path_count += 1
            logger.debug(
                "optional_effect.path_taken",
                extra={
                    "case_name": self._case_name,
                    "path": "present",
                    "count": self._present_path_count,
                },
            )
            return with_present(self._service)
        self._absent_path_count += 1
        logger.debug(
            "optional_effect.path_taken",
            extra={
                "case_name": self._case_name,
                "path": "absent",
                "count": self._absent_path_count,
            },
        )
        return without()

    def metrics(self) -> dict[str, int]:
        """Return per-path counters: ``present_path_count``, ``absent_path_count``."""
        return {
            "present_path_count": self._present_path_count,
            "absent_path_count": self._absent_path_count,
        }

    @property
    def case_name(self) -> str:
        """The stable case identifier passed at construction."""
        return self._case_name
