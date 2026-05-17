"""make_chat_dispatcher routes drop/mention/credential branches."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from wormbase_chat_presence.dispatcher import make_chat_dispatcher
from wormbase_core.reactivity import RelevanceDecision


@pytest.mark.asyncio
async def test_dispatcher_routes_file_drop() -> None:
    routed: list[str] = []

    class _Drop:
        async def on_file_drop(self, infra: Any) -> Any:
            routed.append("file_drop")
            return None

    class _Cred:
        async def on_dm(self, infra: Any) -> Any:
            routed.append("credential")
            return None

    class _Mention:
        async def on_proactive_mention(self, infra: Any) -> Any:
            routed.append("mention")
            return None

    dispatcher = make_chat_dispatcher(
        drop_and_profile=_Drop(),
        credential_in_dm=_Cred(),
        mentioned_in_conversation=_Mention(),
        company_id=uuid4(),
    )
    decision = RelevanceDecision(
        should_react=True, reason="file", suggested_flow="drop_and_profile",
    )
    event = {
        "type": "file_drop",
        "ts": datetime.now(UTC),
        "channel_id": "C1",
        "user_id": str(uuid4()),
        "text": "",
        "message_id": "msg",
        "company_id": str(uuid4()),
        "payload": {"files": [{"filename": "data.csv"}]},
    }
    await dispatcher(event, decision)
    assert "file_drop" in routed


@pytest.mark.asyncio
async def test_dispatcher_routes_credential_in_dm() -> None:
    routed: list[str] = []

    class _Drop:
        async def on_file_drop(self, infra: Any) -> Any:
            routed.append("file_drop")
            return None

    class _Cred:
        async def on_dm(self, infra: Any) -> Any:
            routed.append("credential")
            return None

    class _Mention:
        async def on_proactive_mention(self, infra: Any) -> Any:
            routed.append("mention")
            return None

    dispatcher = make_chat_dispatcher(
        drop_and_profile=_Drop(),
        credential_in_dm=_Cred(),
        mentioned_in_conversation=_Mention(),
        company_id=uuid4(),
    )
    decision = RelevanceDecision(
        should_react=True,
        reason="cred",
        suggested_flow="credential_offered_in_dm",
    )
    event = {
        "type": "dm",
        "ts": datetime.now(UTC),
        "channel_id": "D1",
        "user_id": str(uuid4()),
        "text": "postgres://...",
        "message_id": "msg2",
        "company_id": str(uuid4()),
        "payload": {},
    }
    await dispatcher(event, decision)
    assert routed == ["credential"]


@pytest.mark.asyncio
async def test_dispatcher_routes_mentioned_in_conversation() -> None:
    routed: list[str] = []

    class _Drop:
        async def on_file_drop(self, infra: Any) -> Any:
            routed.append("file_drop")

    class _Cred:
        async def on_dm(self, infra: Any) -> Any:
            routed.append("credential")

    class _Mention:
        async def on_proactive_mention(self, infra: Any) -> Any:
            routed.append("mention")
            return None

    dispatcher = make_chat_dispatcher(
        drop_and_profile=_Drop(),
        credential_in_dm=_Cred(),
        mentioned_in_conversation=_Mention(),
        company_id=uuid4(),
    )
    decision = RelevanceDecision(
        should_react=True,
        reason="kw",
        suggested_flow="mentioned_in_conversation",
    )
    event = {
        "type": "channel_message",
        "ts": datetime.now(UTC),
        "channel_id": "C9",
        "user_id": str(uuid4()),
        "text": "We should look at salesforce data",
        "message_id": "m9",
        "company_id": str(uuid4()),
        "payload": {},
    }
    await dispatcher(event, decision)
    assert routed == ["mention"]


@pytest.mark.asyncio
async def test_dispatcher_no_op_when_should_react_false() -> None:
    routed: list[str] = []

    class _Drop:
        async def on_file_drop(self, infra: Any) -> Any:
            routed.append("file_drop")

    class _Cred:
        async def on_dm(self, infra: Any) -> Any:
            routed.append("credential")

    class _Mention:
        async def on_proactive_mention(self, infra: Any) -> Any:
            routed.append("mention")

    dispatcher = make_chat_dispatcher(
        drop_and_profile=_Drop(),
        credential_in_dm=_Cred(),
        mentioned_in_conversation=_Mention(),
        company_id=uuid4(),
    )
    decision = RelevanceDecision(
        should_react=False,
        reason="lurking",
        suggested_flow="drop_and_profile",
    )
    event = {
        "type": "file_drop",
        "ts": datetime.now(UTC),
        "channel_id": "C1",
        "user_id": str(uuid4()),
        "text": "",
        "message_id": "msg",
        "company_id": str(uuid4()),
        "payload": {},
    }
    await dispatcher(event, decision)
    assert routed == []


@pytest.mark.asyncio
async def test_dispatcher_swallows_flow_exceptions() -> None:
    """A flow that raises must not propagate to the poller."""

    class _Drop:
        async def on_file_drop(self, infra: Any) -> Any:
            raise RuntimeError("boom")

    class _Cred:
        async def on_dm(self, infra: Any) -> Any:
            return None

    class _Mention:
        async def on_proactive_mention(self, infra: Any) -> Any:
            return None

    dispatcher = make_chat_dispatcher(
        drop_and_profile=_Drop(),
        credential_in_dm=_Cred(),
        mentioned_in_conversation=_Mention(),
        company_id=uuid4(),
    )
    decision = RelevanceDecision(
        should_react=True, reason="file", suggested_flow="drop_and_profile",
    )
    event = {
        "type": "file_drop",
        "ts": datetime.now(UTC),
        "channel_id": "C1",
        "user_id": str(uuid4()),
        "text": "",
        "message_id": "msg",
        "company_id": str(uuid4()),
        "payload": {},
    }
    # Must not raise.
    await dispatcher(event, decision)
