# > AUTHORED 2026-05-03: chat-presence Protocol surface per Block B2.
# > Three Protocols ship: RelevanceGate (W5a-style decider taking the
# > new ConversationContext), ChatReply (production reply primitive that
# > closes the unwired-chat_sender gap in cli.py), ChatStore (substrate-
# > swappable read layer for chat state). All @runtime_checkable so
# > duck-typed satisfiers work via isinstance.
"""Protocols for chat-presence.

Three Protocols ship in this module: RelevanceGate, ChatReply, ChatStore.
ChatPolicy is a frozen dataclass (in types.py) — Protocols are reserved
for behavior surfaces.

All Protocols are @runtime_checkable so tests can assert duck-typed
satisfiers via isinstance().
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from wormbase_core.reactivity import (
    InfraEvent,
    RelevanceDecision,
    SemanticInterpretation,
)

from wormbase_chat_presence.types import (
    ChatMessage,
    ChatPolicy,
    ConversationContext,
    MessageRef,
    SpeechAct,
)


@runtime_checkable
class RelevanceGate(Protocol):
    """Decision: should the worm react to this event?

    Replaces the body of RulesBasedRelevanceGate.handle. Same call surface,
    Protocol-typed. The default impl in chat-worm is _LegacyRulesGate (a
    thin shim around the lifted RulesBasedRelevanceGate body — see
    relevance.py). Future impls may swap in an LLM-driven decider.

    NOTE: this is distinct from the legacy `wormbase_core.reactivity.RelevanceGate`
    (which takes only `infra, interp`). The chat-presence variant takes
    a full `ConversationContext` so the decider can reason about
    channel policy, classification, and is_dm without re-folding the
    ledger inside the gate.
    """

    async def should_react(
        self,
        ctx: ConversationContext,
        msg: InfraEvent,
        interp: SemanticInterpretation,
    ) -> RelevanceDecision: ...


@runtime_checkable
class ChatReply(Protocol):
    """The worm's outbound speech primitive.

    Writes a chat_reply_* PEVR cycle:
      propose("chat_reply_proposed") → execute("chat_reply_executed",
      tool="emit_chat_reply_executed", args={text, speech_act, channel_id,
      message_ref?}) → verify("chat_reply_verified", checks=[
        {"name": "channel_adapter_send_ok", "ok": <send returned a MessageRef>}
      ]) → resolve("chat_reply_resolved", outcome="keep" if sent else "discard").

    The verify step calls ChannelAdapter.send and records its outcome.
    On send failure, resolve outcome is "discard" with a rationale that
    cites the exception. The MessageRef returned by a successful send is
    written into args.message_ref so the channel-adapter's emit_chat_sent
    cycle can be correlated downstream.

    Returns the MessageRef on success, None on failure (caller can decide
    whether to retry).
    """

    async def speak(
        self,
        ctx: ConversationContext,
        text: str,
        *,
        speech_act: SpeechAct,
        in_reply_to: str | None = None,
    ) -> MessageRef | None: ...


@runtime_checkable
class ChatStore(Protocol):
    """Substrate-swappable read layer for chat state.

    v1 impl wraps SQLAlchemy reads against:
      - projection_conversations (already exists, schema.py:79-93)
      - projection_channels (Wave B / migration v005)

    Future swaps (DuckDB, customer Snowflake) port these methods.

    `read_messages` is an async generator (returns an AsyncIterator) so
    callers can stream large channels without materialising the full
    projection in memory. `read_policy` and `count_interjections_today`
    are coroutines because both fold the ledger / projection in a single
    pass and naturally return a single value.
    """

    def read_messages(
        self,
        *,
        company_id: UUID,
        channel_id: str | None = None,
        since: datetime | None = None,
        n: int | None = None,
    ) -> AsyncIterator[ChatMessage]: ...

    async def read_policy(
        self,
        *,
        company_id: UUID,
        channel_id: str,
    ) -> ChatPolicy: ...

    async def count_interjections_today(
        self,
        *,
        company_id: UUID,
        channel_id: str,
        now: datetime,
    ) -> int: ...


__all__ = ["ChatReply", "ChatStore", "RelevanceGate"]
