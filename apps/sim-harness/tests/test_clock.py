"""Tests for WallClock + VirtualClock."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from wormbase_sim_harness.clock import VirtualClock, WallClock


@pytest.mark.asyncio
async def test_virtual_clock_advances_without_waiting() -> None:
    clk = VirtualClock(start_dt=datetime(2026, 1, 1, tzinfo=UTC))
    await clk.start()
    t0 = time.monotonic()
    await clk.advance_to(0)
    await clk.advance_to(60)
    await clk.advance_to(3600)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1, f"VirtualClock should not wait; took {elapsed:.3f}s"
    assert clk.now() == datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=3600)


@pytest.mark.asyncio
async def test_virtual_clock_started_at_stable() -> None:
    start = datetime(2026, 4, 25, tzinfo=UTC)
    clk = VirtualClock(start_dt=start)
    await clk.start()
    await clk.advance_to(123)
    assert clk.started_at() == start


@pytest.mark.asyncio
async def test_wall_clock_waits_with_factor() -> None:
    """Use a tiny factor so the wait runs in milliseconds, not seconds.

    With ``monotonic_factor=0.001``, ``advance_to(1000)`` translates to
    a 1.0-second target — but each beat ``at`` of 100 means ~0.1s.
    """
    clk = WallClock(monotonic_factor=0.001)
    await clk.start()

    t0 = time.monotonic()
    await clk.advance_to(0)
    await clk.advance_to(50)
    await clk.advance_to(200)
    elapsed = time.monotonic() - t0
    # 200 * 0.001 = 0.2s target. Allow 50% slack for CI jitter.
    assert 0.1 < elapsed < 1.0, f"WallClock waited {elapsed:.3f}s (expected ~0.2s)"


@pytest.mark.asyncio
async def test_wall_clock_does_not_go_backwards() -> None:
    """advance_to with t < current target should be a no-op (no negative sleep)."""
    clk = WallClock(monotonic_factor=0.001)
    await clk.start()
    await clk.advance_to(100)  # ~0.1s
    t0 = time.monotonic()
    await clk.advance_to(1)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05


@pytest.mark.asyncio
async def test_wall_clock_started_at_set_by_start() -> None:
    clk = WallClock()
    await clk.start()
    assert isinstance(clk.started_at(), datetime)


def test_wall_clock_factor_must_be_positive() -> None:
    with pytest.raises(ValueError, match="monotonic_factor"):
        WallClock(monotonic_factor=0)
