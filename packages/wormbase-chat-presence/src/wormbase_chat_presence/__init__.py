"""WormBase ChatPresence — the chat-worm.

See `docs/superpowers/notes/2026-05-03-chat-worm-phase-0-spike.md` for the
architecture (GO-WITH-CAVEATS) and `docs/superpowers/plans/2026-05-03-chat-worm-extraction.md`
for the implementation plan.

Public surface (frozen after Wave B landing):

- ``ChatPolicy``, ``ConversationContext`` — value types (frozen)
- ``RelevanceGate``, ``ChatReply``, ``ChatStore`` — Protocols
- ``ChatReceivedReactivity``, ``MentionResponseReactivity``,
  ``InterjectionBudgetReactivity``, ``SourceMentionedReactivity`` — Reactivities
- ``MentionsWorm``, ``DataKeywordMatch`` — chat-worm-private W5a predicates
- ``make_chat_reactivities`` — factory: list[Reactivity] for an Install
- ``make_chat_dispatcher`` — flow_dispatcher seam for the worm-core poller
- ``wire_chat_for_install`` — lifecycle factory

Internal-only:
- ``classifier`` — Stub/Ollama/SemanticClassifier impls (chat-worm-private)
- ``setup_dm_driver`` — DM driver primitives (consumed by worm-core's onboarding)
- ``chat_flows.*`` — DropAndProfile / CredentialInDm / MentionedInConversation /
  KpiGapTriggered (all chat-driven)

Re-exports below; full surface area lives in the per-module files.
"""
from __future__ import annotations

from wormbase_chat_presence.chat_reply import _LedgerChatReply
from wormbase_chat_presence.chat_store import _LedgerBackedChatStore
from wormbase_chat_presence.predicates import DataKeywordMatch, MentionsWorm
from wormbase_chat_presence.presence import ConversationContract, Presence
from wormbase_chat_presence.protocols import ChatReply, ChatStore, RelevanceGate
from wormbase_chat_presence.relevance import (
    RulesBasedRelevanceGate,
    Talkativeness as RelevanceTalkativeness,  # alias to avoid clash with types.Talkativeness
)
from wormbase_chat_presence.types import (
    ChatMessage,
    ChatPolicy,
    ConversationContext,
    Install,
    MessageRef,
    SpeechAct,
    Talkativeness,
)

__all__ = [
    "ChatMessage",
    "ChatPolicy",
    "ChatReply",
    "ChatStore",
    "ConversationContext",
    "ConversationContract",
    "DataKeywordMatch",
    "Install",
    "MentionsWorm",
    "MessageRef",
    "Presence",
    "RelevanceGate",
    "RelevanceTalkativeness",
    "RulesBasedRelevanceGate",
    "SpeechAct",
    "Talkativeness",
    "_LedgerBackedChatStore",
    "_LedgerChatReply",
]

from wormbase_chat_presence.dispatcher import make_chat_dispatcher
from wormbase_chat_presence.factory import make_chat_reactivities
from wormbase_chat_presence.lifecycle import ChatBundle, wire_chat_for_install

__all__ += [
    "ChatBundle",
    "make_chat_dispatcher",
    "make_chat_reactivities",
    "wire_chat_for_install",
]
