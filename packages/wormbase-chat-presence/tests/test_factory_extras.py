"""make_chat_reactivities accepts chat-worm services as constructor kwargs.

Block C of the deferred-backlog plan
(`docs/superpowers/plans/2026-05-04-deferred-backlog.md`, lines 315-371).

Per the spike recommendation (Option A — factory kwargs), chat-worm
Reactivities take their service dependencies (`chat_reply`, `chat_store`,
`relevance_gate`, `flow_dispatcher`, `semantic_classifier`,
`mentioned_in_conversation_flow`) at construction time rather than reading
them from `ReactivityContext.extras` on every fire.

The W5a registry's stock dispatch still injects
`extras={"reactivity_id": rid}` only; this test pins that the factory
accepts the service kwargs and threads them onto each Reactivity instance
that consumes them, replacing the test-bridge `_patch_registry_extras`
seam in `tests/integration/test_chat_worm_e2e.py`.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from wormbase_chat_presence import Install, make_chat_reactivities


def test_make_chat_reactivities_accepts_services_directly() -> None:
    install = Install(id=uuid4(), platform="slack")
    chat_reply = MagicMock(name="chat_reply")
    chat_store = MagicMock(name="chat_store")
    relevance_gate = MagicMock(name="relevance_gate")
    flow_dispatcher = MagicMock(name="flow_dispatcher")
    semantic_classifier = MagicMock(name="semantic_classifier")
    mentioned_flow = MagicMock(name="mentioned_in_conversation_flow")

    reactivities = make_chat_reactivities(
        install=install,
        mention_handle="@worm",
        chat_reply=chat_reply,
        chat_store=chat_store,
        relevance_gate=relevance_gate,
        flow_dispatcher=flow_dispatcher,
        semantic_classifier=semantic_classifier,
        mentioned_in_conversation_flow=mentioned_flow,
    )

    by_id: dict[str, Any] = {r.id: r for r in reactivities}

    # ChatReceivedReactivity uses chat_store, relevance_gate,
    # semantic_classifier, flow_dispatcher.
    chat_received = by_id["chat_received"]
    assert chat_received._chat_store is chat_store
    assert chat_received._relevance_gate is relevance_gate
    assert chat_received._semantic_classifier is semantic_classifier
    assert chat_received._flow_dispatcher is flow_dispatcher

    # MentionResponseReactivity uses chat_reply + chat_store.
    mention = by_id["mention_response"]
    assert mention._chat_reply is chat_reply
    assert mention._chat_store is chat_store

    # InterjectionBudgetReactivity uses chat_store only.
    interjection = by_id["interjection_budget"]
    assert interjection._chat_store is chat_store

    # SourceMentionedReactivity uses chat_store, chat_reply, mentioned flow.
    source_mentioned = by_id["source_mentioned"]
    assert source_mentioned._chat_store is chat_store
    assert source_mentioned._chat_reply is chat_reply
    assert source_mentioned._mentioned_in_conversation_flow is mentioned_flow


def test_make_chat_reactivities_omitted_kwargs_default_to_none() -> None:
    """Backwards compat: factory may be called without service kwargs.

    When omitted, each Reactivity stores `None` for the missing service
    and `fire()` short-circuits with `fired=False` (existing behavior
    preserved from the extras-driven path).
    """
    install = Install(id=uuid4(), platform="slack")
    reactivities = make_chat_reactivities(
        install=install, mention_handle="@worm",
    )
    assert len(reactivities) == 4

    by_id = {r.id: r for r in reactivities}
    assert by_id["chat_received"]._chat_store is None
    assert by_id["chat_received"]._relevance_gate is None
    assert by_id["chat_received"]._semantic_classifier is None
    assert by_id["chat_received"]._flow_dispatcher is None
    assert by_id["mention_response"]._chat_reply is None
    assert by_id["mention_response"]._chat_store is None
    assert by_id["interjection_budget"]._chat_store is None
    assert by_id["source_mentioned"]._chat_store is None
    assert by_id["source_mentioned"]._chat_reply is None
    assert by_id["source_mentioned"]._mentioned_in_conversation_flow is None
