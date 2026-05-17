"""Block G — :class:`DecisionLLMClient` Protocol conformance + parsing."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from wormbase_inference.decision_adapter import (
    DecisionLLMClient,
    _parse_affirm_response,
)
from wormbase_inference.protocol import RouteRequest, RouteResponse


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0.85", 0.85),
        ("0", 0.0),
        ("1.0", 1.0),
        (" 0.5 ", 0.5),
        ("0.500", 0.5),
        ("REJECT", None),
        (" reject ", None),  # case-insensitive REJECT matches
        ("the answer is 0.7", None),  # prose disqualifies
        ("", None),
        ("1.5", None),  # out of range
        ("-0.1", None),  # out of range
        ("nan", None),
    ],
)
def test_parse_affirm_response(raw: str, expected: float | None) -> None:
    assert _parse_affirm_response(raw) == expected


# ---------------------------------------------------------------------------
# Adapter — routes through the Router and returns parsed value.
# ---------------------------------------------------------------------------


@dataclass
class FakeRouter:
    reply: str = "0.9"
    raise_with: Exception | None = None
    calls: list[RouteRequest] = field(default_factory=list)

    async def call(self, request: RouteRequest) -> RouteResponse:
        self.calls.append(request)
        if self.raise_with is not None:
            raise self.raise_with
        return RouteResponse(
            text=self.reply,
            served_by="kimi",
            is_fallback=False,
            cache_key="k",
            latency_ms=0,
            model="kimi-k2.6:cloud",
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_adapter_returns_parsed_confidence() -> None:
    router = FakeRouter(reply="0.85")
    client = DecisionLLMClient(router=router)
    out = await client.affirm_decision(
        text="we'll go with snowflake",
        evidence_message_ids=["m1"],
    )
    assert out == 0.85
    assert len(router.calls) == 1
    req = router.calls[0]
    assert req.call_type == "affirm"
    assert req.system is not None and "REJECT" in req.system
    assert ("user", req.messages[0][1]) == req.messages[0]
    assert "we'll go with snowflake" in req.messages[0][1]


@pytest.mark.asyncio
async def test_adapter_returns_none_on_reject() -> None:
    router = FakeRouter(reply="REJECT")
    client = DecisionLLMClient(router=router)
    out = await client.affirm_decision(text="hello", evidence_message_ids=[])
    assert out is None


@pytest.mark.asyncio
async def test_adapter_returns_none_on_router_failure() -> None:
    router = FakeRouter(raise_with=RuntimeError("router exploded"))
    client = DecisionLLMClient(router=router)
    out = await client.affirm_decision(
        text="x", evidence_message_ids=["m1", "m2"]
    )
    assert out is None


@pytest.mark.asyncio
async def test_adapter_satisfies_process_extractor_llmclient_protocol() -> None:
    """Block G — the adapter is the in-tree :class:`LLMClient`.

    ``wormbase_process_extractor.decisions.LLMClient`` is a runtime-checkable
    Protocol; the adapter's static signature must match.
    """
    from wormbase_process_extractor.decisions import LLMClient

    router = FakeRouter(reply="0.7")
    client = DecisionLLMClient(router=router)
    assert isinstance(client, LLMClient)
    out = await client.affirm_decision(text="t", evidence_message_ids=["m"])
    assert out == 0.7


@pytest.mark.asyncio
async def test_adapter_passes_evidence_count_in_extra() -> None:
    router = FakeRouter(reply="0.5")
    client = DecisionLLMClient(router=router)
    await client.affirm_decision(
        text="x", evidence_message_ids=["a", "b", "c"]
    )
    extra = dict(router.calls[0].extra)
    assert extra.get("evidence_count") == "3"
