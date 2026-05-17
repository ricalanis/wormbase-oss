"""wire_chat_for_install registers the four Reactivities + returns the dispatcher.

Block G2 of the chat-worm extraction plan
(docs/superpowers/plans/2026-05-03-chat-worm-extraction.md, lines 3911-4161).

The lifecycle helper registers the four chat Reactivities (chat_received,
mention_response, interjection_budget, source_mentioned) on the worm-core
ReactivityRegistry, builds the chat dispatcher, and returns a ChatBundle
exposing the dispatcher + chat_reply + chat_store + relevance_gate handles
so cli.py can thread the dispatcher into chat_received_reactivity_poller.

Block H's _LedgerChatReply is a forward reference at G2 time; a minimal
stub satisfies the bundle contract (degraded speak path when channel_adapter
is None — same posture H specs for the production impl).
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from wormbase_chat_presence import Install
from wormbase_chat_presence.lifecycle import wire_chat_for_install
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry


@pytest.mark.asyncio
async def test_wire_chat_registers_four_reactivities() -> None:
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = Install(id=company, platform="slack")

    # Stubs for flows; chat-worm doesn't construct them in v1, the caller does.
    class _Stub:
        async def on_file_drop(self, infra: Any) -> Any: return None
        async def on_dm(self, infra: Any) -> Any: return None
        async def on_proactive_mention(self, infra: Any) -> Any: return None

    bundle = await wire_chat_for_install(
        install=install,
        ledger=ledger,
        reactivity_registry=registry,
        drop_and_profile=_Stub(),
        credential_in_dm=_Stub(),
        mentioned_in_conversation=_Stub(),
        channel_adapter=None,  # chat_reply degrades gracefully when None
        channel_adapter_handle=None,
    )

    ids = {r.id for r in registry.list()}
    assert {"chat_received", "mention_response",
            "interjection_budget", "source_mentioned"}.issubset(ids)

    # Bundle exposes the dispatcher + chat_reply + chat_store.
    assert callable(bundle.dispatcher)
    assert bundle.chat_reply is not None
    assert bundle.chat_store is not None


@pytest.mark.asyncio
async def test_wire_chat_returns_bundle_with_relevance_gate() -> None:
    """Bundle exposes relevance_gate alongside the other handles."""
    company = uuid4()
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=company)
    install = Install(id=company, platform="slack")

    class _Stub:
        async def on_file_drop(self, infra: Any) -> Any: return None
        async def on_dm(self, infra: Any) -> Any: return None
        async def on_proactive_mention(self, infra: Any) -> Any: return None

    bundle = await wire_chat_for_install(
        install=install,
        ledger=ledger,
        reactivity_registry=registry,
        drop_and_profile=_Stub(),
        credential_in_dm=_Stub(),
        mentioned_in_conversation=_Stub(),
        channel_adapter=None,
        channel_adapter_handle=None,
    )

    assert bundle.relevance_gate is not None
