"""L1 source-candidate triage — composite via LakeLoopComposite[T].

:func:`make_composite_source_candidate_service` composes any subset of
the 3 strategies (KpiGap, ChannelMention, Complementarity) via
Optional-Effect Injection (doctrine case 15 — **fourth lake-side axis
built on top of :class:`LakeLoopComposite` from day one**, after L5's
case 12, L6's case 13, L8's case 14). Each strategy slot is
independently ``None``-able; missing slots short-circuit to empty
proposal lists and increment the composite's no-op telemetry counter.

The factory returns a :class:`LakeLoopComposite` parameterised over
:class:`ProposedSourceCandidate` — the abstraction does ALL the heavy
lifting. Per spec §4.7, this is **~14 LOC of factory code instead of
~250 LOC of a duplicated composite class** — continuing the
smoking-gun validation that the :class:`LakeLoopComposite` extraction
shipped at ``a4a62c2`` pays off for new consumers. **Fourth from-day-one
consumer.**

Doctrine case 15 framing extends cases 9 (L3) / 10 (L7) / 11 (L4) /
12 (L5) / 13 (L6) / 14 (L8) to a seventh L-axis Compounding service
with the same Optional-Effect Injection contract. L1 introduces ZERO
new cross-axis Protocol CHAINS (the L4→L3 / L6→L5 / L8→L5 sense). It
DOES introduce 3 new lightweight Reader Protocols
(:class:`ConnectedSourceReader`, :class:`KpiNodeReader`,
:class:`SilverConversationReader`), but these read first-class platform
projections, not peer L-axis projections — see :mod:`.protocol` for
the doctrine clarification.

Identity key: ``candidate_id`` (deterministic hash of
``(proposed_kind, proposed_identifier, strategy)``; INCLUDES strategy).
Rationale: per spec §4.7, L1 wants **kept-separate-by-strategy** dedup
behaviour (mirrors L6's
:func:`~wormbase_agent_gateway.column_classification.make_classification_id`,
diverges from L5's
:func:`~wormbase_agent_gateway.semantic_type.make_type_id` and L8's
:func:`~wormbase_agent_gateway.entity_stitch.make_stitch_id` which omit
strategy and merge across strategies). Reason: different strategies
proposing the same source surface independently on the admin queue —
each strategy gets to make its own case.
"""
from __future__ import annotations

from wormbase_agent_gateway.lake_loop import LakeLoopComposite

from .protocol import ProposedSourceCandidate
from .strategies import (
    ChannelMentionAcquisitionStrategy,
    ComplementaritySourceStrategy,
    KpiGapAcquisitionStrategy,
)

__all__ = ["make_composite_source_candidate_service"]


def make_composite_source_candidate_service(
    *,
    kpi_gap: KpiGapAcquisitionStrategy | None = None,
    channel_mention: ChannelMentionAcquisitionStrategy | None = None,
    complementarity: ComplementaritySourceStrategy | None = None,
    min_confidence: float | None = None,
) -> LakeLoopComposite[ProposedSourceCandidate]:
    """Compose the 3 L1 source-candidate strategies via :class:`LakeLoopComposite`.

    Optional-Effect Injection (doctrine case 15 — fourth lake-side axis
    built on top of :class:`LakeLoopComposite` from day one). Each slot
    independently ``None``-able; the returned composite still
    implements :class:`.protocol.SourceCandidateStrategy` and returns
    an empty proposal list when every strategy is ``None``.

    Strategy execution order: ``kpi_gap → channel_mention →
    complementarity``. Order is pinned by tests for replay stability
    of the composite's reasoning string and counter ordering. KpiGap
    fires first because it carries the strongest domain signal (KPI
    name + domain), so its cross-strategy citation lands ahead of the
    weaker portfolio-heuristic explanations.

    Identity key is ``candidate_id`` — the deterministic hash of
    ``(proposed_kind, proposed_identifier, strategy)``. Because
    ``strategy`` is in the hash, two strategies proposing the same
    (kind, identifier) get DISTINCT candidate_ids and surface as
    separate admin rows (kept-separate-by-strategy posture, per spec
    §4.7; mirrors L6, diverges from L5/L8).

    ``min_confidence``: optional promotion-time floor. When set,
    proposals with ``confidence < min_confidence`` are dropped
    POST-merge by the underlying :class:`LakeLoopComposite`. Wired
    from ``WORMBASE_SOURCE_CANDIDATE_MIN_CONFIDENCE`` at the
    worm-core construction site (L1 floor default 0.4 per spec §4.8).
    ``None`` (default) = no filtering (back-compat for tests that
    don't supply a knob).

    The factory body is ~14 LOC by design — see the module docstring
    for the validation framing. No custom composite class is needed.
    """
    return LakeLoopComposite[ProposedSourceCandidate](
        case_name="source_candidate_inference",
        strategies={
            "kpi_gap": kpi_gap,
            "channel_mention": channel_mention,
            "complementarity": complementarity,
        },
        propose_method="propose",
        identity_key=lambda p: p.candidate_id,
        proposals_counter_name="source_candidates_proposed",
        min_confidence=min_confidence,
    )
