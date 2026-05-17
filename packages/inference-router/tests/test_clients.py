"""Blocks C + D — :class:`KimiClient` / :class:`GemmaClient` tests.

Real HTTP is mocked via :class:`httpx.MockTransport`; no network calls.
Real-LLM tests are env-skipped; see ``test_clients_live.py`` for those.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from wormbase_inference.clients import (
    DEFAULT_GEMMA_MODEL,
    DEFAULT_KIMI_MODEL,
    DEFAULT_OLLAMA_BASE,
    DEFAULT_OLLAMA_OWN_BASE,
    GemmaClient,
    InferenceClient,
    InferenceError,
    KimiClient,
)


def _ollama_response(text: str) -> dict[str, Any]:
    return {"message": {"role": "assistant", "content": text}}


# ---------------------------------------------------------------------------
# KimiClient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kimi_client_calls_ollama_cloud_with_bearer() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_ollama_response("hello kimi"))

    client = KimiClient(
        api_key="sk-test",
        base_url=DEFAULT_OLLAMA_BASE,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    out = await client.chat([{"role": "user", "content": "hi"}])
    assert out == "hello kimi"
    assert captured["url"] == f"{DEFAULT_OLLAMA_BASE}/api/chat"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == DEFAULT_KIMI_MODEL
    assert captured["body"]["stream"] is False
    await client.aclose()


@pytest.mark.asyncio
async def test_kimi_client_satisfies_protocol() -> None:
    c = KimiClient(api_key="x")
    assert isinstance(c, InferenceClient)
    assert c.name == "kimi"


@pytest.mark.asyncio
async def test_kimi_client_raises_when_api_key_missing() -> None:
    client = KimiClient(api_key=None)
    with pytest.raises(InferenceError, match="OLLAMA_API_KEY"):
        await client.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_kimi_client_propagates_http_error_as_inference_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    client = KimiClient(
        api_key="sk",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(InferenceError, match="http error"):
        await client.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_kimi_client_raises_on_empty_content() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "  "}})

    client = KimiClient(
        api_key="sk",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(InferenceError, match="empty"):
        await client.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_kimi_client_passes_temperature_and_max_tokens() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_ollama_response("ok"))

    client = KimiClient(
        api_key="sk",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await client.chat(
        [{"role": "user", "content": "hi"}],
        temperature=0.7,
        max_tokens=128,
    )
    assert captured["body"]["temperature"] == 0.7
    assert captured["body"]["max_tokens"] == 128


# ---------------------------------------------------------------------------
# GemmaClient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemma_client_uses_local_base_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OLLAMA_OWN_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_OWN_API_KEY", raising=False)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_ollama_response("hello gemma"))

    client = GemmaClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    out = await client.chat([{"role": "user", "content": "ping"}])
    assert out == "hello gemma"
    assert captured["url"] == f"{DEFAULT_OLLAMA_OWN_BASE}/api/chat"
    # No bearer when unset.
    assert captured["auth"] is None
    assert captured["body"]["model"] == DEFAULT_GEMMA_MODEL


@pytest.mark.asyncio
async def test_gemma_client_attaches_bearer_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_OWN_API_KEY", "vlan-token")
    monkeypatch.setenv("OLLAMA_OWN_BASE_URL", "http://gemma.vlan:11434")

    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=_ollama_response("ok"))

    client = GemmaClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await client.chat([{"role": "user", "content": "x"}])
    assert captured["url"] == "http://gemma.vlan:11434/api/chat"
    assert captured["auth"] == "Bearer vlan-token"


@pytest.mark.asyncio
async def test_gemma_client_satisfies_protocol() -> None:
    g = GemmaClient()
    assert isinstance(g, InferenceClient)
    assert g.name == "gemma"
    assert g.model == DEFAULT_GEMMA_MODEL


@pytest.mark.asyncio
async def test_gemma_client_raises_inference_error_on_5xx() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="oops")

    client = GemmaClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(InferenceError):
        await client.chat([{"role": "user", "content": "hi"}])
