"""Two-mode clock for the scenario engine.

WallClock — used for live demos. ``advance_to(t)`` actually sleeps until
``t`` seconds have elapsed since the run started, so the audience sees
real pacing.

VirtualClock — used for fast dashboard replays + tests. ``advance_to(t)``
returns immediately; ``now()`` returns ``start + t`` so downstream code
that asks "what time does the harness think it is?" still gets a
deterministic answer.
"""

from __future__ import annotations

import abc
import asyncio
import time
from datetime import UTC, datetime, timedelta


class Clock(abc.ABC):
    """Abstract clock; engines call ``advance_to`` once per beat."""

    @abc.abstractmethod
    async def start(self) -> None: ...

    @abc.abstractmethod
    async def advance_to(self, t_seconds: float) -> None: ...

    @abc.abstractmethod
    def now(self) -> datetime: ...

    @abc.abstractmethod
    def started_at(self) -> datetime: ...


class WallClock(Clock):
    """Real-time clock; sleeps the delta between beats.

    Optional ``monotonic_factor`` scales the wait. Tests set it to a tiny
    value to exercise the wait path without actually waiting seconds.
    Default is 1.0 (real wall-clock).
    """

    def __init__(self, *, monotonic_factor: float = 1.0) -> None:
        if monotonic_factor <= 0:
            raise ValueError("monotonic_factor must be > 0")
        self._factor = monotonic_factor
        self._start_mono: float | None = None
        self._start_dt: datetime | None = None

    async def start(self) -> None:
        self._start_mono = time.monotonic()
        self._start_dt = datetime.now(UTC)

    async def advance_to(self, t_seconds: float) -> None:
        if self._start_mono is None or self._start_dt is None:
            await self.start()
        assert self._start_mono is not None
        target = self._start_mono + (t_seconds * self._factor)
        delta = target - time.monotonic()
        if delta > 0:
            await asyncio.sleep(delta)

    def now(self) -> datetime:
        if self._start_dt is None:
            return datetime.now(UTC)
        elapsed = time.monotonic() - (self._start_mono or time.monotonic())
        # Translate elapsed (in scaled time) back to wall-clock terms.
        return self._start_dt + timedelta(seconds=elapsed / self._factor)

    def started_at(self) -> datetime:
        if self._start_dt is None:
            raise RuntimeError("WallClock.start() not called yet")
        return self._start_dt


class VirtualClock(Clock):
    """No-wait clock; ``now()`` follows the most recent ``advance_to``."""

    def __init__(self, start_dt: datetime | None = None) -> None:
        self._start_dt = start_dt
        self._cursor_seconds: float = 0.0

    async def start(self) -> None:
        if self._start_dt is None:
            self._start_dt = datetime.now(UTC)
        self._cursor_seconds = 0.0

    async def advance_to(self, t_seconds: float) -> None:
        if self._start_dt is None:
            await self.start()
        # Virtual clocks never go backwards — ScenarioEngine enforces
        # monotonic beats but a defensive max() also covers callers.
        self._cursor_seconds = max(self._cursor_seconds, float(t_seconds))

    def now(self) -> datetime:
        if self._start_dt is None:
            return datetime.now(UTC)
        return self._start_dt + timedelta(seconds=self._cursor_seconds)

    def started_at(self) -> datetime:
        if self._start_dt is None:
            raise RuntimeError("VirtualClock.start() not called yet")
        return self._start_dt


__all__ = ["Clock", "WallClock", "VirtualClock"]
