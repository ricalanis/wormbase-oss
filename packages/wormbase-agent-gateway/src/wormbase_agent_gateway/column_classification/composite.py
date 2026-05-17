"""L6 column-level classification — composite via LakeLoopComposite[T].

:func:`make_composite_column_classification_service` composes any subset
of the 3 strategies (SemanticType, NamingPattern, DomainDefault) via
Optional-Effect Injection (doctrine case 13 — **second lake-side axis
built on top of :class:`LakeLoopComposite` from day one**, after L5's
case 12). Each strategy slot is independently ``None``-able; missing
slots short-circuit to empty proposal lists and increment the
composite's no-op telemetry counter.

The factory returns a :class:`LakeLoopComposite` parameterised over
:class:`ProposedColumnClassification` — the abstraction does ALL the
heavy lifting. Per spec §4.7, this is **~15 LOC of factory code instead
of ~250 LOC of a duplicated composite class** — continuing the smoking-
gun validation that the :class:`LakeLoopComposite` extraction shipped
at ``a4a62c2`` pays off for new consumers.

Doctrine case 13 framing extends cases 9 (L3) / 10 (L7) / 11 (L4) /
12 (L5) to a fifth L-axis Compounding service with the same Optional-
Effect Injection contract. L6 introduces ONE new cross-axis read
Protocol (:class:`.protocol.ConfirmedSemanticTypeReader`) — the 2nd
instance of the cross-axis pattern after L4's
:class:`LineageEdgeReader`. The composite itself does not own the
cross-axis read; the strategy that needs it
(:class:`.strategies.SemanticTypeClassificationStrategy`) injects the
reader via its own constructor.

Identity key: ``classification_id`` (which includes ``strategy``).
Rationale: per spec §4.4, L6 wants each strategy's per-column-per-
level proposal to be its own projection row so the admin queue can
compare strategies side-by-side. Two strategies proposing the SAME
``(table_id, column, level)`` produce DIFFERENT ``classification_id``s
and therefore DIFFERENT projection rows — they do NOT merge. (This
diverges from L5's merge behaviour by design.)
"""
from __future__ import annotations

from wormbase_agent_gateway.lake_loop import LakeLoopComposite

from .protocol import ProposedColumnClassification
from .strategies import (
    DomainDefaultClassificationStrategy,
    NamingPatternClassificationStrategy,
    SemanticTypeClassificationStrategy,
)

__all__ = ["make_composite_column_classification_service"]


def make_composite_column_classification_service(
    *,
    semantic_type: SemanticTypeClassificationStrategy | None = None,
    naming_pattern: NamingPatternClassificationStrategy | None = None,
    domain_default: DomainDefaultClassificationStrategy | None = None,
    min_confidence: float | None = None,
) -> LakeLoopComposite[ProposedColumnClassification]:
    """Compose the 3 L6 classification strategies via :class:`LakeLoopComposite`.

    Optional-Effect Injection (doctrine case 13 — second lake-side axis
    built on top of :class:`LakeLoopComposite` from day one). Each slot
    independently ``None``-able; the returned composite still implements
    :class:`.protocol.ColumnClassificationStrategy` and returns an
    empty proposal list when every strategy is ``None``.

    Strategy execution order: ``semantic_type → naming_pattern →
    domain_default``. Order is pinned by tests for replay stability of
    the composite's reasoning string (semantic_type fires first when
    L5 has signal so its cross-axis citation lands ahead of the
    pattern-based explanations).

    Identity key is ``classification_id`` which includes ``strategy`` —
    so two strategies proposing the same ``(table_id, column, level)``
    produce different ids and stay as separate projection rows (per
    spec §4.4; diverges from L5's merge-on-(table,column,type) by
    design so the admin queue surfaces strategy-by-strategy signal).

    ``min_confidence``: optional promotion-time floor. When set,
    proposals with ``confidence < min_confidence`` are dropped
    POST-merge by the underlying :class:`LakeLoopComposite`. Wired
    from ``WORMBASE_COLUMN_CLASSIFICATION_MIN_CONFIDENCE`` at the
    worm-core construction site. ``None`` (default) = no filtering
    (back-compat for tests that don't supply a knob).

    The factory body is ~15 LOC by design — see the module docstring
    for the validation framing. No custom composite class is needed.
    """
    return LakeLoopComposite[ProposedColumnClassification](
        case_name="column_classification_inference",
        strategies={
            "semantic_type": semantic_type,
            "naming_pattern": naming_pattern,
            "domain_default": domain_default,
        },
        propose_method="propose",
        identity_key=lambda p: p.classification_id,
        proposals_counter_name="classifications_proposed",
        min_confidence=min_confidence,
    )
