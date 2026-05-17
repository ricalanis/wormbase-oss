"""StalenessSignalReactivity — fires when source has not been observed in N hours."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from wormbase_lake_maintainer.reactivities import StalenessSignalReactivity


def _ctx():
    """Minimal ReactivityContext for predicate/fire tests."""
    from wormbase_reactivities.protocol import ReactivityContext
    return ReactivityContext(
        ledger=AsyncMock(write=AsyncMock(return_value=None)),
        company_id=uuid4(),
        registry=MagicMock(),
        now=lambda: datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_staleness_predicate_matches_source_profiled_entries() -> None:
    src_mock = MagicMock()
    src_mock.id = uuid4()
    src_mock.staleness_signal = AsyncMock(
        return_value=MagicMock(stale=True, last_seen=None, sla_hours=24.0),
    )
    react = StalenessSignalReactivity(source=src_mock)
    entry = {"kind": "execute", "payload": {"tool": "emit_source_profiled"}}
    ctx = _ctx()
    assert await react.predicate.match(entry, ctx) is True


@pytest.mark.asyncio
async def test_staleness_predicate_skips_unrelated_entries() -> None:
    src_mock = MagicMock()
    src_mock.id = uuid4()
    src_mock.staleness_signal = AsyncMock()
    react = StalenessSignalReactivity(source=src_mock)
    entry = {"kind": "execute", "payload": {"tool": "emit_kpi_proposed"}}
    ctx = _ctx()
    assert await react.predicate.match(entry, ctx) is False


@pytest.mark.asyncio
async def test_staleness_fire_emits_when_stale() -> None:
    src_mock = MagicMock()
    src_mock.id = uuid4()
    src_mock.family = "external"
    src_mock.staleness_signal = AsyncMock(
        return_value=MagicMock(
            stale=True,
            last_seen=datetime.now(UTC) - timedelta(hours=48),
            sla_hours=24.0,
        ),
    )
    react = StalenessSignalReactivity(source=src_mock)
    entry = {"kind": "execute", "payload": {"tool": "emit_source_profiled"}}
    ctx = _ctx()
    result = await react.fire(entry, ctx)
    assert result.fired is True
    assert result.actions[0].action_kind == "source_staleness_signaled"
    # Verify ledger.write was called with the PEVR-cycle shape
    assert ctx.ledger.write.await_count == 1
    call_kwargs = ctx.ledger.write.await_args.kwargs
    assert call_kwargs["propose"]["target_kind"] == "source_staleness_signaled"
    assert "execute_fn" in call_kwargs
    assert "verify_fn" in call_kwargs
    assert "resolve_fn" in call_kwargs
    assert "timestamp" in call_kwargs
    assert "quadrant" in call_kwargs


@pytest.mark.asyncio
async def test_staleness_fire_returns_no_op_when_not_stale() -> None:
    src_mock = MagicMock()
    src_mock.id = uuid4()
    src_mock.family = "external"
    src_mock.staleness_signal = AsyncMock(
        return_value=MagicMock(
            stale=False,
            last_seen=datetime.now(UTC),
            sla_hours=24.0,
        ),
    )
    react = StalenessSignalReactivity(source=src_mock)
    entry = {"kind": "execute", "payload": {"tool": "emit_source_profiled"}}
    ctx = _ctx()
    result = await react.fire(entry, ctx)
    assert result.fired is False
    # No ledger.write when not stale
    assert ctx.ledger.write.await_count == 0
