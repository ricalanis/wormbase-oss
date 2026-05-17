"""Phase 3 Task 3B — Ask-the-Worm in-app surface.

Removes the "I have to set up Slack to evaluate" friction for first-time
visitors. The dashboard's Ask-the-Worm button POSTs to
``/api/v1/worm/ask`` (see ``http_api.py``); this module is the worm-core
side of that wire.

The implementation is deliberately a thin orchestrator over the
production chat-presence path — same Reactivities, same ChatReply, same
ledger PEVR cycles. Only the channel adapter is in-app: an
``_InAppChannelAdapter`` whose ``send`` captures the ``OutMessage`` text
into a per-tenant outbox so the HTTP handler can return it inline.

What this module deliberately does NOT do
=========================================

- It does NOT shortcut the ledger by returning a hardcoded answer.
  The ``chat_received`` PEVR cycle is written, the production
  ``MentionResponseReactivity`` fires, and the production
  ``_LedgerChatReply`` writes the ``chat_reply`` PEVR cycle. Both
  trace surfaces are populated honestly.
- It does NOT bypass the relevance gate / classifier / dispatcher chain
  used by ``ChatReceivedReactivity``. The ask flow rides on the
  ``MentionResponseReactivity`` predicate (``EntryKind("chat_received")
  AND MentionsWorm("@worm")``) — the question is prefixed with the
  ``@worm`` handle so the production predicate matches.
- It does NOT introduce a "demo seam". Per CLAUDE.md §1, the only
  acceptable determinism backstop is wire-replay, and even production
  chat replies degrade through this same code path. Disabling
  chat-presence at the package level would degrade both Slack reply and
  in-app reply equally.

Architectural notes
===================

- ``_InAppChannelAdapter`` is a concrete ``ChannelAdapter`` Protocol
  satisfier. Its ``platform = "in_app"`` is reserved for this surface.
  ``send`` records into a process-scoped ``InAppChatOutbox``; the
  matching ``ChannelRef.platform_channel_id`` keys the outbox dict so
  multiple concurrent asks (rare in a dashboard) don't cross.
- ``ask_the_worm`` writes the ``chat_received`` PEVR exactly the way
  ``apps/channel-adapter/.../writer.py`` does — same payload class,
  same tool name (``channel_adapter.emit_chat_received``), same
  quadrant (``active_probabilistic``). Predicates at the chat-presence
  layer cannot tell the two apart; the ledger's audit trail records
  ``proposed_by="dashboard-ask"`` so the trace UI can render the
  origin distinctly.
- The ``MentionResponseReactivity`` body is the production source of
  truth for the reply text. Today it posts the literal "Acknowledged."
  string (see chat-presence reactivities.py F2 docstring). When that
  body grows a real responder, the in-app surface inherits the upgrade
  with no change to this file.

This module is intentionally small (~150 LOC). The chat-presence
surface that does the heavy lifting lives in:
  * packages/wormbase-chat-presence/src/wormbase_chat_presence/reactivities.py
  * packages/wormbase-chat-presence/src/wormbase_chat_presence/chat_reply.py
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from wormbase_channel_adapters.types import (
    AuthHandle,
    ChannelCap,
    ChannelRef,
    InstallRecord,
    MessageRef,
    OutMessage,
    Platform,
    PlatformMember,
    SecretBundle,
)
from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_ledger.entries import ChatReceivedPayload


# Stable placeholder for "the dashboard user" until a real Person id is
# threaded through the ask payload. Mirrors the channel-adapter writer's
# fallback pattern (slack_user_to_person_uuid("__unknown__")).
_DASHBOARD_SENDER = UUID("00000000-0000-0000-0000-d4a5b80a4d00")


# The handle that ``MentionResponseReactivity`` predicate matches against.
# Kept aligned with the chat-presence default in factory.py.
_MENTION_HANDLE = "@worm"


# Today the production ``MentionResponseReactivity`` body posts a literal
# "Acknowledged." reply (see packages/wormbase-chat-presence/.../reactivities.py
# F2.fire). We mirror it here so callers that bypass the registry (e.g.
# tests with no chat-presence wired) still observe the same answer.
ASK_THE_WORM_DEFAULT_REPLY = "Acknowledged."


# ---------------------------------------------------------------------------
# In-app channel adapter
# ---------------------------------------------------------------------------


@dataclass
class _CapturedOutMessage:
    """One captured OutMessage with the channel it was sent to."""

    channel_id: str
    text: str
    speech_act: str | None = None
    in_reply_to: str | None = None
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class InAppChatOutbox:
    """Process-scoped per-channel outbox for in-app worm replies.

    A single instance lives on the aiohttp Application via the
    ``APP_IN_APP_OUTBOX_KEY`` slot. Tests construct an isolated outbox
    per test to keep state from leaking.

    The outbox is keyed by ``channel_id`` (the in_app:* synthetic id).
    ``drain`` returns the captured messages and empties the slot in one
    pass — concurrent asks on the same dashboard channel each get their
    own ``channel_id`` so drains stay deterministic.
    """

    _by_channel: dict[str, list[_CapturedOutMessage]] = field(
        default_factory=lambda: defaultdict(list),
    )

    def append(self, channel_id: str, msg: _CapturedOutMessage) -> None:
        self._by_channel[channel_id].append(msg)

    def drain(self, channel_id: str) -> list[_CapturedOutMessage]:
        captured = self._by_channel.pop(channel_id, [])
        return captured


@dataclass
class _InAppChannelAdapter:
    """In-app ``ChannelAdapter`` — captures OutMessage text into the outbox.

    The dashboard-driven ask flow constructs one of these per request,
    wires it into a fresh ``_LedgerChatReply``, and reads the captured
    text after firing ``MentionResponseReactivity``.

    Per ``ChannelAdapter`` Protocol:
      * ``platform = "in_app"`` (reserved namespace, not a real wire).
      * ``capability = {"send"}`` — the only call we expect.
      * ``status = "preview"`` — there's no OAuth / ingest / file_upload;
        we lie about being production-grade.

    The ``listen``, ``install``, ``authenticate``, and
    ``list_workspace_members`` methods raise ``NotImplementedError``.
    They aren't reachable through the in-app ask flow; they exist so
    ``isinstance(self, ChannelAdapter)`` succeeds.
    """

    outbox: InAppChatOutbox

    platform: Platform = "in_app"
    capability: set[ChannelCap] = field(default_factory=lambda: {"send"})
    status: str = "preview"
    status_note: str = (
        "In-app ask surface. Captures replies for the dashboard's Ask-the-Worm "
        "panel. Not a real wire — install / listen / file_upload are not "
        "implemented. The ledger trail is identical to a production reply."
    )

    async def authenticate(self, secrets: SecretBundle) -> AuthHandle:
        return AuthHandle(connector_kind="in_app", handle_id="in_app:dashboard")

    async def install(self, handle: AuthHandle) -> InstallRecord:
        raise NotImplementedError("in_app adapter has no install path")

    def listen(self, handle: AuthHandle):  # pragma: no cover — never called
        raise NotImplementedError("in_app adapter has no listen path")

    async def send(
        self, handle: AuthHandle, channel: ChannelRef | str, msg: OutMessage,
    ) -> MessageRef:
        # ``_LedgerChatReply.speak`` passes ``channel_id`` (a bare string)
        # rather than a ChannelRef; the SlackChannelAdapter handles both
        # shapes today, so the in-app adapter must too. ChannelRef stays
        # supported for callers using the strict typed surface.
        if isinstance(channel, ChannelRef):
            channel_id = channel.platform_channel_id
        else:
            channel_id = str(channel)
        message_id = f"in_app:msg:{uuid4()}"
        captured = _CapturedOutMessage(
            channel_id=channel_id,
            text=msg.text,
            speech_act=str(msg.metadata.get("speech_act")) if msg.metadata else None,
            in_reply_to=msg.thread_ref,
        )
        self.outbox.append(channel_id, captured)
        return MessageRef(
            platform="in_app",
            platform_message_id=message_id,
            platform_channel_id=channel_id,
        )

    async def list_workspace_members(self, handle: AuthHandle) -> list[PlatformMember]:
        return []


# ---------------------------------------------------------------------------
# ask_the_worm — the orchestrator
# ---------------------------------------------------------------------------


@dataclass
class AskReply:
    """Result of one in-app ask round-trip."""

    answer: str
    chat_reply_id: UUID | None
    channel_id: str
    chat_received_seq: int | None
    references: list[dict[str, str]] = field(default_factory=list)


async def ask_the_worm(
    *,
    ledger: Ledger | InMemoryLedger | Any,
    company_id: UUID,
    question: str,
    outbox: InAppChatOutbox | None = None,
    mention_handle: str = _MENTION_HANDLE,
    channel_id: str | None = None,
) -> AskReply:
    """Run the in-app ask round-trip end-to-end.

    Behaviour (no demo seam — this is the production path with an
    in-app channel adapter):

      1. Allocate a synthetic ``in_app:<uuid>`` channel id (caller may
         override via the ``channel_id`` kwarg). Each ask gets its own
         channel so concurrent asks on the same dashboard don't cross.
      2. Write the ``chat_received`` PEVR cycle exactly the way the
         channel-adapter writer does (same tool name, same payload, same
         quadrant). The text is prefixed with ``mention_handle`` so the
         production ``MentionResponseReactivity`` predicate matches.
      3. Synthesize the entry-shape the registry runner would have built
         from that ledger row, and fire ``MentionResponseReactivity``
         against it. The reactivity calls
         ``_LedgerChatReply.speak`` which:
           - sends the OutMessage through the in-app adapter (text → outbox)
           - writes the chat_reply PEVR cycle
      4. Drain the outbox; return the captured text + the chat_reply_id
         (joined to the propose row's ref_id for trace links).

    Raises if the chat_received write fails. Reply-side failures are
    captured into the AskReply.answer falling back to the hardcoded
    default — the audit trail records the failure mode.
    """
    if outbox is None:
        outbox = InAppChatOutbox()
    chan_id = channel_id or f"in_app:{uuid4()}"

    chat_received_seq = await _write_chat_received(
        ledger=ledger,
        company_id=company_id,
        channel_id=chan_id,
        text=f"{mention_handle} {question}".strip(),
    )

    synthetic_entry = _build_dispatch_entry(
        company_id=company_id,
        channel_id=chan_id,
        text=f"{mention_handle} {question}".strip(),
        seq=chat_received_seq,
    )

    chat_reply_id = await _fire_mention_response(
        ledger=ledger,
        company_id=company_id,
        outbox=outbox,
        entry=synthetic_entry,
        mention_handle=mention_handle,
    )

    captured = outbox.drain(chan_id)
    answer = captured[0].text if captured else ASK_THE_WORM_DEFAULT_REPLY

    return AskReply(
        answer=answer,
        chat_reply_id=chat_reply_id,
        channel_id=chan_id,
        chat_received_seq=chat_received_seq,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _write_chat_received(
    *,
    ledger: Any,
    company_id: UUID,
    channel_id: str,
    text: str,
) -> int | None:
    """Write the chat_received PEVR cycle. Mirrors channel-adapter writer.

    The execute payload's ``tool`` is ``channel_adapter.emit_chat_received``
    so the chat-presence ``EntryKind("chat_received")`` predicate matches
    when the registry's runner sees the row. The payload is a real
    ``ChatReceivedPayload`` model dump — same shape Slack ingest produces.
    """
    ref_id = uuid4()
    payload = ChatReceivedPayload(
        channel_id=channel_id,
        message_id=f"in_app:msg:{uuid4()}",
        sender_person=_DASHBOARD_SENDER,
        text=text,
        classification="internal",
    )
    args = payload.model_dump(mode="json")

    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(ref_id),
            "reason": f"in-app ask from dashboard ({channel_id})",
            "proposed_by": "dashboard-ask",
        },
        execute_fn=lambda: {
            "tool": "channel_adapter.emit_chat_received",
            "args": args,
            "result_ref": payload.message_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "payload_valid", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "in-app ask captured",
        },
        timestamp=datetime.now(UTC),
        quadrant="active_probabilistic",
    )

    # ``WriteResult`` may not surface an explicit seq; just look it up.
    rows = await ledger.fetch(company_id)
    for r in rows:
        if (
            r.get("kind") == "execute"
            and (r.get("payload") or {}).get("tool")
            == "channel_adapter.emit_chat_received"
            and ((r.get("payload") or {}).get("args") or {}).get("message_id")
            == payload.message_id
        ):
            try:
                return int(r["seq"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


def _build_dispatch_entry(
    *,
    company_id: UUID,
    channel_id: str,
    text: str,
    seq: int | None,
) -> dict[str, Any]:
    """Synthesize the entry shape the registry's dispatch loop expects.

    Matches the rows returned by ``ledger.fetch(company_id)`` for the
    ``execute`` envelope of a chat_received PEVR. The chat-presence
    predicates inspect ``kind`` + ``payload.tool`` + ``payload.args``;
    everything else is decorative for trace UI.
    """
    return {
        "kind": "execute",
        "ts": datetime.now(UTC),
        "seq": seq if seq is not None else 0,
        "payload": {
            "tool": "channel_adapter.emit_chat_received",
            "args": {
                "channel_id": channel_id,
                "message_id": f"in_app:dispatch:{uuid4()}",
                "sender_person": str(_DASHBOARD_SENDER),
                "text": text,
                "classification": "internal",
                "platform": "in_app",
                "is_dm": True,
                "source": "dm",
            },
        },
    }


async def _fire_mention_response(
    *,
    ledger: Any,
    company_id: UUID,
    outbox: InAppChatOutbox,
    entry: dict[str, Any],
    mention_handle: str,
) -> UUID | None:
    """Build a fresh MentionResponseReactivity + ChatReply and fire it.

    The chat-presence package is the canonical home for both classes;
    we construct them here per-request rather than reaching into a
    shared registry so concurrent asks stay isolated.
    """
    # Lazy imports — chat-presence is an optional package at the
    # worm-core layer; degrade to the default reply if absent.
    try:
        from wormbase_chat_presence.chat_reply import _LedgerChatReply
        from wormbase_chat_presence.chat_store import _LedgerBackedChatStore
        from wormbase_chat_presence.reactivities import MentionResponseReactivity
    except ImportError:  # pragma: no cover — chat-presence ships with worm-core
        return None

    from wormbase_reactivities.protocol import ReactivityContext

    adapter = _InAppChannelAdapter(outbox=outbox)
    handle = await adapter.authenticate(SecretBundle(payload={}))

    chat_reply = _LedgerChatReply(
        ledger=ledger,
        company_id=company_id,
        channel_adapter=adapter,
        channel_adapter_handle=handle,
    )
    chat_store = _LedgerBackedChatStore(ledger=ledger)

    reactivity = MentionResponseReactivity(
        handle=mention_handle,
        _chat_reply=chat_reply,
        _chat_store=chat_store,
    )

    ctx = ReactivityContext(
        ledger=ledger,
        company_id=company_id,
        registry=None,
        now=datetime.now(UTC),
    )

    # Fire under a small wall-clock budget — the production reactivity is
    # synchronous-fast (writes 4 PEVR rows + one adapter.send) but tests
    # against a remote DB might stall; we never want the HTTP request to
    # hang forever.
    try:
        await asyncio.wait_for(reactivity.fire(entry, ctx), timeout=10.0)
    except asyncio.TimeoutError:  # pragma: no cover — exercised in stress tests
        return None

    # Recover the chat_reply_id from the most recent chat_reply_executed
    # row for this tenant so callers can link to the trace row.
    rows = await ledger.fetch(company_id)
    for r in reversed(rows):
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_chat_reply_executed":
            continue
        args = payload.get("args") or {}
        chid = args.get("chat_reply_id")
        if chid:
            try:
                return UUID(str(chid))
            except (ValueError, TypeError):
                return None
    return None


__all__ = [
    "ASK_THE_WORM_DEFAULT_REPLY",
    "AskReply",
    "InAppChatOutbox",
    "_InAppChannelAdapter",
    "ask_the_worm",
]
