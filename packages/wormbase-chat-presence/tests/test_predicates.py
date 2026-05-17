"""W5a-style predicate tests for chat-worm."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from wormbase_chat_presence.predicates import DataKeywordMatch, MentionsWorm
from wormbase_reactivities.protocol import ReactivityContext


def _ctx() -> ReactivityContext:
    return ReactivityContext(
        ledger=SimpleNamespace(),
        company_id=uuid4(),
        registry=None,
        now=lambda: None,
    )


@pytest.mark.asyncio
async def test_mentions_worm_matches_handle() -> None:
    p = MentionsWorm(handle="@worm")
    entry = {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {"text": "Hey @worm what is the churn rate?"},
        },
    }
    assert await p.match(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_mentions_worm_misses_without_handle() -> None:
    p = MentionsWorm(handle="@worm")
    entry = {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {"text": "What is the churn rate?"},
        },
    }
    assert await p.match(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_mentions_worm_skips_non_chat_entry() -> None:
    p = MentionsWorm(handle="@worm")
    entry = {
        "kind": "execute",
        "payload": {
            "tool": "emit_source_proposed",
            "args": {"text": "@worm hi"},  # text irrelevant on non-chat entry
        },
    }
    assert await p.match(entry, _ctx()) is False


@pytest.mark.asyncio
async def test_data_keyword_match_hits_stripe() -> None:
    p = DataKeywordMatch()
    entry = {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {"text": "we should pull from Stripe"},
        },
    }
    assert await p.match(entry, _ctx()) is True


@pytest.mark.asyncio
async def test_data_keyword_match_misses_unknown() -> None:
    p = DataKeywordMatch()
    entry = {
        "kind": "execute",
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {"text": "we should write a markdown doc"},
        },
    }
    assert await p.match(entry, _ctx()) is False
