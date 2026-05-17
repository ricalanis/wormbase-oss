"""AgentID + GovernanceContext value types.

Router-extension types for the Wave 2 agent-gateway integration.

Phase 0 §7 finding (spike commit ``dc59518``): :class:`RouteRequest` is
``frozen=True, slots=True``; this BLOCKS a ``__post_init__``-based
AgentID coercion path. The spike's design that retyped
``RouteRequest.requested_by`` to ``AgentID`` failed because slotted
frozen dataclasses cannot coerce field types after construction.

The reconciliation:

- ``RouteRequest.requested_by`` STAYS ``str = "unknown"`` at the
  dataclass boundary, preserving the existing call-site contract for
  chat-presence / process-extractor / voice-agent and every other
  internal consumer.
- The conversion to :class:`AgentID` happens INSIDE
  :meth:`CachedRouter.call` (or wherever the ``inference_served``
  ledger emission lives), via :meth:`AgentID.from_legacy_string`.
- :class:`GovernanceContext` carries the agent-grant context (cost
  ceiling, classification ceiling, redaction policy, domain scope)
  through to the audit-emission site.

This module is import-cheap; no I/O, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class AgentID:
    """Typed wrapper over ``str`` agent identifiers.

    Constructed at the inference-router boundary (inside
    ``CachedRouter.call``) from ``RouteRequest.requested_by``, not at
    the dataclass field level (see module docstring for the slots=True
    incompatibility).
    """

    value: str

    @classmethod
    def from_legacy_string(cls, s: str) -> "AgentID":
        """Boundary-convert a legacy ``requested_by`` string to AgentID.

        ``"unknown"`` is preserved verbatim — it's a sentinel that
        downstream audit filters recognize as "no agent attribution
        available."
        """
        return cls(value=s)


Classification = Literal[
    "public",
    "internal",
    "confidential",
    "pii",
    "regulated",
]


@dataclass(frozen=True)
class GovernanceContext:
    """Per-call governance envelope for agent-mediated inference.

    Threaded onto :class:`RouteRequest` as
    ``governance_context: GovernanceContext | None`` so the router can
    surface the agent's grant ceiling + budget + redaction policy in
    the ``inference_served`` audit row without round-tripping through
    a separate audit store.

    Excluded from the cache key on purpose: two requests that differ
    only by governance envelope should hit the same cached response
    (the response text is governance-invariant; the audit trail is
    what records who saw it under which envelope).
    """

    classification_ceiling: Classification = "internal"
    cost_budget_usd: Decimal | None = None
    pii_redaction: bool = True
    domain_id: str | None = None


__all__ = [
    "AgentID",
    "Classification",
    "GovernanceContext",
]
