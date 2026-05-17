"""SlackLurker contract tests — exercise the chat_received writer + reactivity dispatch."""

from __future__ import annotations

from wormbase_core.lurker import SlackLurker, slack_user_to_person


def test_slack_user_to_person_is_stable():
    a = slack_user_to_person("U-alice")
    b = slack_user_to_person("U-alice")
    assert a == b


def test_slack_user_to_person_unknown_collides():
    a = slack_user_to_person(None)
    b = slack_user_to_person("")
    assert a == b


async def test_lurker_writes_chat_received_without_pipeline(ledger, company_id):
    lurker = SlackLurker(ledger, company_id, app_token="x", bot_token="x")
    await lurker._handle_event(
        event={
            "type": "message",
            "channel": "C-data",
            "user": "U-alice",
            "text": "hello world",
            "ts": "1745330400.000100",
        },
        body={},
        kind="channel_message",
    )
    rows = await ledger.fetch(company_id)
    chat = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_chat_received"
    ]
    assert len(chat) == 1
    assert chat[0]["payload"]["args"]["text"] == "hello world"


async def test_lurker_skips_bot_messages(ledger, company_id):
    lurker = SlackLurker(ledger, company_id, app_token="x", bot_token="x")
    await lurker._handle_event(
        event={
            "type": "message",
            "subtype": "bot_message",
            "bot_id": "B-self",
            "channel": "C1",
            "text": "no recursion",
            "ts": "1745330400.000200",
        },
        body={},
        kind="channel_message",
    )
    rows = await ledger.fetch(company_id)
    chat = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_chat_received"
    ]
    assert chat == []
