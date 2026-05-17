"""Tests for service.GlobalLogCapture.on_channel_admit.

The capture object turns a bare channel-id (from OpenClaw's log) into a
chat_received PEVR cycle in the ledger. The behaviors we lock down:

  * dedup: same Slack ``ts`` for a channel is emitted once;
  * echo guard: messages whose ``subtype=="bot_message"`` AND ``bot_id``
    equals our resolved bot_id are dropped (and recorded in ``last_ts``
    so the next non-bot ts can still be compared);
  * ledger payload: the execute row carries
    ``tool == "channel_adapter.emit_chat_received"``;
  * defensive paths: missing ``ts`` and SlackClient returning None are
    no-ops (no ledger write).
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger

from wormbase_channel_adapter.service import GlobalLogCapture
from wormbase_channel_adapter.tenant import tenant_to_company_uuid


@pytest.fixture
def company_id() -> UUID:
    return tenant_to_company_uuid("baseworm")


def _stub_slack(latest_msg: dict | None, *, bot_id: str | None = None):
    """Return an object that quacks like SlackClient for the capture."""
    stub = AsyncMock()
    stub.fetch_latest_message = AsyncMock(return_value=latest_msg)
    # ``bot_id`` is a *property* on the real class; on AsyncMock we can
    # just set the attribute and it works for ``self._slack.bot_id``.
    stub.bot_id = bot_id
    return stub


def _execute_rows(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "channel_adapter.emit_chat_received"
    ]


@pytest.mark.asyncio
async def test_emits_chat_received_on_first_admit(company_id: UUID) -> None:
    ledger = InMemoryLedger()
    slack = _stub_slack(
        {
            "ts": "1777152782.000001",
            "user": "U0SENDER",
            "text": "hello world",
        }
    )
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0CHAN01")

    rows = await ledger.fetch(company_id)
    # PEVR cycle = 4 entries.
    assert [r["kind"] for r in rows] == [
        "propose",
        "execute",
        "verify",
        "resolve",
    ]
    execute = _execute_rows(rows)
    assert len(execute) == 1
    args = execute[0]["payload"]["args"]
    assert args["channel_id"] == "C0CHAN01"
    assert args["message_id"] == "1777152782.000001"
    assert args["text"] == "hello world"
    # Tool string is the canonical channel_adapter emit name.
    assert execute[0]["payload"]["tool"] == "channel_adapter.emit_chat_received"
    # last_ts updated.
    assert capture.last_ts["C0CHAN01"] == "1777152782.000001"


@pytest.mark.asyncio
async def test_dedup_skips_repeat_ts(company_id: UUID) -> None:
    ledger = InMemoryLedger()
    slack = _stub_slack(
        {"ts": "1777152782.000001", "user": "U0SENDER", "text": "x"}
    )
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0DEDUP")
    await capture.on_channel_admit("C0DEDUP")  # same ts — should no-op
    await capture.on_channel_admit("C0DEDUP")

    rows = await ledger.fetch(company_id)
    assert len(_execute_rows(rows)) == 1
    # And ``fetch_latest_message`` was called every tick (we don't dedup
    # at the network call boundary — we dedup on what comes back).
    assert slack.fetch_latest_message.await_count == 3


@pytest.mark.asyncio
async def test_emits_again_on_newer_ts(company_id: UUID) -> None:
    ledger = InMemoryLedger()
    slack = _stub_slack(
        {"ts": "1777152782.000001", "user": "U0SENDER", "text": "first"}
    )
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0CHAN01")

    # Slack now returns a newer message.
    slack.fetch_latest_message.return_value = {
        "ts": "1777152800.000099",
        "user": "U0SENDER",
        "text": "second",
    }
    await capture.on_channel_admit("C0CHAN01")

    execute = _execute_rows(await ledger.fetch(company_id))
    assert [e["payload"]["args"]["text"] for e in execute] == ["first", "second"]


@pytest.mark.asyncio
async def test_skips_own_bot_messages(company_id: UUID) -> None:
    ledger = InMemoryLedger()
    slack = _stub_slack(
        {
            "ts": "1777152782.000001",
            "subtype": "bot_message",
            "bot_id": "B0SELF",
            "text": "echo of my own reply",
        },
        bot_id="B0SELF",
    )
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0CHAN01")

    rows = await ledger.fetch(company_id)
    assert _execute_rows(rows) == []
    # last_ts is still recorded so a later same-ts call is also skipped.
    assert capture.last_ts["C0CHAN01"] == "1777152782.000001"


@pytest.mark.asyncio
async def test_does_not_skip_other_bots(company_id: UUID) -> None:
    """If the message is from a *different* bot, we still capture it."""
    ledger = InMemoryLedger()
    slack = _stub_slack(
        {
            "ts": "1777152782.000001",
            "subtype": "bot_message",
            "bot_id": "B0OTHER",
            "text": "from a different integration",
        },
        bot_id="B0SELF",
    )
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0CHAN01")

    rows = await ledger.fetch(company_id)
    assert len(_execute_rows(rows)) == 1


def _execute_rows_with_tool(rows: list[dict], tool: str) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "execute" and r["payload"].get("tool") == tool
    ]


@pytest.mark.asyncio
async def test_emits_file_received_for_user_upload(company_id: UUID) -> None:
    """Real user upload — file_share message with files[] payload."""
    ledger = InMemoryLedger()
    slack = _stub_slack(
        {
            "ts": "1777152782.000099",
            "user": "U0BOB",
            "text": "sales-q3.csv",
            "subtype": "file_share",
            "files": [
                {
                    "id": "F0FILE001",
                    "name": "sales-q3.csv",
                    "mimetype": "text/csv",
                    "size": 4096,
                    "url_private": "https://files.example.com/sales-q3.csv",
                },
            ],
        },
        bot_id="B0SELF",
    )
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0DROP01")

    rows = await ledger.fetch(company_id)
    chat_rows = _execute_rows_with_tool(rows, "channel_adapter.emit_chat_received")
    file_rows = _execute_rows_with_tool(rows, "channel_adapter.emit_file_received")
    # Both fire: one chat_received for the caption text, one file_received
    # per file.
    assert len(chat_rows) == 1
    assert len(file_rows) == 1
    args = file_rows[0]["payload"]["args"]
    assert args["channel_id"] == "C0DROP01"
    assert args["slack_file_id"] == "F0FILE001"
    assert args["file_name"] == "sales-q3.csv"
    assert args["mimetype"] == "text/csv"
    assert args["file_size"] == 4096
    assert args["caption_text"] == "sales-q3.csv"


@pytest.mark.asyncio
async def test_emits_file_received_for_bot_upload(company_id: UUID) -> None:
    """C1 regression: sim-harness uploads files via the worm's bot token,
    so Slack records the message with our own ``bot_id``. The chat-level
    echo guard MUST NOT suppress the file_received fan-out (PRD §9.1).
    """
    ledger = InMemoryLedger()
    slack = _stub_slack(
        {
            "ts": "1777152782.000200",
            "subtype": "file_share",
            "bot_id": "B0SELF",  # ← same bot_id as our own (sim-harness path)
            "user": "U0BOTUSER",
            "text": "sales-q3.csv",
            "files": [
                {
                    "id": "F0FILE002",
                    "name": "sales-q3.csv",
                    "mimetype": "text/csv",
                    "size": 4096,
                    "url_private": "https://files.example.com/sales-q3.csv",
                },
            ],
        },
        bot_id="B0SELF",
    )
    # bot_user_id matches our own — so chat_received WOULD be self-echo.
    slack.bot_user_id = "U0BOTUSER"
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0DROP02")

    rows = await ledger.fetch(company_id)
    chat_rows = _execute_rows_with_tool(rows, "channel_adapter.emit_chat_received")
    file_rows = _execute_rows_with_tool(rows, "channel_adapter.emit_file_received")
    # Chat is suppressed (self-echo) — that's fine, the worm shouldn't
    # treat its own caption as inbound chat.
    assert chat_rows == []
    # But the file_received MUST fire — sim-harness drops + future
    # bot-attributed uploads are real wire events the worm must see.
    assert len(file_rows) == 1
    args = file_rows[0]["payload"]["args"]
    assert args["slack_file_id"] == "F0FILE002"


@pytest.mark.asyncio
async def test_file_received_dedups_on_same_file_id(company_id: UUID) -> None:
    """Repeated polls of the same channel/ts/file should emit once."""
    ledger = InMemoryLedger()
    slack = _stub_slack(
        {
            "ts": "1777152782.000300",
            "user": "U0BOB",
            "text": "",
            "subtype": "file_share",
            "files": [{"id": "F0DUP", "name": "x.csv", "mimetype": "text/csv"}],
        },
    )
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0DEDUP")
    await capture.on_channel_admit("C0DEDUP")
    await capture.on_channel_admit("C0DEDUP")

    rows = await ledger.fetch(company_id)
    file_rows = _execute_rows_with_tool(rows, "channel_adapter.emit_file_received")
    assert len(file_rows) == 1


@pytest.mark.asyncio
async def test_no_op_when_slack_returns_none(company_id: UUID) -> None:
    ledger = InMemoryLedger()
    slack = _stub_slack(None)
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0CHAN01")

    assert await ledger.fetch(company_id) == []
    assert capture.last_ts == {}


@pytest.mark.asyncio
async def test_no_op_when_ts_missing(company_id: UUID) -> None:
    ledger = InMemoryLedger()
    slack = _stub_slack({"user": "U0SENDER", "text": "no ts"})
    capture = GlobalLogCapture(ledger=ledger, company_id=company_id, slack=slack)

    await capture.on_channel_admit("C0CHAN01")

    assert await ledger.fetch(company_id) == []
    assert capture.last_ts == {}
