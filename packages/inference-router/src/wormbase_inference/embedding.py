"""v2.B Phase 3b — Embedding service (parallel to Router).

The :class:`Router` (in :mod:`router`) is text-in / text-out. Embedding
generation has different ergonomics:

  * the response is a vector (``list[float]``), not text;
  * vectors are large (768 floats ~= 6KB) so an LRU memory cache is
    appropriate, not a sqlite blob;
  * the model + dimensionality are part of the response so callers can
    detect a model swap and re-embed;
  * failures should return a sentinel (None on the result, or raise an
    :class:`EmbeddingError`), not retry-with-fallback like the Router.

This module therefore ships a SEPARATE Protocol +
:class:`OllamaCloudEmbeddingService` impl + LRU cache, leaving the
Router unchanged.

Production wiring: the §4.5 ``lake.query.record_outcome`` MCP tool calls
``EmbeddingService.embed(nl_question)`` at write time and stamps the
resulting vector onto the ``QueryOutcomeRecordedPayload.embedding`` field.
Downstream axes 1 (template promotion) + 3 (bad-pattern) cluster on
cosine ≥ 0.85.

Model: Ollama Cloud's ``nomic-embed-text`` (768 dim) is the v2.B Phase 3b
ship pick — free on Ollama Cloud's existing API key, well-documented,
single-vector output. Fallback to ``mxbai-embed-large`` (1024 dim) is
production-supported as of post-rest #6 (2026-05-24); the cross-model
migration runbook lives at
``docs/superpowers/notes/2026-05-24-cross-model-embedding-migration.md``.

Env knobs:

  * ``OLLAMA_API_KEY`` — same bearer as Kimi (Ollama Cloud).
  * ``OLLAMA_API_BASE`` — same base URL as Kimi (``https://ollama.com``).
  * ``WORMBASE_EMBEDDING_MODEL`` — override the model name. Must be one
    of :data:`SUPPORTED_EMBEDDING_MODELS` (``nomic-embed-text``,
    ``mxbai-embed-large``).
  * ``WORMBASE_EMBEDDING_DIM`` — must match the model's native dim
    (768 for nomic-embed-text; 1024 for mxbai-embed-large). Mismatch
    raises :class:`EmbeddingConfigError` at construction time.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_EMBEDDING_MODEL: str = "nomic-embed-text"
"""Ollama Cloud's free, well-supported 768-dim embedding model.

