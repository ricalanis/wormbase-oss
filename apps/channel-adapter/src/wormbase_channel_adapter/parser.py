"""Parse one OpenClaw session JSONL line into a typed channel event.

OpenClaw v3 session schema (observed; not contract-tested upstream):

    {"type":"session", ...}                     # ignore — file header
    {"type":"model_change", ...}                # ignore
    {"type":"thinking_level_change", ...}       # ignore
    {"type":"custom", ...}                      # ignore
    {"type":"message", "id":..., "message": {
        "role": "user",      content:[{type:text, text: "<slack metadata>"}]
        "role": "assistant", content:[{type:text|toolCall, ...}]
        "role": "toolResult", ...
     }}

Slack inbound (chat_received) lives in ``role=user`` text content as a
plain-text envelope that begins ``System: [<ts>] Slack message in
#<channel>`` and contains a fenced JSON block::

    Conversation info (untrusted metadata):
    ```json
    {
      "chat_id": "channel:C0B06MCSLQ1",
      "message_id": "1777152782.692639",
      "sender_id": "U0AV4C8TTEZ",
      "conversation_label": "#todo-baseworm",
      "sender": "Ricardo Alanís",
      ...
    }
    ```

Slack outbound (chat_sent) lives in ``role=assistant`` messages whose
content array is exactly one ``{"type":"text"}`` block AND ``stopReason``
is ``"stop"`` (i.e. not ``"toolUse"``). Tool calls and tool results are
ignored.

Bootstrap user prompts (the ``[Bootstrap pending]`` synthetic prompt) and
assistant replies that come *before* the first real Slack inbound are NOT
emitted — we key off the embedded Slack metadata block to distinguish a
real inbound from a synthetic system prompt.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from wormbase_channel_adapter.whatsapp_envelope_watcher import (
        WhatsAppInboundEnvelope,  # noqa: F401  Used as forward-ref string in type alias below.
    )

# Public type alias for the WhatsApp envelope-lookup callable threaded
# into ``parse_session_line``. Returns the most-recent envelope within
# the requested window, or ``None``. Defined here as a forward-string
# annotation so this module stays import-cycle-free even when the
# watcher imports something from parser later.
WhatsAppEnvelopeLookup = Callable[
    [datetime, float], "WhatsAppInboundEnvelope | None",
]


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatReceivedEvent:
    """A real Slack message arrived from a user.

    Provenance fields (additive, defaulted for back-compat with callers
    that pre-date the conversation-provenance work) carry the same shape
    as ``ChatReceivedPayload``:
      * ``delivery_mode`` — "push" (default) vs "history_sync".
      * ``platform_ts`` — platform's authoritative wall-clock; ``None`` if
        unknown or not surfaced.
      * ``history_sync_id`` — UUID string of the parent ``conversation_sync``
        entry; ``None`` for live (push) events.
      * ``mentioned_jids`` — list of WhatsApp jids explicitly mentioned in
        the message body (extracted from Baileys'
        ``payload.message.extendedTextMessage.contextInfo.mentionedJid``).
        Slack callers leave this ``None``; WhatsApp messages without
        mentions surface an empty list. (Wave B1.1, 2026-05-06.)
    """

    kind: Literal["chat_received"]
    session_id: str
    event_id: str  # the OpenClaw message id (stable per line)
    ts: datetime
    channel_id: str  # e.g. "channel:C0B06MCSLQ1"
    message_id: str  # Slack ts (e.g. "1777152782.692639")
    sender_id: str  # Slack user id (e.g. "U0AV4C8TTEZ")
    sender_label: str
    text: str  # the user-visible text (after metadata stripping)
    conversation_label: str  # "#todo-baseworm"
    delivery_mode: Literal["push", "history_sync"] = "push"
    platform_ts: datetime | None = None
    history_sync_id: str | None = None
    mentioned_jids: list[str] | None = None


@dataclass(frozen=True)
class ChatSentEvent:
    """The agent posted a final text reply (not a tool call)."""

    kind: Literal["chat_sent"]
    session_id: str
    event_id: str
    ts: datetime
    text: str
    in_reply_to: str | None  # last seen received message_id, when available


ParsedEvent = ChatReceivedEvent | ChatSentEvent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_SLACK_INBOUND_MARKER = "Slack message in"
_JSON_BLOCK_RE = re.compile(
    r"Conversation info \(untrusted metadata\):\s*```json\s*(\{.*?\})\s*```",
    re.DOTALL,
)
# Captures the user-visible body OpenClaw wraps in a `System:` line. Format:
#     System: [2026-04-25 21:34:05 UTC] Slack message in #channel from Name: <body>
# The body extends to end of line (Slack messages can be multi-line; OpenClaw
# keeps the whole message on one System: line, with embedded \n preserved).
_SYSTEM_LINE_RE = re.compile(
    r"^System:\s+\[[^\]]+\]\s+Slack message in\s+\S+\s+from\s+[^:]+:\s+(.*)$",
    re.MULTILINE,
)
# Bootstrap markers — synthetic prompts OpenClaw injects before any real
# inbound. We must NOT correlate these against a WhatsApp envelope (they
# are not user-authored messages). The marker check runs after the Slack
# branch so a user message containing the literal string still parses
# correctly via the Slack metadata path.
_BOOTSTRAP_MARKERS: tuple[str, ...] = (
    "[Bootstrap pending]",
    "[Bootstrap]",
)
# Default correlation window for the WhatsApp envelope lookup. Mirrors
# the watcher's default; pinned here so callers who don't pass an
# explicit window get the same value the watcher documents.
_DEFAULT_WHATSAPP_WINDOW_S = 30.0
# WhatsApp inbound @-mention pattern. Baileys mentions surface as
# ``@<digits>`` in the rendered body when no extendedTextMessage
# context is present. We forward only well-formed mentions (digits +
# DM-jid suffix) so the MentionsWorm WhatsApp branch evaluates on
# real ledger entries; everything else stays None.
_WHATSAPP_MENTION_RE = re.compile(r"@(\d+)\b")


def parse_session_line(
    raw_line: str,
    session_id: str,
    *,
    last_inbound_message_id: str | None = None,
    whatsapp_envelope_lookup: "WhatsAppEnvelopeLookup | None" = None,
) -> ParsedEvent | None:
    """Return a typed event, or None if the line is not channel-relevant.

    ``last_inbound_message_id`` lets us populate ``in_reply_to`` on a
    ``chat_sent`` event without forcing the caller to do correlation. Pass
    None when the caller has not yet seen any inbound on this session.

    ``whatsapp_envelope_lookup`` is an optional callable that takes
    ``(target_ts, window_s)`` and returns the most-recent
    :class:`WhatsAppInboundEnvelope` cached by
    :class:`WhatsAppInboundEnvelopeWatcher`, or ``None`` when no
    correlation hits. When provided, the parser correlates a
    ``role=user`` frame that has no Slack metadata block against the
    watcher's recent-envelope cache, emitting a WhatsApp-shaped
    ``ChatReceivedEvent`` on hit. When ``None`` (default), Slack
    behavior is byte-identical: non-Slack frames return None.
    """
    raw_line = raw_line.strip()
    if not raw_line:
        return None
    try:
        obj: dict[str, Any] = json.loads(raw_line)
    except json.JSONDecodeError:
        return None

    if obj.get("type") != "message":
        return None

    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None

    role = msg.get("role")
    event_id = str(obj.get("id") or "")
    ts_raw = obj.get("timestamp")
    if not isinstance(ts_raw, str):
        return None
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    except ValueError:
        return None

    if role == "user":
        return _parse_user_message(
            obj, msg, session_id, event_id, ts,
            whatsapp_envelope_lookup=whatsapp_envelope_lookup,
        )
    if role == "assistant":
        return _parse_assistant_message(
            obj, msg, session_id, event_id, ts, last_inbound_message_id
        )
    return None  # toolResult and others


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _parse_user_message(
    _envelope: dict[str, Any],
    msg: dict[str, Any],
    session_id: str,
    event_id: str,
    ts: datetime,
    *,
    whatsapp_envelope_lookup: "WhatsAppEnvelopeLookup | None" = None,
) -> ChatReceivedEvent | None:
    content = msg.get("content")
    if not isinstance(content, list) or not content:
        return None
    # Concatenate all text parts; OpenClaw splits a single user prompt
    # across multiple text blocks for some channels.
    parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    if not parts:
        return None
    body = "\n".join(parts)

    if _SLACK_INBOUND_MARKER in body:
        # Slack path — unchanged. Existing tests pin this byte-for-byte.
        match = _JSON_BLOCK_RE.search(body)
        if match is None:
            return None
        try:
            meta = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

        # Extract the actual slack text from the `System: [...] Slack
        # message in #channel from <name>: <text>` line. This is the
        # only field that reliably carries the user-visible body
        # without bootstrap noise or metadata leakage.
        sys_match = _SYSTEM_LINE_RE.search(body)
        cleaned = sys_match.group(1).strip() if sys_match else body.strip()

        return ChatReceivedEvent(
            kind="chat_received",
            session_id=session_id,
            event_id=event_id,
            ts=ts,
            channel_id=str(meta.get("chat_id", "")),
            message_id=str(meta.get("message_id", "")),
            sender_id=str(meta.get("sender_id", "")),
            sender_label=str(meta.get("sender", "")),
            text=cleaned,
            conversation_label=str(meta.get("conversation_label", "")),
        )

    # Not a Slack inbound. Two remaining possibilities:
    #
    # 1. **Synthetic bootstrap prompt** — OpenClaw injects "[Bootstrap
    #    pending]" / "[Bootstrap]" frames at session start. These are
    #    NOT user-authored, so even if a WhatsApp envelope is present
    #    in the recent window we must NOT correlate (or every paired
    #    install would produce a spurious chat_received for whatever
    #    the operator typed last on a different DM). Filter early.
    # 2. **WhatsApp inbound** — OpenClaw 2026.5.6 routes WhatsApp DMs
    #    through the agent without a Slack-style envelope; the raw body
    #    arrives bare (e.g. "sup yo"). We correlate against the daily
    #    log's "Inbound message +<sender> -> +<bot>" envelope cached
    #    by :class:`WhatsAppInboundEnvelopeWatcher`. On hit, emit a
    #    WhatsApp-shaped ChatReceivedEvent.
    #
    # Anything else (unknown bootstrap variant, future channel) returns
    # None — capability honesty, no fabricated sender info.
    body_stripped = body.lstrip()
    for marker in _BOOTSTRAP_MARKERS:
        if body_stripped.startswith(marker):
            return None

    if whatsapp_envelope_lookup is None:
        # No watcher wired — Slack-only deployment. Stay byte-identical
        # with prior behavior: drop the frame.
        return None

    envelope = whatsapp_envelope_lookup(ts, _DEFAULT_WHATSAPP_WINDOW_S)
    if envelope is None:
        return None
    if envelope.chat_type != "direct":
        # Group correlation is not yet supported — the OpenClaw envelope
        # for groups doesn't carry the sender's per-message jid, only
        # the conversation jid. Skip rather than fabricate.
        return None

    cleaned_text = body.strip()
    if not cleaned_text:
        return None

    # Extract @<digits> mentions from the body. Forward as a list of
    # canonical DM jids so the MentionsWorm WhatsApp branch evaluates
    # on real ledger entries; absence stays None per the schema's
    # back-compat default.
    mention_phones = _WHATSAPP_MENTION_RE.findall(cleaned_text)
    mentioned_jids: list[str] | None
    if mention_phones:
        mentioned_jids = [f"{p}@s.whatsapp.net" for p in mention_phones]
    else:
        mentioned_jids = None

    sender_jid = envelope.sender_jid
    # Phone-digit prefix as a placeholder display label until the
    # operator renames the Person via /people. Mirrors B2's discovery
    # display-name convention (``+<phone>``).
    sender_label = sender_jid.split("@", 1)[0]

    return ChatReceivedEvent(
        kind="chat_received",
        session_id=session_id,
        event_id=event_id,
        ts=ts,
        channel_id=sender_jid,  # for DMs, channel == sender's jid
        message_id=event_id,    # session-JSONL frame id; no Baileys correlation cheap
        sender_id=sender_jid,
        sender_label=sender_label,
        text=cleaned_text,
        conversation_label="",
        delivery_mode="push",
        platform_ts=envelope.ts,
        history_sync_id=None,
        mentioned_jids=mentioned_jids,
    )


def _parse_assistant_message(
    _envelope: dict[str, Any],
    msg: dict[str, Any],
    session_id: str,
    event_id: str,
    ts: datetime,
    last_inbound_message_id: str | None,
) -> ChatSentEvent | None:
    stop_reason = msg.get("stopReason")
    if stop_reason != "stop":
        # toolUse, length, or other intermediate stops are not Slack-bound.
        return None

    content = msg.get("content")
    if not isinstance(content, list) or not content:
        return None
    text_parts = [
        c.get("text", "")
        for c in content
        if isinstance(c, dict) and c.get("type") == "text"
    ]
    has_tool_call = any(isinstance(c, dict) and c.get("type") == "toolCall" for c in content)
    if has_tool_call or not text_parts:
        return None

    text = "\n".join(t for t in text_parts if t).strip()
    if not text:
        return None

    return ChatSentEvent(
        kind="chat_sent",
        session_id=session_id,
        event_id=event_id,
        ts=ts,
        text=text,
        in_reply_to=last_inbound_message_id,
    )
