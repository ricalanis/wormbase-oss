"""Shared lake-side composite abstraction for L3 / L7 / L4 axes.

Extracted from the three lake-side axes on 2026-05-15 (HEAD = ``d80b076``)
once the OptionalEffectGuard precedent — *extract when the 3rd consumer
ships* — fired. Before extraction, each of
:class:`wormbase_agent_gateway.lineage.CompositeLineageInferenceService`,
:class:`wormbase_agent_gateway.quality.CompositeQualityProposalService`,
and :class:`wormbase_agent_gateway.schema_impact.CompositeSchemaImpactService`
carried a near-identical ~80-LOC composite class. The three now share
:class:`LakeLoopComposite` while keeping their per-axis wrappers thin,
public surfaces unchanged, and ledger/projection/dashboard layers
fully duplicated by design.

Per-axis Compounding-factory boilerplate (``make_<axis>_discovery_reactivity``
in :mod:`wormbase_agent_gateway.reactivities`) is **NOT** extracted here.
The axis-specific surfaces (gather_fn payloads, idempotency_filter
tool-name lookups, promotion_action emit functions tied to per-axis
ledger entry kinds) do not share cleanly — the boilerplate has too many
axis-specific bits to wrap in a single helper without bloating the
helper's parameter surface beyond comprehension. Deferred to a future
refactor when a fourth axis ships (see also the OptionalEffectGuard
precedent).
"""
from __future__ import annotations

from .composite import (
    LakeLoopComposite,
    default_cluster_merge,
    default_merge_winner,
)
from .protocol import LakeLoopProposal, LakeLoopStrategy

__all__ = [
    "LakeLoopComposite",
    "LakeLoopProposal",
    "LakeLoopStrategy",
    "default_cluster_merge",
    "default_merge_winner",
]
