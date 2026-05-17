"""Round-trip tests for the 4 chat_reply_* payload classes."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from wormbase_ledger.entries import (
    ALL_KINDS,
    ChatReplyExecutedPayload,
    ChatReplyProposedPayload,
    ChatReplyResolvedPayload,
    ChatReplyVerifiedPayload,
    KIND_REGISTRY,
)


def test_chat_reply_kinds_registered() -> None:
    for k in (
        "chat_reply_proposed",
        "chat_reply_executed",
        "chat_reply_verified",
        "chat_reply_resolved",
    ):
        assert k in ALL_KINDS, f"{k} not in ALL_KINDS"
        assert k in KIND_REGISTRY, f"{k} not in KIND_REGISTRY"


def test_chat_reply_proposed_payload_round_trip() -> None:
    p = ChatReplyProposedPayload(
        chat_reply_id=uuid4(),
        channel_id="C1",
        speech_act="proposal",
        text="want me to wire up Stripe?",
    )
    d = p.model_dump(mode="json")
    p2 = ChatReplyProposedPayload.model_validate(d)
    assert p2 == p


def test_chat_reply_executed_payload_round_trip() -> None:
    started = datetime.now(UTC)
    ended = started
    p = ChatReplyExecutedPayload(
        chat_reply_id=uuid4(),
        channel_id="C1",
        platform="slack",
        adapter_call_started_at=started,
        adapter_call_ended_at=ended,
    )
    d = p.model_dump(mode="json")
    p2 = ChatReplyExecutedPayload.model_validate(d)
    assert p2 == p


def test_chat_reply_verified_payload_passed() -> None:
    p = ChatReplyVerifiedPayload(
        chat_reply_id=uuid4(),
        passed=True,
        message_ref="slack_msg_123",
    )
    assert p.passed is True
    assert p.error is None


def test_chat_reply_verified_payload_failed() -> None:
    p = ChatReplyVerifiedPayload(
        chat_reply_id=uuid4(),
        passed=False,
        error="rate_limited",
    )
    assert p.passed is False
    assert p.message_ref is None


def test_chat_reply_resolved_outcomes() -> None:
    keep = ChatReplyResolvedPayload(
        chat_reply_id=uuid4(), outcome="keep", rationale="sent ok",
    )
    discard = ChatReplyResolvedPayload(
        chat_reply_id=uuid4(), outcome="discard", rationale="send failed",
    )
    assert keep.outcome == "keep"
    assert discard.outcome == "discard"
