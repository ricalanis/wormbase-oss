"""Shared abstractions for lake-side L-axis composite services.

Three lake-side axes share a near-identical composite shape: L3 lineage
discovery (:class:`wormbase_agent_gateway.lineage.CompositeLineageInferenceService`),
L7 quality-check discovery
(:class:`wormbase_agent_gateway.quality.CompositeQualityProposalService`),
and L4 schema-evolution-impact
(:class:`wormbase_agent_gateway.schema_impact.CompositeSchemaImpactService`).

The OptionalEffectGuard precedent — *extract when the 3rd consumer
ships* — fired on the L4 close-out (HEAD = ``d80b076``). This module
extracts the shared shape into :class:`.composite.LakeLoopComposite` so
the three axes share a single tested generic, while leaving the per-
axis ledger/projection/dashboard surfaces fully duplicated (those are
axis-specific and over-coupling them would harm clarity).

Public surfaces:

  * :class:`LakeLoopStrategy` — the per-strategy shape: a ``name`` and
    an async propose method (the method name varies per axis;
    :class:`.composite.LakeLoopComposite` dispatches by configurable
    ``propose_method``).
  * :data:`LakeLoopProposal` — :class:`typing.Protocol` describing the
    structural shape every axis's proposal type satisfies (``confidence``
    + ``strategy`` + ``reasoning`` + ``evidence``). Used as a TypeVar
    bound on the composite for type-safety without forcing all proposals
    to inherit a shared base.

The Protocol is intentionally structural — the existing per-axis
dataclasses (:class:`~wormbase_agent_gateway.lineage.InferredEdge`,
:class:`~wormbase_agent_gateway.quality.ProposedQualityCheck`,
:class:`~wormbase_agent_gateway.schema_impact.ProposedImpact`) already
satisfy it without inheritance changes. No ledger-payload coupling is
forced on consumers.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["LakeLoopProposal", "LakeLoopStrategy"]


@runtime_checkable
class LakeLoopProposal(Protocol):
    """Structural shape every lake-side proposal type satisfies.

    The three axes' proposal dataclasses
    (:class:`~wormbase_agent_gateway.lineage.InferredEdge`,
    :class:`~wormbase_agent_gateway.quality.ProposedQualityCheck`,
    :class:`~wormbase_agent_gateway.schema_impact.ProposedImpact`) all
    carry these four fields — the composite reads them when merging
    duplicates. Axis-specific fields (``edge_id`` / ``check_id`` /
    ``impact_id`` / ``upstream_lineage_edge_id`` / ``config`` etc.) are
    handled by axis-side merge hooks (see :func:`.composite.default_merge_winner`).

    The Protocol is structural / non-inheritable on purpose — none of
    the axis dataclasses must change to satisfy it.
    """

    confidence: float
    strategy: str
    reasoning: str
    evidence: dict[str, Any]


@runtime_checkable
class LakeLoopStrategy(Protocol):
    """Per-strategy shape the lake-loop composite consumes.

    The composite calls ``getattr(strategy, propose_method)(**kwargs)``
    where ``propose_method`` is the axis-configured method name
    (``infer_edges`` for L3, ``propose_checks`` for L7, ``propose_impacts``
    for L4). All three axes already satisfy this shape — see each axis's
    ``protocol.py`` for the per-axis Protocol that pins the exact
    signature.

    Held as ``Protocol`` rather than an ABC so existing strategies stay
    duck-typed; the composite never type-checks strategies at runtime
    beyond the existing per-axis Protocol contract.
    """

    name: str
