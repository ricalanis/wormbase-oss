"""Factory: the four process-worm Reactivities, in deterministic order.

Mirrors lake-maintainer's ``make_maintenance_reactivities``
(``packages/lake-maintainer/src/wormbase_lake_maintainer/factory.py:23-35``)
— a single point of construction enforces the (process-worm × Reactivity)
cardinality structurally. The factory is the only place the four-class
contract lives; lifecycle code, tests, and audit log all read it from
here.

Order (fixed): TopicSynthesis, RecurringQuestion, DecisionRecord,
SystemMapNode. Callers may rely on this ordering for positional
metadata; adding a new Reactivity must extend the tail.

Import discipline: this module must NOT pull in ``wormbase_llm`` or
``wormbase_core`` at import time — LLM resolution is lazy via
``context.extras`` (see ``reactivities.py:_resolve_llm_client``), and
worm-core is the consumer of the lifecycle hook, not a dep.
"""
from __future__ import annotations

from wormbase_reactivities.protocol import Reactivity

from wormbase_process_extractor.reactivities import (
    DecisionRecordReactivity,
    RecurringQuestionReactivity,
    SystemMapNodeReactivity,
    TopicSynthesisReactivity,
)


def make_process_reactivities(
    *,
    llm_client: object | None = None,
    topic_labeler: object | None = None,
    decision_per_tenant_budget: int = 20,
    decision_novelty_hours: float = 1.0,
    system_map_per_tenant_budget: int = 50,
    topic_per_tenant_budget: int = 50,
    recurring_threshold: int = 3,
    recurring_window_days: int = 14,
    recurring_per_tenant_budget: int = 5,
) -> list[Reactivity]:
    """Build the four process-worm Reactivities.

    The ``llm_client`` and ``topic_labeler`` parameters are accepted for
    API symmetry with ``wire_process_for_install`` but are not threaded
    into the constructed instances — both adapters are resolved lazily
    via ``ReactivityContext.extras`` (see ``reactivities.py``:
    ``_resolve_llm_client`` for decisions,
    ``_resolve_topic_labeler`` for topics). The factory keeps the
    parameters so call sites can be uniform between the two surfaces
    even if a future Reactivity wants the adapter at construction time.

    Returns:
        ``[TopicSynthesisReactivity,
           RecurringQuestionReactivity (P10 alias),
           DecisionRecordReactivity,
           SystemMapNodeReactivity]``
    """
    return [
        TopicSynthesisReactivity(
            per_tenant_budget=topic_per_tenant_budget,
        ),
        RecurringQuestionReactivity(
            threshold=recurring_threshold,
            window_days=recurring_window_days,
            per_tenant_budget=recurring_per_tenant_budget,
        ),
        DecisionRecordReactivity(
            per_tenant_budget=decision_per_tenant_budget,
            novelty_hours=decision_novelty_hours,
        ),
        SystemMapNodeReactivity(
            per_tenant_budget=system_map_per_tenant_budget,
        ),
    ]


__all__ = ["make_process_reactivities"]
