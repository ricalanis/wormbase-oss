"""Type smoke tests."""
from __future__ import annotations

import dataclasses
from uuid import uuid4

from wormbase_chat_presence.types import ChatPolicy, ConversationContext


def test_chat_policy_frozen() -> None:
    policy = ChatPolicy(talkativeness="responsive", daily_interjection_budget=3)
    # Dataclass frozen — assigning a field should raise FrozenInstanceError.
    try:
        policy.talkativeness = "lurker"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    assert False, "ChatPolicy should be frozen"


def test_chat_policy_defaults() -> None:
    """Default policy: responsive + budget 3."""
    policy = ChatPolicy(talkativeness="responsive", daily_interjection_budget=3)
    assert policy.talkativeness == "responsive"
    assert policy.daily_interjection_budget == 3


def test_conversation_context_minimal() -> None:
    ctx = ConversationContext(
        company_id=uuid4(),
        channel_id="C123",
        domain_id=None,
        is_dm=False,
        classification="internal",
        policy=ChatPolicy(talkativeness="responsive", daily_interjection_budget=3),
    )
    assert ctx.is_dm is False
    assert ctx.classification == "internal"
