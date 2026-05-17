"""Tests for parse_session_line — the OpenClaw JSONL → ParsedEvent mapping."""

from __future__ import annotations

from wormbase_channel_adapter.parser import (
    ChatReceivedEvent,
    ChatSentEvent,
    parse_session_line,
)
from tests.conftest import (
    make_inbound_line,
    make_outbound_line,
    make_session_header_line,
    make_tool_call_line,
    make_tool_result_line,
)


class TestUserMessages:
    def test_slack_inbound_extracts_metadata(self, session_id: str) -> None:
        line = make_inbound_line()
        event = parse_session_line(line, session_id=session_id)
        assert isinstance(event, ChatReceivedEvent)
        assert event.kind == "chat_received"
        assert event.session_id == session_id
        assert event.event_id == "beaf55cd"
        assert event.channel_id == "channel:C0B06MCSLQ1"
        assert event.message_id == "1777152782.692639"
        assert event.sender_id == "U0AV4C8TTEZ"
        assert event.sender_label == "Ricardo Alanís"
        assert event.conversation_label == "#todo-baseworm"
        # Cleaned text is exactly what the user typed (extracted from the
        # `System: [...] Slack message in #channel from <name>: <body>` line).
        assert event.text == "<@U0AUSATGUB1> (WormBase) hello"
        # Bootstrap noise + metadata blocks must NOT leak into the body.
        assert "Bootstrap pending" not in event.text
        assert "chat_id" not in event.text
        assert "BOOTSTRAP.md" not in event.text
        assert "EXTERNAL_UNTRUSTED_CONTENT" not in event.text

    def test_bootstrap_only_user_message_is_ignored(self, session_id: str) -> None:
        # No "Slack message in" marker = no Slack inbound. This is the
        # synthetic bootstrap nudge OpenClaw injects on first run.
        line = make_inbound_line(text="[Bootstrap pending]\nPlease read BOOTSTRAP.md...")
        event = parse_session_line(line, session_id=session_id)
        assert event is None

    def test_user_message_without_metadata_block_is_ignored(self, session_id: str) -> None:
        line = make_inbound_line(text="System: [..] Slack message in #x from Y: hi")
        event = parse_session_line(line, session_id=session_id)
        assert event is None  # has marker but no JSON metadata

    def test_inbound_carries_tz_aware_timestamp(self, session_id: str) -> None:
        line = make_inbound_line(timestamp="2026-04-25T21:36:13.978Z")
        event = parse_session_line(line, session_id=session_id)
        assert isinstance(event, ChatReceivedEvent)
        assert event.ts.tzinfo is not None


class TestAssistantMessages:
    def test_assistant_text_with_stop_is_chat_sent(self, session_id: str) -> None:
        line = make_outbound_line(text="Hello world.")
        event = parse_session_line(line, session_id=session_id)
        assert isinstance(event, ChatSentEvent)
        assert event.text == "Hello world."
        assert event.session_id == session_id
        assert event.in_reply_to is None

    def test_assistant_in_reply_to_is_threaded_through(self, session_id: str) -> None:
        line = make_outbound_line(text="ack")
        event = parse_session_line(
            line, session_id=session_id, last_inbound_message_id="1777152782.692639"
        )
        assert isinstance(event, ChatSentEvent)
        assert event.in_reply_to == "1777152782.692639"

    def test_assistant_tool_call_is_ignored(self, session_id: str) -> None:
        line = make_tool_call_line()
        assert parse_session_line(line, session_id=session_id) is None

    def test_assistant_empty_text_is_ignored(self, session_id: str) -> None:
        line = make_outbound_line(text="   ")
        assert parse_session_line(line, session_id=session_id) is None


class TestNonMessageEvents:
    def test_session_header_is_ignored(self, session_id: str) -> None:
        assert parse_session_line(make_session_header_line(), session_id=session_id) is None

    def test_tool_result_is_ignored(self, session_id: str) -> None:
        assert parse_session_line(make_tool_result_line(), session_id=session_id) is None

    def test_blank_line_is_ignored(self, session_id: str) -> None:
        assert parse_session_line("", session_id=session_id) is None
        assert parse_session_line("\n", session_id=session_id) is None

    def test_invalid_json_is_ignored(self, session_id: str) -> None:
        assert parse_session_line("{not json", session_id=session_id) is None

    def test_model_change_is_ignored(self, session_id: str) -> None:
        line = (
            '{"type":"model_change","id":"x","timestamp":"2026-04-25T21:36:13.217Z",'
            '"provider":"ollama","modelId":"kimi-k2.6:cloud"}\n'
        )
        assert parse_session_line(line, session_id=session_id) is None
