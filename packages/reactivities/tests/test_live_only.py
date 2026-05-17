"""Tests for the LiveOnly Reactivity condition.

LiveOnly reads delivery_mode + platform_ts off entry.payload.args and
allows only push-delivered, fresh events. Permissive when fields are
missing — back-compat for pre-provenance entries replayed through the
runner.

The freshness window is configurable via WORMBASE_FRESHNESS_WINDOW_S
(60s default) so operators can tighten/loosen for noisy networks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest

from wormbase_reactivities.conditions import (
    DomainEnabled,
    LiveOnly,
    NotRecentlyFired,
)
from wormbase_reactivities.protocol import ReactivityContext


def _ctx() -> ReactivityContext:
    """Build a synthetic context with no registry (LiveOnly is read-only)."""
    return ReactivityContext(
        ledger=None,
        company_id=uuid4(),
        registry=None,
        now=datetime.now(timezone.utc),
        extras={"reactivity_id": "test"},
    )


def _entry(*, args: dict[str, Any], ts: datetime | None = None) -> dict[str, Any]:
    return {
        "kind": "execute",
        "ts": ts or datetime.now(timezone.utc),
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
        },
    }


@pytest.mark.asyncio
async def test_push_with_recent_platform_ts_allowed() -> None:
    cond = LiveOnly()
    now = datetime.now(timezone.utc)
    entry = _entry(
        args={
            "delivery_mode": "push",
            "platform_ts": (now - timedelta(seconds=5)).isoformat(),
        },
        ts=now,
    )
    assert await cond.allows(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_push_with_stale_platform_ts_blocked() -> None:
    cond = LiveOnly()
    now = datetime.now(timezone.utc)
    entry = _entry(
        args={
            "delivery_mode": "push",
            "platform_ts": (now - timedelta(seconds=120)).isoformat(),
        },
        ts=now,
    )
    assert await cond.allows(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_history_sync_blocked() -> None:
    cond = LiveOnly()
    now = datetime.now(timezone.utc)
    entry = _entry(
        args={
            "delivery_mode": "history_sync",
            "platform_ts": now.isoformat(),
        },
        ts=now,
    )
    assert await cond.allows(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_history_sync_with_old_platform_ts_blocked() -> None:
    cond = LiveOnly()
    now = datetime.now(timezone.utc)
    entry = _entry(
        args={
            "delivery_mode": "history_sync",
            "platform_ts": (now - timedelta(hours=2)).isoformat(),
        },
        ts=now,
    )
    assert await cond.allows(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_missing_delivery_mode_defaults_to_push_allowed() -> None:
    cond = LiveOnly()
    entry = _entry(args={})
    assert await cond.allows(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_missing_platform_ts_permissive() -> None:
    cond = LiveOnly()
    entry = _entry(args={"delivery_mode": "push"})
    assert await cond.allows(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_invalid_platform_ts_string_permissive() -> None:
    """Bad ISO string falls back to permissive — pre-provenance hygiene."""
    cond = LiveOnly()
    entry = _entry(
        args={"delivery_mode": "push", "platform_ts": "not-a-date"},
    )
    assert await cond.allows(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_freshness_env_override_extends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_FRESHNESS_WINDOW_S", "300")
    cond = LiveOnly()
    now = datetime.now(timezone.utc)
    entry = _entry(
        args={
            "delivery_mode": "push",
            "platform_ts": (now - timedelta(seconds=120)).isoformat(),
        },
        ts=now,
    )
    # 120s is past the 60s default but inside the 300s override.
    assert await cond.allows(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_freshness_env_override_tightens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORMBASE_FRESHNESS_WINDOW_S", "5")
    cond = LiveOnly()
    now = datetime.now(timezone.utc)
    entry = _entry(
        args={
            "delivery_mode": "push",
            "platform_ts": (now - timedelta(seconds=10)).isoformat(),
        },
        ts=now,
    )
    assert await cond.allows(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_composes_with_and_operator() -> None:
    """LiveOnly composes with the existing condition algebra via __and__."""
    composed = LiveOnly() & DomainEnabled()
    # Both branches pass on a fresh push with no domain → True.
    now = datetime.now(timezone.utc)
    entry = _entry(
        args={
            "delivery_mode": "push",
            "platform_ts": (now - timedelta(seconds=5)).isoformat(),
        },
        ts=now,
    )
    # DomainEnabled returns True when registry is None.
    assert await composed.allows(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_composes_blocks_when_history_sync() -> None:
    composed = LiveOnly() & DomainEnabled()
    now = datetime.now(timezone.utc)
    entry = _entry(
        args={"delivery_mode": "history_sync", "platform_ts": now.isoformat()},
        ts=now,
    )
    # LiveOnly says no → AND short-circuits to no, regardless of DomainEnabled.
    assert await composed.allows(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_composes_with_three_way_and() -> None:
    """F4 SourceMentionedReactivity composes NotRecentlyFired & LiveOnly &
    DomainEnabled — verify the chain operates on LiveOnly correctly."""
    composed = (
        NotRecentlyFired(novelty_key="dummy", hours=1.0)
        & LiveOnly()
        & DomainEnabled()
    )
    now = datetime.now(timezone.utc)
    entry = _entry(
        args={
            "delivery_mode": "history_sync",
            "platform_ts": now.isoformat(),
        },
        ts=now,
    )
    # LiveOnly will block in the middle.
    assert await composed.allows(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_platform_ts_as_datetime_object_handled() -> None:
    """Some call paths set platform_ts as a datetime, not an ISO string."""
    cond = LiveOnly()
    now = datetime.now(timezone.utc)
    entry = _entry(
        args={
            "delivery_mode": "push",
            "platform_ts": now - timedelta(seconds=5),
        },
        ts=now,
    )
    assert await cond.allows(entry, _ctx()) is True
