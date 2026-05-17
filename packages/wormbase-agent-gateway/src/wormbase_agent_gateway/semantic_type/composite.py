"""L5 semantic-type fingerprinting — composite via LakeLoopComposite[T].

:func:`make_composite_semantic_type_service` composes any subset of the
3 strategies (ColumnName, ValuePattern, Distribution) via Optional-
Effect Injection (doctrine case 12). Each strategy slot is independently
``None``-able; missing slots short-circuit to empty proposal lists and
increment the composite's no-op telemetry counter.

The factory returns a :class:`LakeLoopComposite` parameterised over
:class:`ProposedSemanticType` — the abstraction does ALL the heavy
lifting. Per spec §3.6, this is **~15 LOC of factory code instead of
~250 LOC of a duplicated composite class** — the smoking-gun validation
that the :class:`LakeLoopComposite` extraction shipped at ``a4a62c2``
pays off for new consumers.

Doctrine case 12 framing extends cases 9 (L3) / 10 (L7) / 11 (L4) to a
fourth L-axis Compounding service with the same Optional-Effect
Injection contract. Unlike L4, L5 does NOT introduce a new cross-axis
read Protocol — strategies reuse L3's :class:`SamplerProtocol` and
L7's :class:`HistoricalStatsReader` directly (see
:mod:`.strategies` reuse-policy docstring).

Pre-extraction L3/L7/L4 each carried a ~80 LOC custom composite class
plus a ~40 LOC ``_merge_proposals`` helper. L5 has neither — it is
born sharing the shared generic. The factory function below is the
ENTIRE composition surface; no merge-cluster hook is needed because
the default :func:`wormbase_agent_gateway.lake_loop.default_cluster_merge`
behavior matches L5's contract exactly (same-``type_id`` clusters
merge by max confidence + composite reasoning).
"""
from __future__ import annotations

from wormbase_agent_gateway.lake_loop import LakeLoopComposite

from .protocol import ProposedSemanticType
from .strategies import (
    ColumnNameFingerprintStrategy,
    DistributionFingerprintStrategy,
    ValuePatternFingerprintStrategy,
)

__all__ = ["make_composite_semantic_type_service"]


def make_composite_semantic_type_service(
    *,
    column_name: ColumnNameFingerprintStrategy | None = None,
    value_pattern: ValuePatternFingerprintStrategy | None = None,
    distribution: DistributionFingerprintStrategy | None = None,
) -> LakeLoopComposite[ProposedSemanticType]:
    """Compose the 3 L5 fingerprinting strategies via :class:`LakeLoopComposite`.

    Optional-Effect Injection (doctrine case 12 — first lake-side axis
    built on top of :class:`LakeLoopComposite` from day one). Each slot
    independently ``None``-able; the returned composite still implements
    :class:`.protocol.FingerprintStrategy` and returns an empty proposal
    list when every strategy is ``None``.

    Strategy execution order: ``column_name → value_pattern →
    distribution``. Order is pinned by tests for replay stability of
    the composite's reasoning string (column_name fires first so its
    "regex matched ..." prefix lands ahead of value/distribution
    explanations).

    The factory body is ~15 LOC by design — see the module docstring
    for the validation framing. No custom composite class is needed.
    """
    return LakeLoopComposite[ProposedSemanticType](
        case_name="fingerprint_inference",
        strategies={
            "column_name": column_name,
            "value_pattern": value_pattern,
            "distribution": distribution,
        },
        propose_method="propose",
        identity_key=lambda p: p.type_id,
        proposals_counter_name="types_proposed",
    )
