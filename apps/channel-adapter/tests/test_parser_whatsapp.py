"""Tests for the WhatsApp branch of :func:`parse_session_line`.

The parser sees ``role=user`` frames whose body has NO Slack
metadata block (OpenClaw 2026.5.6 routes WhatsApp DMs through the
agent without a Slack-style envelope; the body arrives bare). When a
``whatsapp_envelope_lookup`` callable is wired, the parser correlates
against the watcher's recent-envelope cache and emits a WhatsApp-shaped
``ChatReceivedEvent`` on hit. Without the callable (Slack-only
deployment) the behavior is byte-identical with the pre-WhatsApp wire.

Covers:

* WhatsApp body + envelope hit → emit WhatsApp-shaped ChatReceivedEvent
  with correct sender_jid, channel_id, text;
* WhatsApp body + envelope miss (no recent match) → returns None;
* Slack body still parses correctly when callable is wired (no
  cross-fire interference);
* Bootstrap prompt body + envelope hit → returns None (no fabrication);
* @-mention extraction surfaces ``mentioned_jids`` when present;
* group-chat envelope is NOT correlated as a Person message (the
  envelope's ``chat_type == "group"`` is filtered out).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from wormbase_channel_adapter.parser import (
    ChatReceivedEvent,
    parse_session_line,
)
from wormbase_channel_adapter.whatsapp_envelope_watcher import (
    WhatsAppInboundEnvelope,
)
from tests.conftest import (
    make_inbound_line,
)


# ---------------------------------------------------------------------------
# Helpers — synthesize WhatsApp-shaped session JSONL frames
# ---------------------------------------------------------------------------


def _whatsapp_user_line(
    body: str = "sup yo",
    *,
    event_id: str = "wa-evt-1",
    timestamp: str = "2026-05-07T04:10:50.000Z",
) -> str:
    """A bare role=user frame with no Slack envelope — the WhatsApp shape
    OpenClaw 2026.5.6 writes for inbound WhatsApp DMs."""
    return (
        json.dumps(
            {
                "type": "message",
                "id": event_id,
                "timestamp": timestamp,
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": body}],
                    "timestamp": 1777152973875,
                },
            }
        )
        + "\n"
    )


def _make_lookup(envelope: WhatsAppInboundEnvelope | None):
    """Build a deterministic envelope-lookup callable for tests."""
    def _lookup(target_ts: datetime, window_s: float) -> Any:  # noqa: ARG001
        return envelope
    return _lookup


def _make_envelope(
    *,
    ts: datetime | None = None,
    sender_jid: str = "5218117649489@s.whatsapp.net",
    bot_jid: str = "5218114822051@s.whatsapp.net",
    chat_type: str = "direct",
    char_count: int | None = 62,
) -> WhatsAppInboundEnvelope:
    if ts is None:
        ts = datetime(2026, 5, 7, 4, 10, 49, tzinfo=UTC)
    return WhatsAppInboundEnvelope(
        ts=ts,
        sender_jid=sender_jid,
        bot_jid=bot_jid,
        chat_type=chat_type,  # type: ignore[arg-type]
        char_count=char_count,
    )


# ---------------------------------------------------------------------------
# Successful correlation
# ---------------------------------------------------------------------------


class TestWhatsAppCorrelation:
    def test_envelope_hit_emits_chat_received(
        self, session_id: str,
    ) -> None:
        line = _whatsapp_user_line(body="sup yo")
        envelope = _make_envelope()
        event = parse_session_line(
            line,
            session_id=session_id,
            whatsapp_envelope_lookup=_make_lookup(envelope),
        )
        assert isinstance(event, ChatReceivedEvent)
        assert event.kind == "chat_received"
        # Sender + channel are the WhatsApp jid (B2 regex matches).
        assert event.sender_id == "5218117649489@s.whatsapp.net"
        assert event.channel_id == "5218117649489@s.whatsapp.net"
        assert event.message_id == "wa-evt-1"
        assert event.event_id == "wa-evt-1"
        # Body forwarded verbatim (no envelope to strip).
        assert event.text == "sup yo"
        # Display label: phone digits (operator renames via /people).
        assert event.sender_label == "5218117649489"
        # Provenance: live push, platform_ts from the envelope.
        assert event.delivery_mode == "push"
        assert event.platform_ts == envelope.ts
        assert event.history_sync_id is None
        # No mentions in this body.
        assert event.mentioned_jids is None

    def test_body_with_mention_surfaces_mentioned_jids(
        self, session_id: str,
    ) -> None:
        line = _whatsapp_user_line(body="hey @5218114822051 take a look")
        envelope = _make_envelope()
        event = parse_session_line(
            line,
            session_id=session_id,
            whatsapp_envelope_lookup=_make_lookup(envelope),
        )
        assert isinstance(event, ChatReceivedEvent)
        assert event.mentioned_jids == ["5218114822051@s.whatsapp.net"]

    def test_envelope_miss_returns_none(self, session_id: str) -> None:
        line = _whatsapp_user_line(body="sup yo")
        # Lookup returns None → no correlation possible.
        event = parse_session_line(
            line,
            session_id=session_id,
            whatsapp_envelope_lookup=_make_lookup(None),
        )
        assert event is None

    def test_no_lookup_callable_returns_none(self, session_id: str) -> None:
        """Slack-only deployment: no callable, drop bare frames."""
        line = _whatsapp_user_line(body="sup yo")
        event = parse_session_line(line, session_id=session_id)
        assert event is None

    def test_group_envelope_is_not_correlated(self, session_id: str) -> None:
        """Group envelopes don't carry per-message sender jids; skip."""
        line = _whatsapp_user_line(body="anyone home?")
        envelope = _make_envelope(chat_type="group")
        event = parse_session_line(
            line,
            session_id=session_id,
            whatsapp_envelope_lookup=_make_lookup(envelope),
        )
        assert event is None

    def test_empty_body_returns_none(self, session_id: str) -> None:
        line = _whatsapp_user_line(body="   ")
        envelope = _make_envelope()
        event = parse_session_line(
            line,
            session_id=session_id,
            whatsapp_envelope_lookup=_make_lookup(envelope),
        )
        assert event is None


