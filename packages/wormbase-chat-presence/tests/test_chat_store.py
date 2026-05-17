"""ChatStore impl tests — read_policy + count_interjections_today + read_messages."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from wormbase_chat_presence.chat_store import _LedgerBackedChatStore
from wormbase_chat_presence.protocols import ChatStore
from wormbase_ledger import InMemoryLedger


def test_chat_store_satisfies_protocol() -> None:
    ledger = InMemoryLedger()
    store = _LedgerBackedChatStore(ledger=ledger)
    assert isinstance(store, ChatStore)


@pytest.mark.asyncio
async def test_read_policy_default_on_empty_tenant() -> None:
    """No policy_applied for the channel → default ChatPolicy."""
    ledger = InMemoryLedger()
    store = _LedgerBackedChatStore(ledger=ledger)
    company = uuid4()

    policy = await store.read_policy(company_id=company, channel_id="C123")

    assert policy.talkativeness == "responsive"
    assert policy.daily_interjection_budget == 3


@pytest.mark.asyncio
async def test_read_policy_folds_policy_applied_entries() -> None:
    """A policy_applied entry for the channel changes the resolved policy."""
    ledger = InMemoryLedger()
    store = _LedgerBackedChatStore(ledger=ledger)
    company = uuid4()
    channel_id = "C_LURKER"

    # Write a policy_applied entry setting the channel to lurker.
    await ledger.write(
        company_id=company,
        propose={
            "target_kind": "policy_applied",
            "ref_id": str(uuid4()),
            "reason": "admin: silence #legal",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_policy_applied",
            "args": {
                "policy_id": str(uuid4()),
                "policy_name": "policy:channel_talkativeness",
                "applies_to": {"scope": "channel", "channel_id": channel_id},
                "rule": "lurker mode",
                "gate_impl": "channel_talkativeness_default",
                "talkativeness": "lurker",
                "daily_interjection_budget": 0,
            },
            "result_ref": channel_id,
        },
        verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
        resolve_fn=lambda _v: {"outcome": "applied", "rationale": "admin set"},
        timestamp=datetime.now(UTC),
        quadrant="active_deterministic",
    )

    policy = await store.read_policy(company_id=company, channel_id=channel_id)
    assert policy.talkativeness == "lurker"
    assert policy.daily_interjection_budget == 0


@pytest.mark.asyncio
async def test_count_interjections_today_zero_default() -> None:
    """No clarify_asked entries → zero count."""
    ledger = InMemoryLedger()
    store = _LedgerBackedChatStore(ledger=ledger)
    company = uuid4()

    count = await store.count_interjections_today(
        company_id=company, channel_id="C1", now=datetime.now(UTC),
    )
    assert count == 0


@pytest.mark.asyncio
async def test_count_interjections_today_folds_clarify_asked() -> None:
    """Two clarify_asked entries today → count=2."""
    ledger = InMemoryLedger()
    store = _LedgerBackedChatStore(ledger=ledger)
    company = uuid4()
    channel_id = "C1"
    now = datetime.now(UTC)

    for _ in range(2):
        await ledger.write(
            company_id=company,
            propose={
                "target_kind": "memory_written",
                "ref_id": str(uuid4()),
                "reason": "clarify",
                "proposed_by": "test",
            },
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {
                    "memory_id": str(uuid4()),
                    "content": f"clarify_asked:{channel_id}",
                    "tags": ["clarify_asked", f"channel:{channel_id}"],
                },
                "result_ref": channel_id,
            },
            verify_fn=lambda _r: {"checks": [{"name": "ok", "ok": True}], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "clarify"},
            timestamp=now,
            quadrant="active_deterministic",
        )

    count = await store.count_interjections_today(
        company_id=company, channel_id=channel_id, now=now,
    )
    assert count == 2