Fallback candidates: ``mxbai-embed-large`` (1024 dim) if nomic rate-
limits or disappears. The migration v018 documents the swap.
"""

DEFAULT_EMBEDDING_DIM: int = 768
"""nomic-embed-text output dimension."""

# Canonical model → native-dim map. The dim must match the model's
# output exactly; mismatch raises :class:`EmbeddingConfigError` at
# service construction time so an operator can't silently land a
# misconfigured deployment that would scramble cosine distances.
#
# Extension policy: add a row here when a new model is approved for
# production. The migration runbook
# (``docs/superpowers/notes/2026-05-24-cross-model-embedding-migration.md``)
# walks through the cross-model swap procedure (drop HNSW, NULL out
# existing embeddings, ALTER vector dim, re-create index, backfill).
SUPPORTED_EMBEDDING_MODELS: dict[str, int] = {
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
}

# Tiny in-memory LRU cap. Vectors are large enough that bigger caches
# leak memory; per-tenant cardinality of NL questions is bounded.
_CACHE_MAX_ENTRIES: int = 1000

_DEFAULT_OLLAMA_BASE: str = "https://ollama.com"

_ENV_MODEL: str = "WORMBASE_EMBEDDING_MODEL"
_ENV_DIM: str = "WORMBASE_EMBEDDING_DIM"


class EmbeddingError(RuntimeError):
    """Raised when an embedding call fails (network / malformed body /
    auth / dim mismatch).

    Distinct from :class:`wormbase_inference.InferenceError` so the
    Router's fallback policy never sees embedding failures (the two
    surfaces are independent).
    """


class EmbeddingConfigError(ValueError):
    """Raised at service construction time when ``WORMBASE_EMBEDDING_MODEL``
    and ``WORMBASE_EMBEDDING_DIM`` disagree, or when the model name is
    not in :data:`SUPPORTED_EMBEDDING_MODELS`.

    Loud-at-construction (not at first-embed) so a misconfigured boot
    fails fast — a deployment that quietly stamps 768-dim vectors with
    a model that produces 1024 would corrupt cosine clustering for the
    lifetime of the install. Better to refuse to start.
    """


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Return shape of :meth:`EmbeddingService.embed`.

    Frozen + slotted so it can flow through the value-object stack
    (ledger payloads, cache keys, audit rows) without surprise mutation.
    """

    vector: tuple[float, ...]
    """The embedding. ``tuple`` so the value object is hashable + frozen-
    safe; callers wanting a list dump call ``list(result.vector)``."""

    dim: int
    """Length of ``vector``. Asserted equal to ``DEFAULT_EMBEDDING_DIM``
    unless overridden via env."""

    model: str
    """Echo of the model that produced the vector. Lets downstream
    consumers detect a model swap (cosine across different models is
    meaningless — they must re-embed)."""

    latency_ms: int
    """Wall-clock ms of the embed call (cache hits are 0)."""

    cached: bool = False
    """True iff served from the LRU cache; False on a fresh backend
    call. Useful for telemetry."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingService(Protocol):
    """The single embedding entry point WormBase code depends on.

    Implementations:

    * :class:`OllamaCloudEmbeddingService` — production, calls Ollama
      Cloud's ``/api/embed`` endpoint with the same bearer token as
      :class:`KimiClient`.
    * Test fakes return a deterministic vector keyed on the input text
      (see ``test_embedding_service.py``).
    """

    model: str
    dim: int

    async def embed(self, text: str) -> EmbeddingResult:
        """Embed one text string. Raises :class:`EmbeddingError` on any
        backend failure (network, malformed response, dim mismatch)."""
        ...

    async def aclose(self) -> None:
        """Release any owned httpx client."""
        ...


# ---------------------------------------------------------------------------
# LRU cache
# ---------------------------------------------------------------------------


@dataclass
class _EmbeddingCache:
    """Tiny in-memory LRU keyed on ``(text_hash, model)``.

    Capped at :data:`_CACHE_MAX_ENTRIES`; on overflow we drop the LRU
    entry. The hash collapses long NL questions to a fixed-length key
    so memory footprint scales with cache size, not query length.

    Cross-process sharing isn't a goal — this cache lives in the
    EmbeddingService instance, and the agent-gateway constructs one
    per process. A future deployment that fans out across worker
    processes will get N caches, each independently warming. That's
    fine: cache hits are an optimization, not a correctness primitive.
    """

    max_entries: int = _CACHE_MAX_ENTRIES
    _entries: OrderedDict[tuple[str, str], tuple[float, ...]] = field(
        default_factory=OrderedDict,
    )

    @staticmethod
    def _key(text: str, model: str) -> tuple[str, str]:
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return (h, model)

    def get(self, text: str, model: str) -> tuple[float, ...] | None:
        key = self._key(text, model)
        if key not in self._entries:
            return None
        # Mark as most-recently-used.
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, text: str, model: str, vector: tuple[float, ...]) -> None:
        key = self._key(text, model)
        if key in self._entries:
            self._entries.move_to_end(key)
            self._entries[key] = vector
            return
        self._entries[key] = vector
        # Evict LRU until under cap.
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def __len__(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# OllamaCloudEmbeddingService — production impl
# ---------------------------------------------------------------------------


@dataclass
class OllamaCloudEmbeddingService:
    """Async embedding client routed through Ollama Cloud.

    Configurable via constructor kwargs OR env:

    * ``OLLAMA_API_KEY`` — bearer token (required for cloud).
    * ``OLLAMA_API_BASE`` — default ``https://ollama.com``.
    * ``WORMBASE_EMBEDDING_MODEL`` — override the model name.
    * ``WORMBASE_EMBEDDING_DIM`` — assert the expected dim.

    A custom ``client`` can be injected for tests. When omitted, a
    fresh :class:`httpx.AsyncClient` is created on first call and
    closed by :meth:`aclose`.

    The cache is a per-instance LRU — see :class:`_EmbeddingCache`.
    """

    api_key: str | None = None
    base_url: str = _DEFAULT_OLLAMA_BASE
    model: str = DEFAULT_EMBEDDING_MODEL
    dim: int = DEFAULT_EMBEDDING_DIM
    timeout_s: float = 30.0
    client: httpx.AsyncClient | None = None
    _own_client: bool = field(default=False, init=False)
    _cache: _EmbeddingCache = field(default_factory=_EmbeddingCache, init=False)

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("OLLAMA_API_KEY")
        env_base = os.environ.get("OLLAMA_API_BASE")
        if env_base:
            self.base_url = env_base

        # ----------------------------------------------------------------
        # Model + dim resolution.
        #
        # Constructor kwargs win over env (so tests can pin a model
        # without monkeypatching), env wins over module defaults. The
        # resolution order matches the rest of the inference-router
        # builder convention.
        #
        # After resolution, validate against SUPPORTED_EMBEDDING_MODELS
        # so an operator cannot land a model/dim mismatch in production.
        # ----------------------------------------------------------------
        # Track whether the model/dim were explicitly passed (via kwargs)
        # to distinguish from the dataclass defaults — env should only
        # override the field if the caller didn't pin it.
        constructor_model_default = self.model == DEFAULT_EMBEDDING_MODEL
        constructor_dim_default = self.dim == DEFAULT_EMBEDDING_DIM
        env_model = os.environ.get(_ENV_MODEL)
        if env_model and constructor_model_default:
            self.model = env_model
        env_dim_raw = os.environ.get(_ENV_DIM)
        if env_dim_raw and constructor_dim_default:
            try:
                self.dim = int(env_dim_raw)
            except ValueError as exc:
                raise EmbeddingConfigError(
                    f"{_ENV_DIM}={env_dim_raw!r} is not a valid integer; "
                    f"expected one of {sorted(set(SUPPORTED_EMBEDDING_MODELS.values()))} "
                    f"or unset (default {DEFAULT_EMBEDDING_DIM})."
                ) from exc

        self._validate_model_and_dim()
        self.base_url = self.base_url.rstrip("/")

    def _validate_model_and_dim(self) -> None:
        """Reject unsupported models + model/dim mismatch.

        Raises :class:`EmbeddingConfigError` with operator-actionable
        text that names both env knobs so an ops person reading the
        log can correct the misconfiguration without re-reading the
        source.
        """
        if self.model not in SUPPORTED_EMBEDDING_MODELS:
            supported = ", ".join(sorted(SUPPORTED_EMBEDDING_MODELS))
            raise EmbeddingConfigError(
                f"unsupported embedding model {self.model!r}; "
                f"supported models: [{supported}]. "
                f"Set {_ENV_MODEL} to one of the supported values."
            )
        native_dim = SUPPORTED_EMBEDDING_MODELS[self.model]
        if self.dim != native_dim:
            raise EmbeddingConfigError(
                f"{self.model!r} produces {native_dim}-dim vectors; "
                f"got {_ENV_DIM}={self.dim}. "
                f"Either set {_ENV_DIM}={native_dim} or change "
                f"{_ENV_MODEL} to a model whose native dim matches "
                f"(supported: {SUPPORTED_EMBEDDING_MODELS})."
            )

    async def embed(self, text: str) -> EmbeddingResult:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingError("embed: text must be a non-empty string")

        # ----------------------------------------------------------------
        # Cache hit — short-circuit. cached=True surfaces in telemetry.
        # ----------------------------------------------------------------
        hit = self._cache.get(text, self.model)
        if hit is not None:
            return EmbeddingResult(
                vector=hit,
                dim=len(hit),
                model=self.model,
                latency_ms=0,
                cached=True,
            )

        if not self.api_key:
            raise EmbeddingError(
                "embed: OLLAMA_API_KEY is not configured; remote "
                "embedding unavailable"
            )
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout_s)
            self._own_client = True

        body: dict[str, Any] = {
            "model": self.model,
            # Ollama's embed endpoint accepts either ``input`` (newer)
            # or ``prompt`` (older). ``input`` is the cloud-standard
            # field; we send both for safety against schema drift.
            "input": text,
            "prompt": text,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        start = time.monotonic()
        try:
            r = await self.client.post(
                f"{self.base_url}/api/embed",
                headers=headers,
                json=body,
            )
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"http error: {exc}") from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise EmbeddingError(f"malformed response body: {exc}") from exc

        vector = _extract_vector(data)
        if not vector:
            raise EmbeddingError(
                f"embed: response had no vector payload; keys={list(data) if isinstance(data, dict) else type(data).__name__}"
            )
        if self.dim and len(vector) != self.dim:
            raise EmbeddingError(
                f"embed: dim mismatch — got {len(vector)} expected {self.dim} "
                f"(model={self.model})"
            )

        vec_tuple = tuple(float(v) for v in vector)
        self._cache.put(text, self.model, vec_tuple)
        latency_ms = int((time.monotonic() - start) * 1000)
        return EmbeddingResult(
            vector=vec_tuple,
            dim=len(vec_tuple),
            model=self.model,
            latency_ms=latency_ms,
            cached=False,
        )

    async def aclose(self) -> None:
        if self._own_client and self.client is not None:
            await self.client.aclose()
            self.client = None
            self._own_client = False


def _extract_vector(data: Any) -> list[float] | None:
    """Tolerant extractor for Ollama's embed response shape.

    Ollama Cloud's ``/api/embed`` returns one of:

      * ``{"embeddings": [[...]]}`` — newer cloud shape (list-of-lists
        even for a single input);
      * ``{"embedding": [...]}`` — older single-vector shape;
      * ``{"data": [{"embedding": [...]}]}`` — OpenAI-compat shape on
        some routes.

    Returns the first vector or None if the shape was unrecognised.
    """
    if not isinstance(data, dict):
        return None
    embs = data.get("embeddings")
    if isinstance(embs, list) and embs and isinstance(embs[0], list):
        return [float(v) for v in embs[0]]
    emb = data.get("embedding")
    if isinstance(emb, list):
        return [float(v) for v in emb]
    dlist = data.get("data")
    if isinstance(dlist, list) and dlist:
        first = dlist[0]
        if isinstance(first, dict):
            v = first.get("embedding")
            if isinstance(v, list):
                return [float(x) for x in v]
    return None


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_default_embedding_service() -> OllamaCloudEmbeddingService:
    """Production-shape embedding service from environment variables.

    Returns an :class:`OllamaCloudEmbeddingService` configured via env.
    The caller does not need to know about the env knobs — same
    convention as :func:`wormbase_inference.router.build_default_router`.

    The service is opt-in at the worm-core wiring site
    (``WORMBASE_EMBEDDING_ENABLED=true``); when disabled, callers pass
    ``embedding_service=None`` and the §4.5 write-time wire skips the
    embed call.
    """
    return OllamaCloudEmbeddingService()


__all__ = [
    "DEFAULT_EMBEDDING_DIM",
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingConfigError",
    "EmbeddingError",
    "EmbeddingResult",
    "EmbeddingService",
    "OllamaCloudEmbeddingService",
    "SUPPORTED_EMBEDDING_MODELS",
    "build_default_embedding_service",
]