class TestBootstrapBodiesAreFiltered:
    def test_bootstrap_pending_with_envelope_returns_none(
        self, session_id: str,
    ) -> None:
        """Even with a recent envelope present, [Bootstrap pending]
        is the synthetic boot prompt — never correlate."""
        line = _whatsapp_user_line(
            body="[Bootstrap pending]\nPlease read BOOTSTRAP.md...",
        )
        envelope = _make_envelope()
        event = parse_session_line(
            line,
            session_id=session_id,
            whatsapp_envelope_lookup=_make_lookup(envelope),
        )
        assert event is None

    def test_bootstrap_marker_returns_none(self, session_id: str) -> None:
        line = _whatsapp_user_line(body="[Bootstrap]\nplease load context")
        envelope = _make_envelope()
        event = parse_session_line(
            line,
            session_id=session_id,
            whatsapp_envelope_lookup=_make_lookup(envelope),
        )
        assert event is None


class TestSlackBackcompatWithEnvelopeLookup:
    """When a WhatsApp lookup is wired but a Slack frame arrives,
    the Slack metadata path takes precedence — no cross-fire."""

    def test_slack_inbound_still_parses(self, session_id: str) -> None:
        slack_line = make_inbound_line()
        envelope = _make_envelope()
        # Even though we wired a WhatsApp lookup, this Slack frame must
        # parse via the existing metadata path with no interference.
        event = parse_session_line(
            slack_line,
            session_id=session_id,
            whatsapp_envelope_lookup=_make_lookup(envelope),
        )
        assert isinstance(event, ChatReceivedEvent)
        assert event.channel_id == "channel:C0B06MCSLQ1"
        assert event.sender_id == "U0AV4C8TTEZ"
        assert event.text == "<@U0AUSATGUB1> (WormBase) hello"
        # Slack frames don't get WhatsApp provenance.
        assert event.delivery_mode == "push"
        assert event.platform_ts is None  # untouched
        assert event.mentioned_jids is None

    def test_slack_inbound_byte_identical_without_lookup(
        self, session_id: str,
    ) -> None:
        """The default-None back-compat surface — existing Slack tests
        in test_parser.py already pin this. We re-pin here to lock the
        contract that the new kwarg defaulting to None preserves it."""
        slack_line = make_inbound_line()
        a = parse_session_line(slack_line, session_id=session_id)
        b = parse_session_line(
            slack_line,
            session_id=session_id,
            whatsapp_envelope_lookup=None,
        )
        assert isinstance(a, ChatReceivedEvent)
        assert isinstance(b, ChatReceivedEvent)
        # Same fields all the way through.
        assert a == b


class TestEnvelopeLookupReceivesFrameTs:
    """Spec contract: the parser passes the frame's timestamp + the
    default 30s window to the lookup callable."""

    def test_lookup_receives_frame_ts_and_default_window(
        self, session_id: str,
    ) -> None:
        captured: list[tuple[datetime, float]] = []

        def _lookup(target_ts: datetime, window_s: float) -> Any:
            captured.append((target_ts, window_s))
            return _make_envelope()

        line = _whatsapp_user_line(
            body="hi",
            timestamp="2026-05-07T04:10:50.500Z",
        )
        parse_session_line(
            line,
            session_id=session_id,
            whatsapp_envelope_lookup=_lookup,
        )
        assert len(captured) == 1
        ts, window = captured[0]
        # Frame ts: 2026-05-07T04:10:50.500+00:00
        assert ts == datetime(2026, 5, 7, 4, 10, 50, 500_000, tzinfo=UTC)
        # Default window — pinned at 30s in the parser module.
        assert window == 30.0
