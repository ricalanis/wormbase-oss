# > AUTHORED 2026-05-03: Block G.1 of the research-worm extraction.
# > Mirrors lake-maintainer / chat-presence / identity-tracker factory
# > shape — single point of construction so the four-instance cardinality
# > is enforced structurally. The wire helper is the lifecycle hook
# > worm-core's boot path calls once per Install.
"""Factory + wire helper for the four research-loop Reactivities.

Block G.1 of the research-worm extraction (Wave C₁). The four
Reactivities lifted in Block F (ExperimentTrigger, ExperimentResolve,
LessonExtraction, KeepRatePublish) need a single point of construction
so worm-core's boot path can register them with one call per Install.

Per the lake-maintainer / chat-presence / identity-tracker template the
factory:

  * Returns Reactivities in a fixed, documented order — caller-side
    telemetry can rely on it.
  * Accepts dependency-injectable hooks (publisher, per-scope budget)
    as keyword args; defaults are sensible for production.
  * Does NOT eagerly construct services that need ledger/company_id.
    The KeepRatePublisher is built lazily inside the Reactivity's
    ``fire`` body when the caller doesn't supply one — keeps the factory
    free of side effects and avoids fabricating dummy ids.

The wire helper (``wire_research_for_install``) is the lifecycle hook
the worm-core boot path calls. It mirrors
``wire_chat_for_install`` / ``wire_identity_for_install`` shape:

  * Per-Install scope (Reactivities are company-scoped — one Install ↔
    one (tenant, channel-platform) pair).
  * Side effect: registers each Reactivity with the supplied registry
    at the default ``initial_state="active"`` (code-registered
    reactivities are trusted per ReactivityRegistry.register docstring).
  * Returns ``None`` — there is no resolver Protocol to thread back to
    callers (research-loop is downstream-only). This is the simpler
    shape; chat-worm's bundle return is the more complex case.
"""
from __future__ import annotations

from typing import Any

from wormbase_ledger import InMemoryLedger, Ledger
from wormbase_reactivities.protocol import Reactivity

from wormbase_research_loop.keep_rate import KeepRatePublisher
from wormbase_research_loop.reactivities import (
    ExperimentResolveReactivity,
    ExperimentTriggerReactivity,
    KeepRatePublishReactivity,
    LessonExtractionReactivity,
)


def make_research_reactivities(
    *,
    publisher: KeepRatePublisher | None = None,
    per_scope_daily_budget: int = 3,
) -> list[Reactivity]:
    """Build the four research-loop Reactivities.

    Args:
        publisher: optional pre-built ``KeepRatePublisher``. When ``None``
            (default), the ``KeepRatePublishReactivity`` lazily constructs
            one inside its ``fire`` body from ``context.ledger`` /
            ``context.company_id``. Tests + advanced callers may inject
            a publisher up-front; production wiring relies on the lazy
            path.
        per_scope_daily_budget: max experiments per (scope_kind, scope_id)
            per UTC day, threaded into ``ExperimentTriggerReactivity``.
            Default 3 — conservative, matches the F.1 spec default.

    Returns the four Reactivities in a fixed order:

      1. ``ExperimentTriggerReactivity`` — propose+run+resolve+publish
         on the five upstream entry kinds (phenomenon_gap_detected,
         metric_observed, experiment_lesson, experiment_resolved,
         chat_received).
      2. ``ExperimentResolveReactivity`` — keep/discard idempotency
         insurance for ``experiment_run`` rows that landed outside the
         trigger Reactivity's fire path.
      3. ``LessonExtractionReactivity`` — extracts one
         ``experiment_lesson`` per kept ``experiment_resolved`` row,
         closing Karpathy's autoresearch loop on itself.
      4. ``KeepRatePublishReactivity`` — periodically publishes per-scope
         keep-rate via the lifted ``KeepRatePublisher``.

    The order is part of the contract: caller-side telemetry / logging
    relies on it (see chat-presence's ``make_chat_reactivities`` for the
    same convention).
    """
    return [
        ExperimentTriggerReactivity(
            per_scope_daily_budget=per_scope_daily_budget,
        ),
        ExperimentResolveReactivity(),
        LessonExtractionReactivity(),
        KeepRatePublishReactivity(publisher=publisher),
    ]


async def wire_research_for_install(
    *,
    install: Any,
    ledger: Ledger | InMemoryLedger,
    reactivity_registry: Any,  # ReactivityRegistry — typed Any to avoid
                                # importing it (light dep policy, mirrors
                                # identity-tracker's lifecycle.py)
    publisher: KeepRatePublisher | None = None,
    per_scope_daily_budget: int = 3,
) -> None:
    """Register the four research-loop Reactivities with the W5a registry.

    Per **C5** of the spike, scope is per-Install — one (tenant, channel-
    platform) pair. Reactivities are company-scoped so this function is
    called once per Install at boot.

    Side effects:

      1. Calls ``make_research_reactivities`` to build the four
         Reactivities.
      2. Registers each with the supplied ``ReactivityRegistry`` at the
         default ``initial_state="active"``.

    Args:
        install: duck-typed in v1 (no formal Install dataclass yet —
            same posture as identity-worm Wave A and chat-worm). The
            factory does not currently read ``install.id`` /
            ``install.platform``; they are reserved for future
            platform-aware wiring.
        ledger: the ledger handle (Ledger or InMemoryLedger). Forwarded
            into the optional ``KeepRatePublisher`` when the caller
            wants to construct one up-front; the lazy publisher path
            inside ``KeepRatePublishReactivity.fire`` reads it from
            ``context.ledger`` instead.
        reactivity_registry: the W5a ``ReactivityRegistry`` to register
            into. Typed ``Any`` to keep this module's import surface
            light (the registry import is heavy enough that lake-
            maintainer and identity-tracker also avoid it here).
        publisher: optional pre-built ``KeepRatePublisher``; passed
            through to ``make_research_reactivities``.
        per_scope_daily_budget: max experiments per (scope_kind,
            scope_id) per UTC day, threaded through to the trigger
            Reactivity. Default 3.

    Returns ``None``. Research-loop is downstream-only — no resolver
    Protocol to thread back to callers.
    """
    reactivities = make_research_reactivities(
        publisher=publisher,
        per_scope_daily_budget=per_scope_daily_budget,
    )
    for r in reactivities:
        reactivity_registry.register(r)


__all__ = [
    "make_research_reactivities",
    "wire_research_for_install",
]
