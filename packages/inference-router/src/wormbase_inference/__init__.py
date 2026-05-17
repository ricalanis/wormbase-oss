"""WormBase inference router.

Routes LLM requests across:

* **remote inference** (Kimi K2.6 via Ollama Cloud) — frontier-quality
  reasoning, low volume, high stakes.
* **own inference** (Gemma 4 E4B via local/VLAN Ollama) — high volume
  commodity work (classification, summarization, embeddings, PII tagging).

Public surface (Blocks B + C + D + E)
-------------------------------------

The router exposes ONE primitive:

    response = await router.call(request)

where ``request`` is a :class:`RouteRequest` and ``response`` a
:class:`RouteResponse`. :class:`CachedRouter` composes a
:class:`KimiClient` + :class:`GemmaClient` + :class:`InferenceCache`
+ optional ledger writer; on each call it routes by ``call_type``,
caches the answer (sqlite by default), and emits an
``inference_served`` PEVR cycle when a ledger is wired.

Note on the "Kimi base URL"
---------------------------

The orchestrator's plan referenced ``https://api.moonshot.ai/v1``.
Production code in this repo (voice-agent,
chat-presence's ``OllamaCloudClassifier``) speaks Ollama Cloud at
``https://ollama.com/api/chat``; the same ``OLLAMA_API_KEY`` env var
configures every Kimi consumer. The router follows that production
shape — fragmenting into a second auth scheme would be a regression.
"""

from __future__ import annotations

from wormbase_inference.agent_id import (
    AgentID,
    Classification,
    GovernanceContext,
)
from wormbase_inference.cache import (
    InferenceCache,
    NullInferenceCache,
    SqliteInferenceCache,
    make_cache_key,
)
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
from wormbase_inference.decision_adapter import DecisionLLMClient
from wormbase_inference.embedding import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingError,
    EmbeddingResult,
    EmbeddingService,
    OllamaCloudEmbeddingService,
    build_default_embedding_service,
)
from wormbase_inference.demo_prompts import (
    ACME_DEMO_PROMPTS,
    DemoPrompt,
    PopulateReport,
    populate_acme_cache,
    populate_acme_cache_at_path,
)
from wormbase_inference.topic_labeler_adapter import TopicLabelerLLMClient
from wormbase_inference.protocol import (
    Router,
    RouteRequest,
    RouteResponse,
    default_backend,
)
from wormbase_inference.router import (
    CachedRouter,
    CacheMissError,
    build_cache_key,
    build_default_router,
)

__all__ = [
    "ACME_DEMO_PROMPTS",
    "AgentID",
    "CacheMissError",
    "CachedRouter",
    "Classification",
    "DEFAULT_EMBEDDING_DIM",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_GEMMA_MODEL",
    "DEFAULT_KIMI_MODEL",
    "DEFAULT_OLLAMA_BASE",
    "DEFAULT_OLLAMA_OWN_BASE",
    "DecisionLLMClient",
    "DemoPrompt",
    "EmbeddingError",
    "EmbeddingResult",
    "EmbeddingService",
    "GemmaClient",
    "GovernanceContext",
    "InferenceCache",
    "InferenceClient",
    "InferenceError",
    "KimiClient",
    "NullInferenceCache",
    "OllamaCloudEmbeddingService",
    "PopulateReport",
    "RouteRequest",
    "RouteResponse",
    "Router",
    "SqliteInferenceCache",
    "TopicLabelerLLMClient",
    "build_cache_key",
    "build_default_embedding_service",
    "build_default_router",
    "default_backend",
    "make_cache_key",
    "populate_acme_cache",
    "populate_acme_cache_at_path",
]
