"""WormBase research-loop — Karpathy autoresearch loop as a package.

See `docs/superpowers/plans/2026-05-03-research-worm-extraction.md` for
the Wave C₁ extraction plan.

Public surface:

  * Block B.1 lift — the AutoresearchLoop class and its Team / Company
    siblings, plus their service-level runner wrappers and the
    ``PersonPosition`` value object.
  * Block C.1 lift — the autoresearch learn step (P9): lesson extraction,
    reading, and ``applied_at`` stamping.
  * Block D.1 lift — the keep-rate publisher (P1): per-scope keep-rate
    publication + the long-lived ``KeepRatePublisher`` loop class.
  * Block F.1 — ``ExperimentTriggerReactivity``: the W5a wrap of the
    propose → run → resolve → publish_keep_notebook sequence. Replaces
    the wall-clock timer with a ledger-driven trigger.
  * Block F.2 — ``ExperimentResolveReactivity`` + ``resolve_experiment``
    + ``publish_keep_notebook``: keep/discard idempotency insurance.
  * Block F.3 — ``LessonExtractionReactivity``: closes Karpathy's
    autoresearch loop on itself by extracting one lesson per kept
    experiment.
  * Block F.4 — ``KeepRatePublishReactivity``: periodic per-scope keep-
    rate publication via the lifted ``KeepRatePublisher``.
  * Block G.1 — ``make_research_reactivities`` factory +
    ``wire_research_for_install`` lifecycle hook. Single point of
    construction so the four-instance cardinality is enforced
    structurally; mirrors lake-maintainer / chat-presence /
    identity-tracker wiring shape.
"""
from __future__ import annotations

from wormbase_research_loop.factory import (
    make_research_reactivities,
    wire_research_for_install,
)
from wormbase_research_loop.keep_rate import (
    KeepRatePublisher,
    publish_for_day,
)
from wormbase_research_loop.learn import (
    extract_lesson,
    extract_lesson_features,
    extract_lessons_for_kept,
    mark_lessons_applied,
    recent_lessons_for_scope,
    render_lesson_for_rationale,
)
from wormbase_research_loop.loop import (
    AutoresearchLoop,
    CompanyAutoresearchLoop,
    PersonPosition,
    TeamAutoresearchLoop,
    autoresearch_loop_runner,
    company_loop_runner,
    team_loop_runner,
)
from wormbase_research_loop.reactivities import (
    ExperimentResolveReactivity,
    ExperimentTriggerReactivity,
    KeepRatePublishReactivity,
    LessonExtractionReactivity,
    publish_keep_notebook,
    resolve_experiment,
)

__all__ = [
    "AutoresearchLoop",
    "CompanyAutoresearchLoop",
    "ExperimentResolveReactivity",
    "ExperimentTriggerReactivity",
    "KeepRatePublishReactivity",
    "KeepRatePublisher",
    "LessonExtractionReactivity",
    "PersonPosition",
    "TeamAutoresearchLoop",
    "autoresearch_loop_runner",
    "company_loop_runner",
    "extract_lesson",
    "extract_lesson_features",
    "extract_lessons_for_kept",
    "make_research_reactivities",
    "mark_lessons_applied",
    "publish_for_day",
    "publish_keep_notebook",
    "recent_lessons_for_scope",
    "render_lesson_for_rationale",
    "resolve_experiment",
    "team_loop_runner",
    "wire_research_for_install",
]
