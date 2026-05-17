"""wire_chat_for_install — boot-time chat-worm wiring.

Constructs the chat-worm internal services (ChatStore, ChatReply,
RelevanceGate); builds the dispatcher; constructs the four Reactivities
via make_chat_reactivities; registers them on the worm-core
ReactivityRegistry. Returns a ChatBundle with the dispatcher + chat_reply
+ chat_store handles for cli.py to thread into the poller.

Mirrors lake-maintainer's wire_maintenance_for_source shape
(packages/lake-maintainer/src/wormbase_lake_maintainer/registry.py:54-79)
and identity-tracker's wire_identity_for_install shape
(packages/wormbase-identity-tracker/src/wormbase_identity_tracker/lifecycle.py:35-60).

Block G2 of the chat-worm extraction plan
(docs/superpowers/plans/2026-05-03-chat-worm-extraction.md, lines 3911-4161).

Per O-B2 (deferred-backlog Block C, 2026-05-04): chat-worm Reactivities
take their services via factory kwargs (constructor injection), unifying
the production path (cli.py) and the test path. The wire helper still
RETURNS the services in the bundle so callers (cli.py) can thread the
dispatcher into the chat_received_reactivity_poller's flow_dispatcher
kwarg, but Reactivities themselves no longer read from
`ReactivityContext.extras`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from wormbase_chat_presence.chat_reply import _LedgerChatReply
from wormbase_chat_presence.chat_store import _LedgerBackedChatStore
from wormbase_chat_presence.dispatcher import make_chat_dispatcher
from wormbase_chat_presence.factory import make_chat_reactivities
from wormbase_chat_presence.protocols import ChatReply, ChatStore, RelevanceGate
from wormbase_chat_presence.relevance import RulesBasedRelevanceGate
from wormbase_ledger import InMemoryLedger, Ledger


@dataclass
class ChatBundle:
    """Result of wire_chat_for_install — the chat-worm public handles.

    Caller (cli.py) threads `dispatcher` into chat_received_reactivity_poller's
    flow_dispatcher kwarg. `chat_reply`, `chat_store`, `relevance_gate` are
    exposed for downstream wiring (extras injection, dashboard reads, etc.).
    """

    dispatcher: Any  # async (event, decision) -> None
    chat_reply: ChatReply
    chat_store: ChatStore
    relevance_gate: RelevanceGate


async def wire_chat_for_install(
    *,
    install: Any,
    ledger: Ledger | InMemoryLedger,
    reactivity_registry: Any,
    drop_and_profile: Any,
    credential_in_dm: Any,
    mentioned_in_conversation: Any,
    channel_adapter: Any | None = None,
    channel_adapter_handle: Any | None = None,
    mention_handle: str = "@worm",
    semantic_classifier: Any | None = None,
    cascade: Any | None = None,
) -> ChatBundle:
    """Wire chat-worm into one Install's runtime.

    Side effects:
      1. Constructs ChatStore, ChatReply, RelevanceGate.
      2. Builds the chat dispatcher (delegates to the four chat-driven flows).
      3. Constructs four Reactivities and registers each on the registry.
      4. Returns the ChatBundle for the caller to thread into the
         chat_received_reactivity_poller's flow_dispatcher kwarg.

    `channel_adapter` + `channel_adapter_handle` are the runtime path for
    ChatReply.speak. When None, ChatReply degrades gracefully — Block H's
    full impl writes the PEVR cycle but the verify step records
    `channel_adapter_unavailable`; G2's stub simply logs and returns None.

    `cascade` is an optional ``async (infra, correlation_id) -> None``
    adapter that fires the medallion bronze→silver→gold chain after a
    file_drop's propose lands. cli.py wires it via cascade_after_propose
    + MedallionCascade (O-B1, deferred-backlog Block D). When ``None``
    the chat dispatcher behaves as the legacy Wave-B-extracted shape —
    propose only, no cascade.

    `install` is duck-typed in v1 (no formal Install dataclass yet — same
    posture as identity-worm Wave A). The factory reads `install.id` for
    company_id; `install.platform` is reserved for future platform-aware
    wiring.
    """
    company_id: UUID = install.id

    chat_store = _LedgerBackedChatStore(ledger=ledger)
    chat_reply = _LedgerChatReply(
        ledger=ledger,
        company_id=company_id,
        channel_adapter=channel_adapter,
        channel_adapter_handle=channel_adapter_handle,
    )
    # The legacy RulesBasedRelevanceGate satisfies the new RelevanceGate
    # Protocol (the chat-presence Protocol takes the new ConversationContext
    # signature). Future impls may swap in an LLM-driven decider; the
    # wrapper is a small adapter at the call-site (Block F1's
    # ChatReceivedReactivity already handles both signatures).
    relevance_gate = RulesBasedRelevanceGate(
        ledger=ledger,
        company_id=company_id,
        mention_handle=mention_handle,
    )

    dispatcher = make_chat_dispatcher(
        drop_and_profile=drop_and_profile,
        credential_in_dm=credential_in_dm,
        mentioned_in_conversation=mentioned_in_conversation,
        company_id=company_id,
        cascade=cascade,
    )

    # Per O-B2: services thread through factory kwargs; Reactivities store
    # them as instance attrs and consume them in fire() instead of reading
    # from ReactivityContext.extras. semantic_classifier is optional —
    # production wires it in a later wave; when absent ChatReceivedReactivity
    # short-circuits with fired=False and the chat triad is observation-only.
    reactivities = make_chat_reactivities(
        install=install,
        mention_handle=mention_handle,
        chat_reply=chat_reply,
        chat_store=chat_store,
        relevance_gate=relevance_gate,
        flow_dispatcher=dispatcher,
        semantic_classifier=semantic_classifier,
        mentioned_in_conversation_flow=mentioned_in_conversation,
    )
    for r in reactivities:
        reactivity_registry.register(r)

    return ChatBundle(
        dispatcher=dispatcher,
        chat_reply=chat_reply,
        chat_store=chat_store,
        relevance_gate=relevance_gate,
    )


__all__ = ["ChatBundle", "wire_chat_for_install"]
