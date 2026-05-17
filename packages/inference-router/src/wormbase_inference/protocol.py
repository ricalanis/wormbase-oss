"""Block B — :class:`Router` Protocol + :class:`RouteRequest` /
:class:`RouteResponse` value objects.

The router is the only abstraction every WormBase inference consumer
should depend on. Concrete clients (Kimi, Gemma) live in :mod:`clients`;
the cache + ledger-aware composition lives in :mod:`router`.

Design notes
------------

- ``call_type`` drives backend selection. ``"reasoning"`` and
  ``"affirm"`` go to Kimi by default; ``"classify"``, ``"summarize"``,
  ``"embed_prompt"`` go to Gemma. Consumers may override with
  ``backend_hint``.
- ``RouteRequest`` is **frozen and hashable** so it's safe to use as a
  cache key directly without re-serializing.
- ``RouteResponse.served_by`` matches the ``InferenceServedPayload``
  ``Literal`` set so the caller can hand the field straight to the
  ledger writer.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields as _dc_fields
from typing import Literal, Protocol, runtime_checkable

from wormbase_inference.agent_id import GovernanceContext

CallType = Literal[
    "reasoning",             # frontier reasoning, planning, multi-step (Kimi)
    "affirm",                # decision affirmation (Kimi by default)
    "classify",              # classification (Gemma)
    "summarize",             # short-form summarization (Gemma)
    "voice_turn",            # voice agent turn (Kimi)
    "agent_tool_reasoning",  # agent-gateway MCP tool invocation (Kimi by default)
    "embed_query",           # query embedding for semantic dispatch (Gemma)
    "generic",                # explicit-backend-only; router refuses to pick
]

BackendHint = Literal["kimi", "gemma", "auto"]
# ``claude`` is intentionally KEPT in the Literal (Phase 0 §6 finding):
# this field documents WHICH MODEL produced this content (provenance),
# not which client WormBase invoked. External agents that call WormBase
# MCP via Claude may need their inference tagged as Claude-served in the
# audit trail — that asymmetry between invocation-locus and
# generation-locus is the whole point of the Wave 2 audit story.
ServedBy = Literal["kimi", "gemma", "claude", "cache"]


@dataclass(frozen=True, slots=True)
class RouteRequest:
    """Inputs to a single inference call.

    The ``messages`` field is an OpenAI-shaped chat array. ``system`` is
    a convenience for callers that prefer a single system string; if both
    are supplied, ``messages`` wins (it's already structured).

    ``temperature`` defaults to ``0.0`` — every inference under the
    router should be deterministic by default; callers that want
    creative variance set it explicitly.
    """

    call_type: CallType
    messages: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    system: str | None = None
    backend_hint: BackendHint = "auto"
    temperature: float = 0.0
    max_tokens: int | None = None
    # Caller-provided tag for ledger provenance (e.g. ``"chat-presence"``,
    # ``"voice-agent"``, ``"process-extractor.affirm_decision"``).
    #
    # Phase 0 §7 finding: this stays ``str``, NOT ``AgentID``. ``frozen=True``
    # + ``slots=True`` blocks ``__post_init__`` AgentID coercion, and
    # retyping the field would break every existing internal call site at
    # once. The conversion to ``AgentID`` happens at the boundary inside
    # :meth:`CachedRouter.call` via :meth:`AgentID.from_legacy_string`.
    requested_by: str = "unknown"
    # Free-form metadata that flows into the ``inference_served`` payload's
    # ``cache_key`` derivation. Keep small + JSON-serializable.
    extra: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    # Wave 2 agent-gateway integration: optional governance envelope
    # carrying the agent's grant ceiling + cost budget + redaction
    # policy. Added AFTER ``extra`` to preserve positional-arg
    # construction stability for existing call sites. Excluded from the
    # cache key on purpose — see ``_CACHE_KEY_FIELDS`` below.
    governance_context: GovernanceContext | None = None

    def messages_as_dicts(self) -> list[dict[str, str]]:
        """Render ``messages`` as the dict shape Ollama/OpenAI expects."""
        out: list[dict[str, str]] = []
        if self.system:
            out.append({"role": "system", "content": self.system})
        out.extend({"role": role, "content": text} for role, text in self.messages)
        return out


@dataclass(frozen=True, slots=True)
class RouteResponse:
    """Outputs of a single inference call."""

    text: str
    served_by: ServedBy
    is_fallback: bool
    cache_key: str
    latency_ms: int
    # Echo of the model the backend actually answered with (e.g.
    # ``"kimi-k2.6:cloud"`` or ``"gemma4:e4b"``). Useful for debugging
    # but not part of the cache identity (model is already mixed into
    # ``cache_key`` upstream).
    model: str = ""


@runtime_checkable
class Router(Protocol):
    """The single inference entry point WormBase code depends on.

    Implementations:

    * :class:`wormbase_inference.router.CachedRouter` — the production
      router; backed by Kimi + Gemma + sqlite cache + ledger writer.
    * Test fakes implement this Protocol directly to drive deterministic
      Reactivity tests (see ``test_router.py``).
    """

    async def call(self, request: RouteRequest) -> RouteResponse: ...

    async def aclose(self) -> None:
        """Release any owned httpx clients / sqlite handles."""
        ...


__all__ = [
    "BackendHint",
    "CallType",
    "RouteRequest",
    "RouteResponse",
    "Router",
    "ServedBy",
]


# ---------------------------------------------------------------------------
# Cache-key allow-list — fields that participate in the inference cache key.
#
# Excludes ``requested_by`` and ``governance_context``: both are metadata
# about WHO asked / WHAT-CEILING applied, not model inputs. Two
# RouteRequests differing only in those fields must hit the same cache
# entry (response text is governance-invariant; audit trail records who
# saw it under which envelope, but the model output is shared).
#
# The module-import-time assertion below enforces that this allow-list is
# a strict subset of actual RouteRequest fields — adding a new
# RouteRequest field without consciously deciding whether it's a cache
# input is impossible: the test in
# ``test_router_extension_cache_key.test_cache_key_fields_subset_of_route_request``
# also asserts the subset relationship as a guard against drift in the
# other direction.
# ---------------------------------------------------------------------------

_CACHE_KEY_FIELDS: tuple[str, ...] = (
    "call_type",
    "messages",
    "system",
    "backend_hint",
    "temperature",
    "max_tokens",
    "extra",
)


_ROUTE_REQUEST_FIELD_NAMES = {_f.name for _f in _dc_fields(RouteRequest)}
assert set(_CACHE_KEY_FIELDS) <= _ROUTE_REQUEST_FIELD_NAMES, (
    "_CACHE_KEY_FIELDS drifted from RouteRequest fields: "
    f"{set(_CACHE_KEY_FIELDS) - _ROUTE_REQUEST_FIELD_NAMES}"
)


# ---------------------------------------------------------------------------
# Default backend selection — used by :class:`CachedRouter` when the caller
# leaves ``backend_hint == "auto"``. Documented here so test fakes can
# import the same table.
# ---------------------------------------------------------------------------

_DEFAULT_ROUTING: dict[str, Literal["kimi", "gemma"]] = {
    "reasoning": "kimi",
    "affirm": "kimi",
    "classify": "gemma",
    "summarize": "gemma",
    "voice_turn": "kimi",
    # Wave 2 agent-gateway: MCP tool invocations default to Kimi
    # (frontier reasoning); query-embedding stays on Gemma (commodity
    # workload, owned VLAN endpoint).
    "agent_tool_reasoning": "kimi",
    "embed_query": "gemma",
    # ``generic`` has no default; callers must supply ``backend_hint``.
}


def default_backend(call_type: CallType) -> Literal["kimi", "gemma"] | None:
    return _DEFAULT_ROUTING.get(call_type)


__all__.append("default_backend")
