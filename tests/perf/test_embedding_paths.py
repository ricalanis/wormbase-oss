"""Path D benchmarks — EmbeddingService.embed() cache + concurrency.

Path D measures the surface that calls into Ollama Cloud for vector
embedding. Two regimes matter:

* **Cache hit** — short-circuit on the in-memory LRU. No network. The
  EmbeddingResult is built and returned immediately. This is the
  steady-state cost once the cache warms.
* **Cache miss** — full HTTP round-trip to Ollama, JSON decode,
  vector extraction. This benchmark **mocks** the HTTP so the
  measurement is reproducible. Real-Ollama numbers are flagged as
  a follow-up.

Cache architecture (per ``_EmbeddingCache``): per-instance LRU keyed
on ``sha256(text) + model``. The agent-gateway constructs one
``OllamaCloudEmbeddingService`` per process, so all reactivities share
the same cache. The hit rate depends on canonical_intent similarity
across firings.

The mock here is a controllable fake that simulates a network
latency window, so we measure the cache-vs-miss ratio under a known
network cost.

Methodology limits:

* Mocked HTTP. Real Ollama p95 is typically ~200-500ms depending on
  region; the mock is set to 50ms baseline so the test isn't slow.
* Single-process. Concurrency tests use asyncio.gather; this models
  in-process fanout, not multi-host load.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import pytest

from wormbase_inference.embedding import (
    EmbeddingError,
    EmbeddingResult,
    _EmbeddingCache,
)

from .conftest import (
    EMBEDDING_DIM,
    emit_report_line,
    make_seeded_rng,
    summarize,
    time_async,
)


# ---------------------------------------------------------------------------
# Deterministic fake embedding service
# ---------------------------------------------------------------------------


@dataclass
class FakeEmbeddingService:
    """In-process fake that mimics ``OllamaCloudEmbeddingService``.

    Honors the same EmbeddingService Protocol:
    * ``model`` + ``dim`` attributes
    * async ``embed(text)`` returning ``EmbeddingResult``
    * async ``aclose()``

    Cache semantics match the real service: per-instance LRU keyed
    on ``(sha256(text), model)``. Cache hits return latency_ms=0.

    Misses simulate HTTP latency via ``await asyncio.sleep(miss_latency_s)``
    (default 0.05s ≈ 50ms; tunable per test). The vector is
    deterministic — sha256-derived — so repeated misses for the same
    text return the same vector.
    """

    model: str = "embeddinggemma:300m"
    dim: int = EMBEDDING_DIM
    miss_latency_s: float = 0.05
    _cache: _EmbeddingCache = field(default_factory=_EmbeddingCache, init=False)
    _miss_count: int = field(default=0, init=False)
    _hit_count: int = field(default=0, init=False)

    async def embed(self, text: str) -> EmbeddingResult:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingError("embed: text must be a non-empty string")
        hit = self._cache.get(text, self.model)
        if hit is not None:
            self._hit_count += 1
            return EmbeddingResult(
                vector=hit, dim=len(hit), model=self.model,
                latency_ms=0, cached=True,
            )
        self._miss_count += 1
        if self.miss_latency_s > 0:
            await asyncio.sleep(self.miss_latency_s)
        # Deterministic pseudo-embedding: sha256 → bytes → dim floats.
        seed_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand by repeating + indexing into float space.
        vec: list[float] = []
        for i in range(self.dim):
            b = seed_bytes[i % len(seed_bytes)]
            vec.append((b / 255.0) - 0.5)
        vector_t = tuple(vec)
        self._cache.put(text, self.model, vector_t)
        return EmbeddingResult(
            vector=vector_t,
            dim=len(vector_t),
            model=self.model,
            latency_ms=int(self.miss_latency_s * 1000),
            cached=False,
        )

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.perf
async def test_path_d_cache_hit_walltime() -> None:
    """Steady-state cache-hit cost (warm cache, same text).

    Establishes the lower bound on embed() — what does a hit cost
    when the cache is hot? Should be dominated by SHA256 + dict
    lookup, not by EmbeddingResult construction.
    """
    svc = FakeEmbeddingService(miss_latency_s=0.05)
    # Warm.
    await svc.embed("how many orders today")

    async def _run() -> None:
        await svc.embed("how many orders today")

    samples = await time_async(_run, warmup=10, n_samples=500)
    result = summarize("path_d_cache_hit", samples)
    emit_report_line("path_d_hit", json.dumps(result.as_row()))


@pytest.mark.perf
async def test_path_d_cache_miss_walltime() -> None:
    """Cache-miss cost with 50ms mock network latency.

    Each iteration uses a fresh text → forces a miss. The cost is
    dominated by the simulated HTTP round-trip; the vector
    materialization is < 1ms. Real-Ollama p50 is typically ~150-300ms,
    p95 ~500-800ms.
    """
    svc = FakeEmbeddingService(miss_latency_s=0.05)
    counter = {"n": 0}

    async def _run() -> None:
        counter["n"] += 1
        await svc.embed(f"how many orders today #{counter['n']}")

    samples = await time_async(_run, warmup=2, n_samples=20)
    result = summarize("path_d_cache_miss_50ms_mock", samples)
    emit_report_line("path_d_miss", json.dumps(result.as_row()))


@pytest.mark.perf
async def test_path_d_cache_miss_walltime_zero_latency() -> None:
    """Cache miss with NO simulated network latency.

    Bounds the pure CPU cost of building a 768-dim ``EmbeddingResult``
    + cache insertion. Real-Ollama latency adds linearly on top.
    """
    svc = FakeEmbeddingService(miss_latency_s=0.0)
    counter = {"n": 0}

    async def _run() -> None:
        counter["n"] += 1
        await svc.embed(f"q{counter['n']}")

    samples = await time_async(_run, warmup=5, n_samples=200)
    result = summarize("path_d_cache_miss_zero_latency", samples)
    emit_report_line("path_d_miss_zero", json.dumps(result.as_row()))


@pytest.mark.perf
@pytest.mark.parametrize("concurrency", [1, 5, 10, 20])
async def test_path_d_concurrent_cache_miss(concurrency: int) -> None:
    """Mean per-call cost under N parallel cache-miss calls.

    With asyncio.gather + sleep-modeled network, N parallel calls
    overlap their wait time — total wall-clock should be ~one
    miss_latency, not N × miss_latency. Confirms the asyncio path
    doesn't accidentally serialize.
    """
    svc = FakeEmbeddingService(miss_latency_s=0.05)
    counter = {"n": 0}

    async def _run_batch() -> None:
        async def one() -> None:
            counter["n"] += 1
            await svc.embed(f"concurrent q #{counter['n']}")
        await asyncio.gather(*[one() for _ in range(concurrency)])

    samples = await time_async(_run_batch, warmup=1, n_samples=5)
    result = summarize(
        f"path_d_concurrent_miss_n={concurrency}", samples,
    )
    emit_report_line("path_d_concurrent", json.dumps(result.as_row()))

    # Sanity: wall-clock for N concurrent misses should be << N×50ms
    # (otherwise the event loop is serializing what should be parallel).
    # The single-call case (N=1) needs a floor: one 50ms sleep + asyncio
    # scheduling overhead can land at ~60-100ms, so we compare against
    # N×50ms + a fixed scheduling budget.
    scheduling_budget_ms = 100.0
    upper_bound_ms = (concurrency * 50) * 0.6 + scheduling_budget_ms
    assert result.mean_ms < upper_bound_ms, (
        f"N={concurrency} concurrent embed calls took {result.mean_ms:.1f}ms; "
        f"expected < {upper_bound_ms:.1f}ms (parallel asyncio not serialized)"
    )


@pytest.mark.perf
async def test_path_d_lru_eviction_behavior() -> None:
    """Cost of the cache when it's at capacity + evicting.

    The default LRU cap is ~512 entries (see ``_CACHE_MAX_ENTRIES``).
    Putting > cap entries triggers ``popitem(last=False)`` on each
    insert. Measures whether the steady-state-eviction regime is
    materially slower than the fill-only regime.
    """
    from wormbase_inference.embedding import _CACHE_MAX_ENTRIES

    svc = FakeEmbeddingService(miss_latency_s=0.0)
    # Fill to capacity.
    for i in range(_CACHE_MAX_ENTRIES):
        await svc.embed(f"warmup-{i}")
    assert len(svc._cache) == _CACHE_MAX_ENTRIES

    counter = {"n": 0}

    async def _run() -> None:
        counter["n"] += 1
        # Distinct text each time → forces miss + eviction.
        await svc.embed(f"evict-q-{counter['n']}")

    samples = await time_async(_run, warmup=5, n_samples=100)
    result = summarize("path_d_at_capacity_eviction", samples)
    emit_report_line("path_d_eviction", json.dumps(result.as_row()))

    # Cache stays at cap (LRU invariant).
    assert len(svc._cache) == _CACHE_MAX_ENTRIES
