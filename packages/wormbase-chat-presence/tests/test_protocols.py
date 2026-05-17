"""Protocol shape smoke tests."""
from __future__ import annotations

from typing import Any

from wormbase_chat_presence.protocols import (
    ChatReply,
    ChatStore,
    RelevanceGate,
)


def test_relevance_gate_runtime_checkable() -> None:
    """A duck-typed object satisfies RelevanceGate."""

    class _FakeGate:
        async def should_react(self, ctx: Any, msg: Any, interp: Any) -> Any:
            return None

    assert isinstance(_FakeGate(), RelevanceGate)


def test_chat_reply_runtime_checkable() -> None:
    class _FakeReply:
        async def speak(
            self, ctx: Any, text: str, *, speech_act: str,
            in_reply_to: str | None = None,
        ) -> Any:
            return None

    assert isinstance(_FakeReply(), ChatReply)


def test_chat_store_runtime_checkable() -> None:
    class _FakeStore:
        async def read_messages(self, **kwargs: Any) -> Any:  # noqa: ARG002
            yield  # AsyncIterator

        async def read_policy(self, **kwargs: Any) -> Any:  # noqa: ARG002
            return None

        async def count_interjections_today(self, **kwargs: Any) -> int:  # noqa: ARG002
            return 0

    assert isinstance(_FakeStore(), ChatStore)
