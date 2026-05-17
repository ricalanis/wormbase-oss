"""Topic-labeler adapter — :class:`TopicLabelerLLMClient` Protocol conformance.

Phase 2 Task 2B (Wave H): the production adapter that satisfies the
``TopicLabeler`` Protocol declared in
``wormbase_process_extractor.reactivities``. Routes label_topic calls
through a :class:`Router` (default Gemma via ``call_type="summarize"``)
and parses the response into a ``(label, confidence, served_by)``
triple.

The adapter is wired into ``ReactivityContext.extras["topic_labeler"]``
by the process-extractor factory (Block G.1) when the inference router
is available; tests inject a ``FakeRouter`` directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from wormbase_inference.protocol import RouteRequest, RouteResponse
from wormbase_inference.topic_labeler_adapter import (
    TopicLabelerLLMClient,
    _parse_label_response,
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Q3 finance reporting", "Q3 finance reporting"),
        ("  Q3 reporting  ", "Q3 reporting"),
        ("", None),
        ("   ", None),
        # Long replies are truncated to the payload max (256 chars).
        ("x" * 300, "x" * 256),
        # Reject token short-circuits.
        ("REJECT", None),
        ("reject", None),
    ],
)
def test_parse_label_response(raw: str, expected: str | None) -> None:
    assert _parse_label_response(raw) == expected


# ---------------------------------------------------------------------------
# Adapter — routes through the Router
# ---------------------------------------------------------------------------


@dataclass
class FakeRouter:
    reply: str = "Q3 finance reporting"
    served_by: str = "gemma"
    raise_with: Exception | None = None
    calls: list[RouteRequest] = field(default_factory=list)

    async def call(self, request: RouteRequest) -> RouteResponse:
        self.calls.append(request)
        if self.raise_with is not None:
            raise self.raise_with
        return RouteResponse(
            text=self.reply,
            served_by=self.served_by,  # type: ignore[arg-type]
            is_fallback=False,
            cache_key="k",
            latency_ms=0,
            model="gemma4:e4b",
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_adapter_returns_label_confidence_served_by() -> None:
    router = FakeRouter(reply="Q3 finance reporting", served_by="gemma")
    client = TopicLabelerLLMClient(router=router)
    out = await client.label_topic(
        cluster_signature="q3 finance reporting cadence",
        sample_messages=["What's our Q3 finance cadence?"],
        member_message_ids=["M-1", "M-2"],
    )
    assert out is not None
    label, confidence, served_by = out
    assert label == "Q3 finance reporting"
    # Default confidence floor for router-blessed labels.
    assert 0.0 <= confidence <= 1.0
    assert confidence >= 0.7  # router-blessed should be above heuristic floor
    assert served_by == "gemma"


@pytest.mark.asyncio
async def test_adapter_returns_none_on_empty_reply() -> None:
    router = FakeRouter(reply="")
    client = TopicLabelerLLMClient(router=router)
    out = await client.label_topic(
        cluster_signature="x",
        sample_messages=[],
        member_message_ids=[],
    )
    assert out is None


@pytest.mark.asyncio
async def test_adapter_returns_none_on_reject() -> None:
    router = FakeRouter(reply="REJECT")
    client = TopicLabelerLLMClient(router=router)
    out = await client.label_topic(
        cluster_signature="x",
        sample_messages=[],
        member_message_ids=[],
    )
    assert out is None


@pytest.mark.asyncio
async def test_adapter_returns_none_on_router_failure() -> None:
    router = FakeRouter(raise_with=RuntimeError("router exploded"))
    client = TopicLabelerLLMClient(router=router)
    out = await client.label_topic(
        cluster_signature="x",
        sample_messages=["hello"],
        member_message_ids=["M-1"],
    )
    assert out is None


@pytest.mark.asyncio
async def test_adapter_uses_summarize_call_type_by_default() -> None:
    """Default route is ``call_type="summarize"`` → Gemma.

    Topic labeling is high-volume commodity work — Gemma's the right
    backend per the routing table in protocol.py.
    """
    router = FakeRouter()
    client = TopicLabelerLLMClient(router=router)
    await client.label_topic(
        cluster_signature="q3 finance reporting",
        sample_messages=["sample"],
        member_message_ids=["M-1"],
    )
    assert len(router.calls) == 1
    req = router.calls[0]
    assert req.call_type == "summarize"
    assert req.backend_hint == "auto"  # router decides; default = Gemma


@pytest.mark.asyncio
async def test_adapter_passes_member_count_in_extra() -> None:
    """``extra`` carries member_count for cache + ledger provenance."""
    router = FakeRouter(reply="label")
    client = TopicLabelerLLMClient(router=router)
    await client.label_topic(
        cluster_signature="x",
        sample_messages=["a", "b"],
        member_message_ids=["M-1", "M-2", "M-3"],
    )
    extra = dict(router.calls[0].extra)
    assert extra.get("member_count") == "3"


@pytest.mark.asyncio
async def test_adapter_satisfies_topic_labeler_protocol() -> None:
    """The adapter satisfies the in-tree ``TopicLabeler`` Protocol."""
    from wormbase_process_extractor.reactivities import TopicLabeler

    router = FakeRouter(reply="some label")
    client = TopicLabelerLLMClient(router=router)
    assert isinstance(client, TopicLabeler)
    out = await client.label_topic(
        cluster_signature="sig",
        sample_messages=["hi"],
        member_message_ids=["M-1"],
    )
    assert out is not None
    assert out[0] == "some label"
