"""Block E (router half) — :class:`CachedRouter`.

Composes:

* a :class:`KimiClient` (remote)
* a :class:`GemmaClient` (own VLAN)
* an :class:`InferenceCache`
* an optional ledger writer for ``inference_served`` audit rows

Behavior, in order:

1. Resolve the backend: explicit ``backend_hint`` if given, else
   :func:`default_backend(call_type)`.
2. Compute the cache key over the canonical request shape.
3. If the cache returns a value, emit ``inference_served`` tagged
   ``served_by="cache"`` and return.
4. Else call the chosen backend; on :class:`InferenceError`, fall back
   to the *other* backend (Kimi → Gemma or Gemma → Kimi). Cache the
   answer.
5. Emit ``inference_served`` tagged ``served_by="kimi" | "gemma"`` with
   ``is_fallback=True`` if the fallback path served the answer.

The ledger writer is optional — when ``None``, the router still works
but no ``inference_served`` rows land. Tests that don't care about the
ledger pass ``ledger=None``; production paths always wire a real
``Ledger``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from wormbase_inference.agent_id import AgentID
from wormbase_inference.cache import (
    InferenceCache,
    NullInferenceCache,
    make_cache_key,
)
from wormbase_inference.clients import (
    GemmaClient,
    InferenceClient,
    InferenceError,
    KimiClient,
    monotonic_ms,
)
from wormbase_inference.protocol import (
    _CACHE_KEY_FIELDS,
    RouteRequest,
    RouteResponse,
    ServedBy,
    default_backend,
)

logger = logging.getLogger(__name__)


def build_cache_key(req: RouteRequest) -> str:
    """SHA256 hex over the cache-key-eligible fields of a RouteRequest.

    The ``_CACHE_KEY_FIELDS`` allow-list (in :mod:`protocol`) controls
    which fields participate. ``requested_by`` and ``governance_context``
    are deliberately excluded: two requests that differ only by who
    asked / which governance envelope applies must hit the same cache
    entry (the response is governance-invariant; the audit row records
    who saw it).

    Tuple fields (``messages``, ``extra``) are normalized to lists for
    canonical JSON output. ``default=str`` handles any value type that
    isn't natively JSON-serializable (e.g. enums leaking in via
    ``extra``).

    This function is the public companion to the legacy
    :func:`wormbase_inference.cache.make_cache_key` — that one keys on
    the post-resolve ``model`` + flattened message dicts and is what the
    router actually calls to derive ``cache_key`` for production cache
    lookup. ``build_cache_key`` is the structural fingerprint over the
    RouteRequest itself, used by callers that need to dedupe identical
    requests BEFORE the backend is resolved (e.g. agent-gateway query
    templates).
    """
    import hashlib
    import json

    payload: dict[str, Any] = {}
    for fname in _CACHE_KEY_FIELDS:
        value = getattr(req, fname)
        if isinstance(value, tuple):
            value = [list(t) if isinstance(t, tuple) else t for t in value]
        payload[fname] = value
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


class CacheMissError(InferenceError):
    """Raised when ``cache_only`` is set and the cache has no entry.

    Distinct from a plain :class:`InferenceError` so the router can
    surface a clear "demo cache miss" message without triggering the
    fallback path (the whole point of ``cache_only`` is to refuse
    network I/O).
    """


@dataclass
class CachedRouter:
    """Production :class:`Router` implementation.

    The two backends + cache are constructor-injected for testability.
    The ``ledger`` is optional; when supplied, every call writes one
    PEVR cycle ending in an ``inference_served`` resolve.

    The ``company_id`` is required when ``ledger`` is supplied (every
    ledger entry is tenant-scoped). When ``ledger`` is ``None``, the
    company_id is unused.

    ``cache_only`` (DEMO.1.C) — when True, the router refuses to call
    Kimi or Gemma. Cache hits return as normal; cache misses raise
    :class:`CacheMissError`. This is the demo offline-mode flag: a
    pre-populated cache + ``cache_only=True`` makes the demo
    deterministic and independent of live LLM availability.
    """

    kimi: InferenceClient
    gemma: InferenceClient
    cache: InferenceCache = field(default_factory=NullInferenceCache)
    ledger: Any | None = None
    company_id: UUID | None = None
    cache_only: bool = False

    async def call(self, request: RouteRequest) -> RouteResponse:
        backend = self._resolve_backend(request)

        # Build messages once; both backends consume the same shape.
        messages = request.messages_as_dicts()
        chosen_model = self._chosen_model(backend)
        cache_key = make_cache_key(
            model=chosen_model,
            messages=messages,
            temperature=request.temperature,
            extra=dict(request.extra),
        )

        # ----------------------------------------------------------------
        # Cache hit — short-circuit. Tagged served_by="cache".
        # ----------------------------------------------------------------
        if (hit := self.cache.get(cache_key)) is not None:
            response = RouteResponse(
                text=hit,
                served_by="cache",
                is_fallback=False,
                cache_key=cache_key,
                latency_ms=0,
                model=chosen_model,
            )
            await self._emit_inference_served(request, response)
            return response

        # ----------------------------------------------------------------
        # cache_only — refuse to touch Kimi/Gemma; surface a clean error.
        # ----------------------------------------------------------------
        if self.cache_only:
            raise CacheMissError(
                "cache_only=True and no cached response for "
                f"call_type={request.call_type} requested_by={request.requested_by} "
                f"cache_key={cache_key}. Pre-populate the cache (see "
                "wormbase_inference.demo_prompts.populate_acme_cache) or "
                "set WORMBASE_INFERENCE_CACHE_ONLY=false to allow live LLM."
            )

        # ----------------------------------------------------------------
        # Cache miss — call the chosen backend; on failure, fall back.
        # ----------------------------------------------------------------
        primary, secondary = self._backend_pair(backend)
        start = monotonic_ms()
        is_fallback = False
        served_by: ServedBy = "kimi" if primary.name == "kimi" else "gemma"
        try:
            text = await primary.chat(
                messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
            served_model = primary.model
        except InferenceError as exc:
            if secondary is None:
                logger.error(
                    "inference-router: %s failed and no fallback configured: %s",
                    primary.name, exc,
                )
                raise
            logger.warning(
                "inference-router: %s failed (%s); falling back to %s",
                primary.name, exc, secondary.name,
            )
            text = await secondary.chat(
                messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
            is_fallback = True
            served_by = "kimi" if secondary.name == "kimi" else "gemma"
            served_model = secondary.model

        latency_ms = monotonic_ms() - start
        # Cache under the *chosen* backend's model so that a follow-up
        # request that resolves to the same backend hits; if the route
        # later flips to the other backend, the key is different by
        # design.
        self.cache.put(cache_key, text, model=served_model)

        response = RouteResponse(
            text=text,
            served_by=served_by,
            is_fallback=is_fallback,
            cache_key=cache_key,
            latency_ms=latency_ms,
            model=served_model,
        )
        await self._emit_inference_served(request, response)
        return response

    async def aclose(self) -> None:
        for c in (self.kimi, self.gemma):
            try:
                await c.aclose()
            except Exception:  # noqa: BLE001
                logger.exception("inference-router: backend aclose failed")
        if hasattr(self.cache, "close"):
            try:
                self.cache.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                logger.exception("inference-router: cache close failed")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_backend(self, request: RouteRequest) -> str:
        if request.backend_hint != "auto":
            return request.backend_hint
        choice = default_backend(request.call_type)
        if choice is None:
            raise ValueError(
                f"inference-router: call_type {request.call_type!r} has no "
                f"default backend; pass backend_hint='kimi' or 'gemma'"
            )
        return choice

    def _backend_pair(
        self, backend: str
    ) -> tuple[InferenceClient, InferenceClient | None]:
        if backend == "kimi":
            return self.kimi, self.gemma
        if backend == "gemma":
            return self.gemma, self.kimi
        raise ValueError(f"inference-router: unknown backend {backend!r}")

    def _chosen_model(self, backend: str) -> str:
        if backend == "kimi":
            return self.kimi.model
        if backend == "gemma":
            return self.gemma.model
        raise ValueError(f"inference-router: unknown backend {backend!r}")

    async def _emit_inference_served(
        self,
        request: RouteRequest,
        response: RouteResponse,
    ) -> None:
        """Write one PEVR cycle ending in ``inference_served``.

        Best-effort: ledger failures log + raise. The router cannot
        silently lose audit rows, but it also doesn't fail-soft on the
        inference itself when the ledger is unreachable — a
        :class:`Ledger` consumer that wants soft behaviour should wrap
        :meth:`call` in a ``try`` block.

        When ``self.ledger is None``, this is a no-op.
        """
        if self.ledger is None:
            return
        if self.company_id is None:
            raise ValueError(
                "inference-router: company_id is required when ledger is wired"
            )
        request_id = uuid4()
        target_kind = "inference_served"

        # Boundary-convert ``requested_by: str`` -> ``AgentID`` here, at
        # the audit-emission site. Per Phase 0 §7, retyping the
        # RouteRequest field directly is blocked by ``frozen+slots``;
        # the conversion happens at the router boundary instead so
        # every existing internal call site keeps working unchanged.
        agent_id = AgentID.from_legacy_string(request.requested_by)

        # Surface the governance envelope into the audit payload when
        # present. ``None`` is preserved as ``None`` so a reader can
        # distinguish "no envelope attached" from "envelope said
        # public/no-budget/no-redaction." cost_budget_usd is coerced
        # to ``str`` to keep the ledger payload JSON-serializable
        # without forcing every consumer to import ``Decimal``.
        gov = request.governance_context
        gov_payload: dict[str, Any] | None
        if gov is None:
            gov_payload = None
        else:
            gov_payload = {
                "classification_ceiling": gov.classification_ceiling,
                "cost_budget_usd": (
                    str(gov.cost_budget_usd)
                    if gov.cost_budget_usd is not None
                    else None
                ),
                "pii_redaction": gov.pii_redaction,
                "domain_id": gov.domain_id,
            }

        try:
            await self.ledger.write(
                company_id=self.company_id,
                propose={
                    "target_kind": target_kind,
                    "ref_id": str(request_id),
                    "reason": (
                        f"inference_served via {response.served_by}"
                        f" for {request.call_type} (agent_id={agent_id.value})"
                    ),
                    "proposed_by": "inference_router",
                },
                execute_fn=lambda: {
                    "tool": target_kind,
                    "args": {
                        "request_id": str(request_id),
                        "served_by": response.served_by,
                        "is_fallback": response.is_fallback,
                        "cache_key": response.cache_key,
                        "latency_ms": response.latency_ms,
                        # Wave 2: AgentID + governance envelope land in
                        # the audit row so MCP-tool invocations are
                        # attributable end-to-end.
                        "agent_id": agent_id.value,
                        "governance_context": gov_payload,
                    },
                    "result_ref": str(request_id),
                },
                verify_fn=lambda _r: {
                    "checks": [{"name": "inference_recorded", "ok": True}],
                    "passed": True,
                },
                resolve_fn=lambda _v: {
                    "outcome": "keep",
                    "rationale": (
                        f"inference served by {response.served_by}"
                        f"{' (fallback)' if response.is_fallback else ''}"
                    ),
                },
                quadrant="active_probabilistic",
            )
        except Exception:
            logger.exception("inference-router: ledger write failed")
            raise


def _env_truthy(name: str) -> bool:
    """Truthy parse for boolean-shaped env flags (DEMO.1.C).

    Accepts 1/true/yes/on (case-insensitive). Empty / unset / anything
    else is falsy. Pinned in one helper so adding a new boolean env
    var doesn't drift the parsing rule.
    """
    import os

    raw = os.environ.get(name, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def build_default_router(
    *,
    cache_path: str | None = None,
    ledger: Any | None = None,
    company_id: UUID | None = None,
    cache_only: bool | None = None,
) -> CachedRouter:
    """Production-shape router from environment variables.

    * ``cache_path`` — explicit override; falls back to
      ``WORMBASE_INFERENCE_CACHE_PATH``, then a process-tmp default.
    * ``ledger`` — pass an instance for production; ``None`` in tests.
    * ``cache_only`` — DEMO.1.C. When True, refuse network I/O and
      raise :class:`CacheMissError` on cache misses. ``None`` (default)
      reads ``WORMBASE_INFERENCE_CACHE_ONLY`` from the environment;
      pass ``False`` explicitly to override an env-set demo mode.
    """
    import os
    from pathlib import Path

    from wormbase_inference.cache import SqliteInferenceCache

    path_str = (
        cache_path
        or os.environ.get("WORMBASE_INFERENCE_CACHE_PATH")
        or "/tmp/wormbase-inference-cache.sqlite"
    )
    cache: InferenceCache
    if path_str.lower() in ("none", "off", "disabled"):
        cache = NullInferenceCache()
    else:
        cache = SqliteInferenceCache(Path(path_str))
    if cache_only is None:
        cache_only = _env_truthy("WORMBASE_INFERENCE_CACHE_ONLY")
    return CachedRouter(
        kimi=KimiClient(),
        gemma=GemmaClient(),
        cache=cache,
        ledger=ledger,
        company_id=company_id,
        cache_only=cache_only,
    )


__all__ = [
    "CacheMissError",
    "CachedRouter",
    "build_cache_key",
    "build_default_router",
]
