"""Block B tests — :class:`RouteRequest` / :class:`RouteResponse` shape."""
from __future__ import annotations

from wormbase_inference.protocol import (
    RouteRequest,
    RouteResponse,
    Router,
    default_backend,
)


def test_route_request_is_hashable_and_frozen() -> None:
    req = RouteRequest(
        call_type="reasoning",
        messages=(("user", "hi"),),
        system="be brief",
    )
    # Frozen dataclasses raise on mutation.
    try:
        req.system = "x"  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("RouteRequest should be frozen")
    # Hashable means it can live as a dict key.
    {req: 1}


def test_route_request_messages_as_dicts_prepends_system() -> None:
    req = RouteRequest(
        call_type="reasoning",
        messages=(("user", "ping"),),
        system="answer 'pong'",
    )
    assert req.messages_as_dicts() == [
        {"role": "system", "content": "answer 'pong'"},
        {"role": "user", "content": "ping"},
    ]


def test_route_request_messages_without_system() -> None:
    req = RouteRequest(call_type="classify", messages=(("user", "x"),))
    assert req.messages_as_dicts() == [{"role": "user", "content": "x"}]


def test_route_response_construction() -> None:
    r = RouteResponse(
        text="ok",
        served_by="cache",
        is_fallback=False,
        cache_key="abc",
        latency_ms=5,
        model="kimi-k2.6:cloud",
    )
    assert r.text == "ok"
    assert r.served_by == "cache"
    assert r.is_fallback is False


def test_default_backend_table() -> None:
    assert default_backend("reasoning") == "kimi"
    assert default_backend("affirm") == "kimi"
    assert default_backend("voice_turn") == "kimi"
    assert default_backend("classify") == "gemma"
    assert default_backend("summarize") == "gemma"
    # ``generic`` has no default.
    assert default_backend("generic") is None  # type: ignore[arg-type]


def test_router_is_a_runtime_checkable_protocol() -> None:
    class Fake:
        async def call(self, request):  # type: ignore[no-untyped-def]
            return None

        async def aclose(self) -> None:
            return None

    assert isinstance(Fake(), Router)
