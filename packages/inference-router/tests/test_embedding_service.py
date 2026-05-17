"""v2.B Phase 3b — EmbeddingService Protocol + OllamaCloudEmbeddingService.

Real HTTP is mocked via :class:`httpx.MockTransport`; no network calls.
Tests cover:

  * Protocol roundtrip (mock cloud → vector + dim + model + latency)
  * Cache hit / miss / LRU eviction
  * Error handling (network → EmbeddingError; bad shape; missing key)
  * Multiple response shapes (Ollama cloud + OpenAI-compat)
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from wormbase_inference.embedding import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_EMBEDDING_MODEL,
    SUPPORTED_EMBEDDING_MODELS,
    EmbeddingConfigError,
    EmbeddingError,
    EmbeddingResult,
    EmbeddingService,
    OllamaCloudEmbeddingService,
    _EmbeddingCache,
)


def _fixed_vec(n: int = DEFAULT_EMBEDDING_DIM, seed: float = 0.1) -> list[float]:
    """Build a deterministic 768-dim vector for test bodies."""
    return [seed + i * 0.001 for i in range(n)]


# ---------------------------------------------------------------------------
# Protocol roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embedding_service_protocol_roundtrip() -> None:
    """OllamaCloudEmbeddingService satisfies the EmbeddingService
    Protocol and returns a populated EmbeddingResult."""
    vec = _fixed_vec()
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"embeddings": [vec]})

    svc = OllamaCloudEmbeddingService(
        api_key="sk-test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert isinstance(svc, EmbeddingService)
    result = await svc.embed("what is revenue this quarter?")
    assert isinstance(result, EmbeddingResult)
    assert result.dim == DEFAULT_EMBEDDING_DIM
    assert result.model == DEFAULT_EMBEDDING_MODEL
    assert result.cached is False
    assert result.latency_ms >= 0
    assert len(result.vector) == DEFAULT_EMBEDDING_DIM
    # Vector is a tuple (hashable / frozen-safe).
    assert isinstance(result.vector, tuple)
    # Backend was called.
    assert captured["url"].endswith("/api/embed")
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == DEFAULT_EMBEDDING_MODEL
    await svc.aclose()


@pytest.mark.asyncio
async def test_embedding_service_handles_embedding_singular_shape() -> None:
    """Older Ollama deploys return ``{embedding: [...]}`` not ``embeddings``."""
    vec = _fixed_vec()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embedding": vec})

    svc = OllamaCloudEmbeddingService(
        api_key="sk",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await svc.embed("hello")
    assert len(result.vector) == DEFAULT_EMBEDDING_DIM
    await svc.aclose()


@pytest.mark.asyncio
async def test_embedding_service_handles_openai_compat_shape() -> None:
    """Some Ollama Cloud routes wrap embeddings as ``{data: [{embedding: [...]}]}``."""
    vec = _fixed_vec()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": vec}]})

    svc = OllamaCloudEmbeddingService(
        api_key="sk",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await svc.embed("hello")
    assert len(result.vector) == DEFAULT_EMBEDDING_DIM
    await svc.aclose()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embedding_service_caches_results() -> None:
    """A second embed of the same text returns the cached vector +
    ``cached=True``; the backend is hit only once."""
    vec = _fixed_vec()
    call_count = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json={"embeddings": [vec]})

    svc = OllamaCloudEmbeddingService(
        api_key="sk",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    a = await svc.embed("same question")
    b = await svc.embed("same question")
    assert call_count["n"] == 1
    assert a.cached is False
    assert b.cached is True
    assert b.vector == a.vector
    assert b.latency_ms == 0
    await svc.aclose()


def test_embedding_cache_lru_eviction() -> None:
    """Cache evicts the LRU entry when exceeding max_entries."""
    cache = _EmbeddingCache(max_entries=2)
    cache.put("a", "m", (1.0,))
    cache.put("b", "m", (2.0,))
    assert cache.get("a", "m") == (1.0,)  # access — promotes "a" to MRU
    cache.put("c", "m", (3.0,))
    assert len(cache) == 2
    # "b" was LRU after the "a" access → evicted on "c" insert.
    assert cache.get("b", "m") is None
    assert cache.get("a", "m") == (1.0,)
    assert cache.get("c", "m") == (3.0,)


def test_embedding_cache_keys_by_text_and_model() -> None:
    """Same text under different models → distinct cache slots."""
    cache = _EmbeddingCache()
    cache.put("q", "model-a", (1.0,))
    cache.put("q", "model-b", (2.0,))
    assert cache.get("q", "model-a") == (1.0,)
    assert cache.get("q", "model-b") == (2.0,)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embedding_service_raises_on_missing_api_key() -> None:
    """No bearer token + non-empty text → EmbeddingError (not a sentinel)."""
    svc = OllamaCloudEmbeddingService(api_key=None)
    with pytest.raises(EmbeddingError, match="OLLAMA_API_KEY"):
        await svc.embed("hello")


@pytest.mark.asyncio
async def test_embedding_service_raises_on_http_error() -> None:
    """HTTP 503 → EmbeddingError (caller decides fallback)."""
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    svc = OllamaCloudEmbeddingService(
        api_key="sk",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(EmbeddingError, match="http error"):
        await svc.embed("hello")
    await svc.aclose()


@pytest.mark.asyncio
async def test_embedding_service_raises_on_unknown_shape() -> None:
    """Response with no vector keys → EmbeddingError."""
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unrelated": "blob"})

    svc = OllamaCloudEmbeddingService(
        api_key="sk",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(EmbeddingError, match="no vector"):
        await svc.embed("hello")
    await svc.aclose()


@pytest.mark.asyncio
async def test_embedding_service_raises_on_dim_mismatch() -> None:
    """Wrong-dim vector → EmbeddingError so a model swap is detectable."""
    short_vec = [0.1, 0.2, 0.3]  # 3 dim, not 768

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [short_vec]})

    svc = OllamaCloudEmbeddingService(
        api_key="sk",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(EmbeddingError, match="dim mismatch"):
        await svc.embed("hello")
    await svc.aclose()


@pytest.mark.asyncio
async def test_embedding_service_raises_on_empty_text() -> None:
    """Empty/whitespace text is invalid input (no backend call wasted)."""
    svc = OllamaCloudEmbeddingService(api_key="sk")
    with pytest.raises(EmbeddingError, match="non-empty"):
        await svc.embed("   ")


# ---------------------------------------------------------------------------
# Result model + dim are echoed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embedding_result_echoes_model_for_swap_detection() -> None:
    """Result.model and Result.dim are populated so downstream cosine
    consumers can detect model swaps (cosine across different models
    is meaningless — must re-embed)."""
    vec = _fixed_vec(n=1024, seed=0.05)  # mxbai-embed-large simulated

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [vec]})

    svc = OllamaCloudEmbeddingService(
        api_key="sk",
        model="mxbai-embed-large",
        dim=1024,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await svc.embed("hello")
    assert result.model == "mxbai-embed-large"
    assert result.dim == 1024
    await svc.aclose()


# ---------------------------------------------------------------------------
# Env-knob model + dim selection (post-rest #6, 2026-05-24)
# ---------------------------------------------------------------------------


def test_embedding_service_defaults_byte_identical_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env vars set → service still defaults to nomic-embed-text/768.

    Pins the byte-identical-behaviour invariant: existing Phase 3b
    deployments that don't set the new env knobs see the same model
    and dim as before post-rest #6 landed.
    """
    monkeypatch.delenv("WORMBASE_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("WORMBASE_EMBEDDING_DIM", raising=False)
    svc = OllamaCloudEmbeddingService(api_key="sk")
    assert svc.model == DEFAULT_EMBEDDING_MODEL == "nomic-embed-text"
    assert svc.dim == DEFAULT_EMBEDDING_DIM == 768


def test_embedding_service_honours_env_for_mxbai_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``WORMBASE_EMBEDDING_MODEL=mxbai-embed-large`` +
    ``WORMBASE_EMBEDDING_DIM=1024`` → service routes to the fallback.

    This is the operator-facing switch documented in the cross-model
    migration runbook: when nomic-embed-text rate-limits on Ollama
    Cloud, flip these two envs (after running v020 + re-embedding)
    and the service picks up mxbai-embed-large transparently.
    """
    monkeypatch.setenv("WORMBASE_EMBEDDING_MODEL", "mxbai-embed-large")
    monkeypatch.setenv("WORMBASE_EMBEDDING_DIM", "1024")
    svc = OllamaCloudEmbeddingService(api_key="sk")
    assert svc.model == "mxbai-embed-large"
    assert svc.dim == 1024
    assert SUPPORTED_EMBEDDING_MODELS["mxbai-embed-large"] == 1024


def test_embedding_service_rejects_model_dim_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``WORMBASE_EMBEDDING_MODEL=nomic-embed-text`` +
    ``WORMBASE_EMBEDDING_DIM=1024`` → loud :class:`EmbeddingConfigError`.

    Pins the "no silent misconfiguration" invariant: stamping 1024-dim
    vectors with a model that produces 768 would scramble cosine
    clustering for the lifetime of the install, so the service refuses
    to boot when the two env knobs disagree.
    """
    monkeypatch.setenv("WORMBASE_EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("WORMBASE_EMBEDDING_DIM", "1024")
    with pytest.raises(EmbeddingConfigError) as excinfo:
        OllamaCloudEmbeddingService(api_key="sk")
    msg = str(excinfo.value)
    # The error names both env knobs so an operator reading the boot
    # log can correct the misconfiguration without source-diving.
    assert "WORMBASE_EMBEDDING_DIM" in msg
    assert "WORMBASE_EMBEDDING_MODEL" in msg
    assert "768" in msg
    assert "1024" in msg


def test_embedding_service_rejects_unsupported_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``WORMBASE_EMBEDDING_MODEL=text-embedding-3-small`` is not in the
    supported set → :class:`EmbeddingConfigError`.

    The allowlist is intentional: adding a model requires a row in
    :data:`SUPPORTED_EMBEDDING_MODELS` plus a doc note about
    cross-model migration. Silent acceptance of an arbitrary model
    string would allow operators to land cosine-incompatible
    deployments by typo.
    """
    monkeypatch.setenv("WORMBASE_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.delenv("WORMBASE_EMBEDDING_DIM", raising=False)
    with pytest.raises(EmbeddingConfigError) as excinfo:
        OllamaCloudEmbeddingService(api_key="sk")
    msg = str(excinfo.value)
    assert "unsupported embedding model" in msg
    assert "text-embedding-3-small" in msg
    # The error lists the supported models so an operator can pick a
    # valid alternative without re-reading the source.
    assert "nomic-embed-text" in msg
    assert "mxbai-embed-large" in msg


def test_embedding_service_rejects_non_integer_dim_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``WORMBASE_EMBEDDING_DIM=abc`` → loud raise, not silent fallback.

    Matches the v019 HNSW knobs' "validation is loud" invariant
    (``test_v019_params_reject_ef_construction_non_integer``): a typo
    in a dim env must not silently degrade to 768; better to fail boot.
    """
    monkeypatch.delenv("WORMBASE_EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("WORMBASE_EMBEDDING_DIM", "abc")
    with pytest.raises(EmbeddingConfigError) as excinfo:
        OllamaCloudEmbeddingService(api_key="sk")
    assert "WORMBASE_EMBEDDING_DIM" in str(excinfo.value)
    assert "abc" in str(excinfo.value)


def test_embedding_service_constructor_kwargs_override_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit constructor kwargs win over env vars.

    Pins the resolution order: kwargs > env > module-default. Tests
    that pin a specific model (e.g. the existing
    ``test_embedding_result_echoes_model_for_swap_detection``) keep
    working when env vars are set in the test runner's process.
    """
    monkeypatch.setenv("WORMBASE_EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("WORMBASE_EMBEDDING_DIM", "768")
    svc = OllamaCloudEmbeddingService(
        api_key="sk",
        model="mxbai-embed-large",
        dim=1024,
    )
    assert svc.model == "mxbai-embed-large"
    assert svc.dim == 1024
