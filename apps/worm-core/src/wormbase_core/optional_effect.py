"""Shared helper for the Optional-Effect Injection doctrine.

See ``docs/superpowers/specs/2026-05-21-optional-effect-injection-doctrine.md``
(Addendum 2, 2026-05-27).

The Optional-Effect Injection pattern accepts ``T | None`` as a dependency
where ``None`` is the default-OFF fallback path and a present ``T`` flips
into the with-service path. The doctrine has 10 rules. Rule 9 says:

  "Production observability MUST be able to answer 'what fraction of fires
  hit the with-service path vs the fallback path?'"

The 2026-05-27 maintenance audit found 6 of the 8 in-flight cases fail
Rule 9 (no path-distinguishing counter / log). To make Rule 9 compliance
uniform across NEW cases without forcing a full retrofit of the 8, this
module supplies :class:`OptionalEffectGuard` — a small wrapper that:

- Holds the ``T | None`` reference.
- Exposes :meth:`is_present` for direct branching.
- Exposes :meth:`use` for the require-the-service contract (raises if
  absent — for code paths that have no fallback semantics).
- Exposes :meth:`take_path` for the doctrine's canonical "branch + record"
  shape: each call dispatches to ``with_present`` or ``without`` AND
  ticks a per-path counter, satisfying Rule 9 uniformly.
- Exposes :meth:`metrics` returning per-path counters for inspection.

The guard is async-friendly: :meth:`take_path` accepts ``Awaitable``-returning
callables and itself returns the awaited result. Callers that need a
sync surface can compose around :meth:`is_present` directly.

Adoption policy (Addendum 2):

- New Optional-Effect cases (the 9th + onwards) MUST use the guard.
- Existing cases MAY migrate at their own cadence; not required in one sweep.
- The 2 pilot adoptions for Addendum 2 are LedgerQuotaTracker (Case 7
  composition decision) and TenantEngineRegistry (Case 8 wired into
  ``InMemoryTenantRouter``).
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

    Implements the Optional-Effect Injection doctrine (see
    ``docs/superpowers/specs/2026-05-21-optional-effect-injection-doctrine.md``).
    Default ``None`` = fallback path; injected ``T`` = effect-present path.

    Provides telemetry for which path was taken (Rule 9: telemetry
    distinguishes paths) so per-case audit visibility is uniform.

    The guard records two counters (``present_path_count`` and
    ``absent_path_count``) on every :meth:`take_path` call and emits a
    DEBUG-level log record per dispatch. The counters are accessible via
    :meth:`metrics` for inspection / dashboard surfaces; the log line is
    keyed by ``case_name`` so a single guard's telemetry is filterable.

    Usage::

        guard = OptionalEffectGuard[FooService]("foo", service)

        # Conditional dispatch — both paths satisfy the same external
        # contract:
        result = await guard.take_path(
            with_present=lambda svc: svc.do_thing(...),
            without=lambda: fallback_thing(...),
        )

        # Or query presence directly:
        if guard.is_present():
            await guard.use().do_thing(...)

    The two callables passed to :meth:`take_path` MUST return the same
    type ``R`` — the doctrine's external-contract invariant says both
    paths must satisfy the same contract.
    """

    __slots__ = (
        "_service",
        "_case_name",
        "_present_path_count",
        "_absent_path_count",
    )

    def __init__(self, case_name: str, service: T | None) -> None:
        """Initialize the guard.

        :param case_name: Stable identifier for this Optional-Effect case
            (e.g. ``"tenant_engine_registry"``, ``"ledger_quota_tracker"``).
            Appears in the DEBUG log emission and is recommended to match
            the doctrine's case-name convention.
        :param service: The service instance or ``None``. The guard's
            behavior is determined entirely by the truthiness of this
            argument — ``is_present()`` returns ``service is not None``.
        """
        self._service: T | None = service
        self._case_name = case_name
        self._present_path_count: int = 0
        self._absent_path_count: int = 0

    def is_present(self) -> bool:
        """Return True iff a service was injected (non-None)."""
        return self._service is not None

    def use(self) -> T:
        """Return the service. Raise :class:`OptionalEffectAbsent` if absent.

        For code paths that REQUIRE the service (e.g. Shape B routing
        that has no Shape A fallback). Use :meth:`take_path` for
        graceful fallback semantics.

        Does NOT increment any counter — :meth:`use` is a low-level
        accessor for callers that handle telemetry themselves.
        """
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
        """Dispatch to the active path and record telemetry.

        :param with_present: Async callable invoked with the service
            instance when one is present. Returns the contract type ``R``.
        :param without: Async callable invoked with no arguments when no
            service is present. Returns the contract type ``R``.
        :return: The value returned by whichever callable was dispatched.

        Increments the appropriate per-path counter and emits a DEBUG
        log record keyed by ``case_name``. The two callables MUST
        return the same type ``R`` — the doctrine's external-contract
        invariant.
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
        is naturally synchronous (e.g. constructing a wrapper service).
        Same counter / DEBUG-log contract as :meth:`take_path`, minus
        the async surface. The two callables MUST return the same type.
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
        """Return the per-path counters for inspection / dashboard surfaces.

        :returns: A new dict with two keys:
            ``present_path_count`` — number of :meth:`take_path` (or
            :meth:`take_path_sync`) calls that dispatched to the
            with-present callable.
            ``absent_path_count`` — number of :meth:`take_path` (or
            :meth:`take_path_sync`) calls that dispatched to the
            without callable.

        The dict is freshly allocated on each call; consumers may
        retain it without affecting the guard's internal state.
        """
        return {
            "present_path_count": self._present_path_count,
            "absent_path_count": self._absent_path_count,
        }

    @property
    def case_name(self) -> str:
        """The stable case identifier passed at construction."""
        return self._case_name
