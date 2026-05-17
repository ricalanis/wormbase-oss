"""Unit tests for :class:`wormbase_core.optional_effect.OptionalEffectGuard`.

Polish Wave 2 #3 (Addendum 2 to the Optional-Effect Injection doctrine).
The guard is shared infrastructure consumed by adopted Optional-Effect
Injection cases (initially Case 7 LedgerQuotaTracker composition + Case 8
TenantEngineRegistry routing). These tests pin its contract.
"""
from __future__ import annotations

import logging

import pytest

from wormbase_core.optional_effect import (
    OptionalEffectAbsent,
    OptionalEffectGuard,
)


class _FakeService:
    """Tiny test-double — the guard treats it as opaque ``T``."""

    def __init__(self, label: str) -> None:
        self.label = label

    async def do_thing(self, x: int) -> str:
        return f"{self.label}:{x}"


# ---------------------------------------------------------------------------
# is_present / use
# ---------------------------------------------------------------------------


def test_guard_with_service_is_present():
    """When a service is injected, :meth:`is_present` returns True."""
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", _FakeService("svc"),
    )
    assert guard.is_present() is True


def test_guard_without_service_is_not_present():
    """When no service is injected, :meth:`is_present` returns False."""
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", None,
    )
    assert guard.is_present() is False


def test_use_returns_service_when_present():
    """:meth:`use` returns the injected service identity."""
    svc = _FakeService("svc")
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", svc,
    )
    assert guard.use() is svc


def test_use_raises_when_absent():
    """:meth:`use` raises :class:`OptionalEffectAbsent` when no service."""
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", None,
    )
    with pytest.raises(OptionalEffectAbsent) as exc_info:
        guard.use()
    # The case_name appears in the message so failures are debuggable.
    assert "test_case" in str(exc_info.value)


def test_use_does_not_tick_counter():
    """:meth:`use` is a raw accessor — it does NOT bump :meth:`metrics`.

    Telemetry is the contract of :meth:`take_path`; callers using
    :meth:`use` are expected to record their own telemetry.
    """
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", _FakeService("svc"),
    )
    guard.use()
    guard.use()
    metrics = guard.metrics()
    assert metrics == {"present_path_count": 0, "absent_path_count": 0}


# ---------------------------------------------------------------------------
# take_path — async dispatch + counter ticks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_path_present_dispatches_with_present():
    """When present, :meth:`take_path` invokes the with_present callable."""
    svc = _FakeService("svc")
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", svc,
    )

    async def _with(svc_arg: _FakeService) -> str:
        return await svc_arg.do_thing(42)

    async def _without() -> str:
        raise AssertionError("should not be called when service is present")

    result = await guard.take_path(with_present=_with, without=_without)
    assert result == "svc:42"
    assert guard.metrics() == {
        "present_path_count": 1, "absent_path_count": 0,
    }


@pytest.mark.asyncio
async def test_take_path_absent_dispatches_without():
    """When absent, :meth:`take_path` invokes the without callable."""
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", None,
    )

    async def _with(svc_arg: _FakeService) -> str:
        raise AssertionError("should not be called when service is absent")

    async def _without() -> str:
        return "fallback"

    result = await guard.take_path(with_present=_with, without=_without)
    assert result == "fallback"
    assert guard.metrics() == {
        "present_path_count": 0, "absent_path_count": 1,
    }


@pytest.mark.asyncio
async def test_take_path_counters_accumulate_over_repeated_calls():
    """Counters accumulate across many dispatches."""
    svc = _FakeService("svc")
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", svc,
    )

    async def _with(svc_arg: _FakeService) -> int:
        return 1

    async def _without() -> int:
        return 0

    for _ in range(5):
        await guard.take_path(with_present=_with, without=_without)
    assert guard.metrics() == {
        "present_path_count": 5, "absent_path_count": 0,
    }

    # Swap to absent guard; counters are independent per-guard.
    absent_guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", None,
    )
    for _ in range(3):
        await absent_guard.take_path(with_present=_with, without=_without)
    assert absent_guard.metrics() == {
        "present_path_count": 0, "absent_path_count": 3,
    }


@pytest.mark.asyncio
async def test_take_path_logs_at_debug_level(caplog):
    """:meth:`take_path` emits a DEBUG ``optional_effect.path_taken`` log.

    The log record carries ``case_name``, ``path``, and ``count`` in
    its extra dict — keys downstream telemetry collectors can filter
    on.
    """
    caplog.set_level(logging.DEBUG, logger="wormbase_core.optional_effect")
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "my_case", _FakeService("svc"),
    )

    async def _with(svc_arg: _FakeService) -> str:
        return "ok"

    async def _without() -> str:
        return "fallback"

    await guard.take_path(with_present=_with, without=_without)

    # Find the log record we emitted.
    matching = [
        r for r in caplog.records
        if r.getMessage() == "optional_effect.path_taken"
    ]
    assert len(matching) == 1
    record = matching[0]
    assert record.case_name == "my_case"
    assert record.path == "present"
    assert record.count == 1


# ---------------------------------------------------------------------------
# take_path_sync — sync counterpart for boot-time / composition decisions
# ---------------------------------------------------------------------------


def test_take_path_sync_present_dispatches_with_present():
    """Sync variant: when present, invokes the with_present callable."""
    svc = _FakeService("svc")
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", svc,
    )
    result = guard.take_path_sync(
        with_present=lambda s: f"wrapped:{s.label}",
        without=lambda: "fallback",
    )
    assert result == "wrapped:svc"
    assert guard.metrics() == {
        "present_path_count": 1, "absent_path_count": 0,
    }


def test_take_path_sync_absent_dispatches_without():
    """Sync variant: when absent, invokes the without callable."""
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", None,
    )
    result = guard.take_path_sync(
        with_present=lambda s: "should_not_fire",
        without=lambda: "fallback",
    )
    assert result == "fallback"
    assert guard.metrics() == {
        "present_path_count": 0, "absent_path_count": 1,
    }


# ---------------------------------------------------------------------------
# metrics() shape + isolation
# ---------------------------------------------------------------------------


def test_metrics_returns_fresh_dict_each_call():
    """:meth:`metrics` returns a new dict per call — mutating it is safe."""
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "test_case", _FakeService("svc"),
    )
    snap_1 = guard.metrics()
    snap_1["mutated"] = 999  # type: ignore[assignment]
    snap_2 = guard.metrics()
    assert "mutated" not in snap_2
    assert snap_2 == {"present_path_count": 0, "absent_path_count": 0}


def test_case_name_property_exposes_construction_arg():
    """The ``case_name`` is preserved as a read-only property."""
    guard: OptionalEffectGuard[_FakeService] = OptionalEffectGuard(
        "specific_case_name", _FakeService("svc"),
    )
    assert guard.case_name == "specific_case_name"
