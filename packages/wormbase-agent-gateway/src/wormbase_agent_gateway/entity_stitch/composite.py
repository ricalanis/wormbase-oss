"""L8 cross-source entity stitching — composite via LakeLoopComposite[T].

:func:`make_composite_entity_stitch_service` composes any subset of the
3 strategies (NameMatch, SampleOverlap, SchemaShape) via Optional-Effect
Injection (doctrine case 14 — **third lake-side axis built on top of
:class:`LakeLoopComposite` from day one**, after L5's case 12 and L6's
case 13). Each strategy slot is independently ``None``-able; missing
slots short-circuit to empty proposal lists and increment the
composite's no-op telemetry counter.

The factory returns a :class:`LakeLoopComposite` parameterised over
:class:`ProposedEntityStitch` — the abstraction does ALL the heavy
lifting. Per spec §4.7, this is **~15 LOC of factory code instead of
~250 LOC of a duplicated composite class** — continuing the smoking-gun
validation that the :class:`LakeLoopComposite` extraction shipped at
``a4a62c2`` pays off for new consumers. **Third from-day-one
consumer.**

Doctrine case 14 framing extends cases 9 (L3) / 10 (L7) / 11 (L4) /
12 (L5) / 13 (L6) to a sixth L-axis Compounding service with the same
Optional-Effect Injection contract. L8 introduces ZERO new Protocols
— the NameMatch strategy reuses L6's
:class:`ConfirmedSemanticTypeReader` (second consumer; first is L6's
own SemanticTypeClassificationStrategy) and the SampleOverlap strategy
reuses L7's :class:`SamplerProtocol`.

Identity key: ``stitch_id`` (order-independent hash of the two
endpoint triples; omits strategy + confidence). Rationale: per spec
§4.4, L8 wants cross-strategy merge behaviour — when multiple
strategies propose the same pair, the composite folds them into one
projection row with the highest-confidence winner (mirrors L5's
merge-on-(table,col,type); diverges from L6's keep-separate-by-strategy
posture).
"""
from __future__ import annotations

from wormbase_agent_gateway.lake_loop import LakeLoopComposite

from .protocol import ProposedEntityStitch
from .strategies import (
    NameMatchEntityStrategy,
    SampleOverlapEntityStrategy,
    SchemaShapeEntityStrategy,
)

__all__ = ["make_composite_entity_stitch_service"]


def make_composite_entity_stitch_service(
    *,
    name_match: NameMatchEntityStrategy | None = None,
    sample_overlap: SampleOverlapEntityStrategy | None = None,
    schema_shape: SchemaShapeEntityStrategy | None = None,
    min_confidence: float | None = None,
) -> LakeLoopComposite[ProposedEntityStitch]:
    """Compose the 3 L8 entity-stitch strategies via :class:`LakeLoopComposite`.

    Optional-Effect Injection (doctrine case 14 — third lake-side axis
    built on top of :class:`LakeLoopComposite` from day one). Each slot
    independently ``None``-able; the returned composite still implements
    :class:`.protocol.EntityStitchStrategy` and returns an empty
    proposal list when every strategy is ``None``.

    Strategy execution order: ``name_match → sample_overlap →
    schema_shape``. Order is pinned by tests for replay stability of
    the composite's reasoning string (name_match fires first when L5
    has signal so its cross-axis citation lands ahead of the
    sampling/structural explanations).

    Identity key is ``stitch_id`` — the order-independent hash of the
    two endpoint triples. So two strategies proposing the same pair (in
    either argument order) collide on the same id and merge into one
    projection row (per spec §4.4; mirrors L5's merge-on-(table,col,
    type), diverges from L6's keep-separate-by-strategy by design).

    ``min_confidence``: optional promotion-time floor. When set,
    proposals with ``confidence < min_confidence`` are dropped
    POST-merge by the underlying :class:`LakeLoopComposite`. Wired
    from ``WORMBASE_ENTITY_STITCH_MIN_CONFIDENCE`` at the worm-core
    construction site. ``None`` (default) = no filtering (back-compat
    for tests that don't supply a knob).

    The factory body is ~15 LOC by design — see the module docstring
    for the validation framing. No custom composite class is needed.
    """
    return LakeLoopComposite[ProposedEntityStitch](
        case_name="entity_stitch_inference",
        strategies={
            "name_match": name_match,
            "sample_overlap": sample_overlap,
            "schema_shape": schema_shape,
        },
        propose_method="propose",
        identity_key=lambda p: p.stitch_id,
        proposals_counter_name="stitches_proposed",
        min_confidence=min_confidence,
    )
