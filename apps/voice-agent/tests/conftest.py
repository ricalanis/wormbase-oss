"""Shared pytest fixtures for the voice-agent test suite."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID, uuid5

import pytest

from wormbase_ledger import InMemoryLedger

WORMBASE_TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")


@pytest.fixture
def baseworm_company_id() -> UUID:
    return uuid5(WORMBASE_TENANT_NAMESPACE, "baseworm")


@pytest.fixture
def in_memory_ledger() -> InMemoryLedger:
    return InMemoryLedger()


class FakeKimi:
    """Stand-in for :class:`KimiOllamaClient` that records calls."""

    def __init__(self, *, reply: str = "Q3 net revenue was four point two million dollars."):
        self._reply = reply
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        self.calls.append(list(messages))
        return self._reply


@pytest.fixture
def fake_kimi() -> FakeKimi:
    return FakeKimi()
