"""Factory for the four chat-worm Reactivities.

Per the lake-maintainer template (`packages/lake-maintainer/src/wormbase_lake_maintainer/factory.py`),
the factory is the single point of construction so the four-instance
cardinality is enforced structurally — no caller can register, say, just
ChatReceivedReactivity and forget the others.

The order is fixed: chat_received, mention_response, interjection_budget,
source_mentioned. Caller-side telemetry can rely on this order.

Services (`chat_reply`, `chat_store`, `relevance_gate`, `flow_dispatcher`,
`semantic_classifier`, `mentioned_in_conversation_flow`) are accepted as
factory kwargs and threaded into each Reactivity that consumes them
(O-B2 — Option A constructor injection, 2026-05-04). When omitted, each
Reactivity stores None and `fire()` short-circuits with `fired=False`,
which preserves the misconfigured-wiring guard from the previous
extras-driven path.
"""
from __future__ import annotations

from typing import Any

from wormbase_chat_presence.reactivities import (
    ChatReceivedReactivity,
    InterjectionBudgetReactivity,
    MentionResponseReactivity,
    SourceMentionedReactivity,
)
from wormbase_reactivities.protocol import Reactivity


def make_chat_reactivities(
    *,
    install: Any,
    mention_handle: str = "@worm",
    chat_reply: Any = None,
    chat_store: Any = None,
    relevance_gate: Any = None,
    flow_dispatcher: Any = None,
    semantic_classifier: Any = None,
    mentioned_in_conversation_flow: Any = None,
) -> list[Reactivity]:
    """Return the four chat-worm Reactivities for one Install.

    `install` is the typed `wormbase_chat_presence.Install` dataclass
    (O-A2, 2026-05-04) — a frozen record with id/platform plus optional
    installer_person_id and bot_user_id. The `Any` annotation is kept on
    the parameter so external callers can pass shaped duck-types during
    migration windows; downstream consumers only read `.id`/`.platform`.

    `mention_handle` is the @-mention string MentionResponseReactivity
    uses. Defaults to "@worm" matching the legacy RulesBasedRelevanceGate
    default.

    Service kwargs are threaded into each Reactivity that consumes them:
      - ChatReceivedReactivity: chat_store, relevance_gate,
        semantic_classifier, flow_dispatcher
      - MentionResponseReactivity: chat_reply, chat_store
      - InterjectionBudgetReactivity: chat_store
      - SourceMentionedReactivity: chat_store, chat_reply,
        mentioned_in_conversation_flow

    Defaulting each to None preserves backwards compat with callers (and
    legacy tests) that previously injected services via the extras dict.
    """
    return [
        ChatReceivedReactivity(
            _chat_store=chat_store,
            _relevance_gate=relevance_gate,
            _semantic_classifier=semantic_classifier,
            _flow_dispatcher=flow_dispatcher,
        ),
        MentionResponseReactivity(
            handle=mention_handle,
            _chat_reply=chat_reply,
            _chat_store=chat_store,
        ),
        InterjectionBudgetReactivity(
            _chat_store=chat_store,
        ),
        SourceMentionedReactivity(
            _chat_store=chat_store,
            _chat_reply=chat_reply,
            _mentioned_in_conversation_flow=mentioned_in_conversation_flow,
        ),
    ]


__all__ = ["make_chat_reactivities"]
