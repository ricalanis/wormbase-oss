"""Tests for the LiveOnly gate on chat-presence Reactivities (F1/F2/F4).

LiveOnly composes into the conditions of:
  * F1 ChatReceivedReactivity     — chat triad routing
  * F2 MentionResponseReactivity  — @-mention reply
  * F4 SourceMentionedReactivity  — data-keyword propose

F3 InterjectionBudgetReactivity is observation-only and intentionally
NOT gated by LiveOnly — its job is to record budget consumption even
on history-replay (the budget itself is computed against the channel's
own clarify_asked stream, which is internal — not subject to wire
replay semantics).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from wormbase_chat_presence.reactivities import (
    ChatReceivedReactivity,
    MentionResponseReactivity,
    SourceMentionedReactivity,
)
from wormbase_reactivities.protocol import ReactivityContext


def _ctx() -> ReactivityContext:
    return ReactivityContext(
        ledger=None,
        company_id=uuid4(),
        registry=None,
        now=datetime.now(UTC),
        extras={"reactivity_id": "test"},
    )


def _entry(*, args: dict[str, Any], ts: datetime | None = None) -> dict[str, Any]:
    return {
        "kind": "execute",
        "ts": ts or datetime.now(UTC),
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
        },
    }


# ---------------------------------------------------------------------------
# F1 ChatReceivedReactivity
# ---------------------------------------------------------------------------


class TestF1ChatReceivedReactivity:
    @pytest.mark.asyncio
    async def test_history_sync_blocks_condition(self) -> None:
        r = ChatReceivedReactivity()
        now = datetime.now(UTC)
        entry = _entry(
            args={
                "channel_id": "C1",
                "message_id": "m1",
                "text": "we should pull from Stripe",
                "delivery_mode": "history_sync",
                "platform_ts": now.isoformat(),
                "history_sync_id": "sync-1",
            },
            ts=now,
        )
        assert await r.condition.allows(entry, _ctx()) is False

    @pytest.mark.asyncio
    async def test_stale_push_blocks_condition(self) -> None:
        r = ChatReceivedReactivity()
        now = datetime.now(UTC)
        entry = _entry(
            args={
                "channel_id": "C1",
                "message_id": "m1",
                "text": "hello",
                "delivery_mode": "push",
                "platform_ts": (now - timedelta(hours=2)).isoformat(),
            },
            ts=now,
        )
        assert await r.condition.allows(entry, _ctx()) is False

    @pytest.mark.asyncio
    async def test_fresh_push_allows_condition(self) -> None:
        r = ChatReceivedReactivity()
        now = datetime.now(UTC)
        entry = _entry(
            args={
                "channel_id": "C1",
                "message_id": "m1",
                "text": "hello",
                "delivery_mode": "push",
                "platform_ts": (now - timedelta(seconds=5)).isoformat(),
            },
            ts=now,
        )
        assert await r.condition.allows(entry, _ctx()) is True


# ---------------------------------------------------------------------------
# F2 MentionResponseReactivity
# ---------------------------------------------------------------------------


class TestF2MentionResponseReactivity:
    @pytest.mark.asyncio
    async def test_history_sync_mention_blocked(self) -> None:
        r = MentionResponseReactivity()
        now = datetime.now(UTC)
        entry = _entry(
            args={
                "channel_id": "C1",
                "message_id": "m1",
                "text": "@worm hello",
                "delivery_mode": "history_sync",
                "platform_ts": now.isoformat(),
                "history_sync_id": "sync-1",
            },
            ts=now,
        )
        assert await r.condition.allows(entry, _ctx()) is False

    @pytest.mark.asyncio
    async def test_stale_push_mention_blocked(self) -> None:
        r = MentionResponseReactivity()
        now = datetime.now(UTC)
        entry = _entry(
            args={
                "channel_id": "C1",
                "message_id": "m1",
                "text": "@worm hello",
                "delivery_mode": "push",
                "platform_ts": (now - timedelta(seconds=120)).isoformat(),
            },
            ts=now,
        )
        assert await r.condition.allows(entry, _ctx()) is False

    @pytest.mark.asyncio
    async def test_fresh_push_mention_allowed(self) -> None:
        r = MentionResponseReactivity()
        now = datetime.now(UTC)
        entry = _entry(
            args={
                "channel_id": "C1",
                "message_id": "m1",
                "text": "@worm hello",
                "delivery_mode": "push",
                "platform_ts": (now - timedelta(seconds=2)).isoformat(),
            },
            ts=now,
        )
        assert await r.condition.allows(entry, _ctx()) is True


# ---------------------------------------------------------------------------
# F3 InterjectionBudgetReactivity — NOT gated; verifies the negative case.
# ---------------------------------------------------------------------------


class TestF3InterjectionBudgetReactivityNotGated:
    @pytest.mark.asyncio
    async def test_condition_is_always_allow(self) -> None:
        """F3 keeps AlwaysAllow; observation-only path."""
        from wormbase_chat_presence.reactivities import InterjectionBudgetReactivity
        from wormbase_reactivities.conditions import AlwaysAllow
        r = InterjectionBudgetReactivity()
        assert isinstance(r.condition, AlwaysAllow)

    @pytest.mark.asyncio
    async def test_history_sync_clarify_still_passes_condition(self) -> None:
        """Even a history_sync clarify_asked should pass F3's condition gate
        (LiveOnly is intentionally NOT applied to F3)."""
        from wormbase_chat_presence.reactivities import InterjectionBudgetReactivity
        r = InterjectionBudgetReactivity()
        now = datetime.now(UTC)
        # F3's predicate matches emit_memory_written entries with
        # content="clarify_asked:<channel>". Build an entry that fits.
        entry = {
            "kind": "execute",
            "ts": now,
            "payload": {
                "tool": "emit_memory_written",
                "args": {
                    "content": "clarify_asked:C_test",
                    "delivery_mode": "history_sync",  # would block LiveOnly
                    "platform_ts": (now - timedelta(hours=2)).isoformat(),
                },
            },
        }
        assert await r.condition.allows(entry, _ctx()) is True


# ---------------------------------------------------------------------------
# F4 SourceMentionedReactivity
# ---------------------------------------------------------------------------


class TestF4SourceMentionedReactivity:
    @pytest.mark.asyncio
    async def test_history_sync_blocks_condition(self) -> None:
        r = SourceMentionedReactivity()
        now = datetime.now(UTC)
        entry = _entry(
            args={
                "channel_id": "C1",
                "message_id": "m1",
                "text": "stripe data",
                "delivery_mode": "history_sync",
                "platform_ts": now.isoformat(),
                "history_sync_id": "sync-1",
            },
            ts=now,
        )
        assert await r.condition.allows(entry, _ctx()) is False

    @pytest.mark.asyncio
    async def test_stale_push_blocks_condition(self) -> None:
        r = SourceMentionedReactivity()
        now = datetime.now(UTC)
        entry = _entry(
            args={
                "channel_id": "C1",
                "message_id": "m1",
                "text": "stripe data",
                "delivery_mode": "push",
                "platform_ts": (now - timedelta(seconds=120)).isoformat(),
            },
            ts=now,
        )
        assert await r.condition.allows(entry, _ctx()) is False

    @pytest.mark.asyncio
    async def test_fresh_push_allows_condition(self) -> None:
        r = SourceMentionedReactivity()
        now = datetime.now(UTC)
        entry = _entry(
            args={
                "channel_id": "C1",
                "message_id": "m1",
                "text": "stripe data",
                "delivery_mode": "push",
                "platform_ts": (now - timedelta(seconds=5)).isoformat(),
            },
            ts=now,
        )
        # F4 also has NotRecentlyFired; without a registry, it defaults to True.
        assert await r.condition.allows(entry, _ctx()) is True
