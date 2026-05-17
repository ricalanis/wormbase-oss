"""DEMO.1.C — pre-populated cache entries for the Acme demo.

The Acme SaaS demo (``wormbase demo acme-demo``) exercises every
LLM-driven surface of the dashboard: decision detection, topic
labeling, recurring-question summarization, position inference,
autoresearch experiment proposals. Each of those sites issues prompts
to the inference router. To make demo replays deterministic AND
independent of live Kimi / Gemma availability, we pre-compute the cache
entries here.

Each entry is keyed exactly the way the router would key it
(``make_cache_key(model, messages, temperature, extra)``), so a
production router pointed at a cache file populated by
:func:`populate_acme_cache` will return the cached answer for every
prompt the demo issues — without any network I/O — when
``WORMBASE_INFERENCE_CACHE_ONLY=1`` is set.

Adding a new prompt
-------------------

When a new LLM call site lands in the demo, append an entry to
:data:`ACME_DEMO_PROMPTS` and re-run::

    wormbase-demo-cache populate

The function is pure-Python and uses only the already-public surface of
:mod:`wormbase_inference.cache` and :mod:`wormbase_inference.clients`,
so it's safe to import anywhere in the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wormbase_inference.cache import (
    InferenceCache,
    SqliteInferenceCache,
    make_cache_key,
)
from wormbase_inference.clients import DEFAULT_GEMMA_MODEL, DEFAULT_KIMI_MODEL


@dataclass(frozen=True, slots=True)
class DemoPrompt:
    """One pre-cached LLM call.

    Attributes mirror the router's view of a request, so building a
    :class:`make_cache_key`-shaped key from a :class:`DemoPrompt` is
    one statement.

    ``backend`` selects which model name flows into the cache key —
    ``"kimi"`` resolves to :data:`DEFAULT_KIMI_MODEL`, ``"gemma"`` to
    :data:`DEFAULT_GEMMA_MODEL`. The router uses the same routing table
    (see ``protocol.default_backend``), so demo prompts issued via
    ``call_type=summarize`` (Gemma-by-default) must be cached under
    ``backend="gemma"``.
    """

    name: str
    backend: str  # "kimi" | "gemma"
    system: str
    user: str
    response: str
    temperature: float = 0.0
    extra: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def cache_key(self) -> str:
        """Produce the exact cache key the router would compute."""
        model = (
            DEFAULT_KIMI_MODEL if self.backend == "kimi" else DEFAULT_GEMMA_MODEL
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]
        return make_cache_key(
            model=model,
            messages=messages,
            temperature=self.temperature,
            extra=dict(self.extra),
        )

    def model(self) -> str:
        return (
            DEFAULT_KIMI_MODEL if self.backend == "kimi" else DEFAULT_GEMMA_MODEL
        )


# ---------------------------------------------------------------------------
# Acme demo prompt fixtures
# ---------------------------------------------------------------------------
#
# These cover every LLM-driven surface the demo touches. The system /
# user strings are the same ones the production adapters issue (see
# decision_adapter.py, topic_labeler_adapter.py, voice-agent, etc.).
# Responses are hand-written for clarity — production-shape (JSON for
# structured-extraction prompts, plain text for summaries).
#
# When the production prompt template changes, the cache key here must
# move with it — :func:`populate_acme_cache` does NOT re-derive prompts
# at runtime, so a drift surfaces as a cache miss + CacheMissError
# (which the contract test below pins).
# ---------------------------------------------------------------------------


ACME_DEMO_PROMPTS: tuple[DemoPrompt, ...] = (
    # ----- Decision detection (process-extractor) -------------------
    DemoPrompt(
        name="decision.q3.weekly-active",
        backend="kimi",
        system=(
            "You are a decision detector. Given a chat message, decide "
            "whether it records a team decision. Reply with JSON."
        ),
        user=(
            "for the Q3 review we decided to switch from MAU to "
            "weekly-active-customer as our primary engagement metric"
        ),
        response=(
            '{"is_decision": true, "decision_text": '
            '"Switch primary engagement metric from MAU to weekly-active-customer", '
            '"confidence": 0.92}'
        ),
    ),
    DemoPrompt(
        name="decision.q3.churn-30day",
        backend="kimi",
        system=(
            "You are a decision detector. Given a chat message, decide "
            "whether it records a team decision. Reply with JSON."
        ),
        user=(
            "we agreed to define churn as net-zero MRR for 30 consecutive "
            "days, not the previous 14-day rule"
        ),
        response=(
            '{"is_decision": true, "decision_text": '
            '"Define churn as net-zero MRR for 30 consecutive days (was 14)", '
            '"confidence": 0.95}'
        ),
    ),
    DemoPrompt(
        name="decision.q3.bob-resource-maintainer",
        backend="kimi",
        system=(
            "You are a decision detector. Given a chat message, decide "
            "whether it records a team decision. Reply with JSON."
        ),
        user=(
            "we will own the q3_revenue kpi at the team level — Bob is "
            "the resource maintainer"
        ),
        response=(
            '{"is_decision": true, "decision_text": '
            '"Bob is the resource maintainer for q3_revenue KPI", '
            '"confidence": 0.88}'
        ),
    ),
    # ----- Topic labeling (chat-presence) ---------------------------
    DemoPrompt(
        name="topic.label.q3-churn",
        backend="gemma",
        system=(
            "You label conversation topics. Reply with a 2-4 word topic "
            "phrase."
        ),
        user="what's our Q3 churn?",
        response="Q3 churn rate",
    ),
    DemoPrompt(
        name="topic.label.active-customer",
        backend="gemma",
        system=(
            "You label conversation topics. Reply with a 2-4 word topic "
            "phrase."
        ),
        user=(
            "we need a kpi for active customer count too — there's no "
            "source of truth right now"
        ),
        response="Active customer KPI",
    ),
    # ----- Recurring-question summarization (process-extractor) -----
    DemoPrompt(
        name="recurring.q3-churn-summary",
        backend="gemma",
        system=(
            "Summarize a recurring question pattern in one sentence. "
            "Highlight the asker, the askee, and the topic."
        ),
        user=(
            "Dave asked Alice 'what's our Q3 churn?' four times in #sales "
            "over the last hour."
        ),
        response=(
            "Dave repeatedly asks Alice about Q3 churn — the channel "
            "lacks a published KPI, suggesting a process gap."
        ),
    ),
    # ----- Position inference (identity-tracker) --------------------
    DemoPrompt(
        name="position.maya-sales-lead",
        backend="kimi",
        system=(
            "Score the chatter signal for an inferred position. Reply "
            "with JSON {position, score, evidence}."
        ),
        user="Maya is the Sales Lead for Q3 — she's owning the board narrative",
        response=(
            '{"position": "Sales Lead", "score": 0.91, "evidence": '
            '"explicit role attribution + ownership of board narrative"}'
        ),
    ),
    DemoPrompt(
        name="position.bob-resource-owner",
        backend="kimi",
        system=(
            "Score the chatter signal for an inferred position. Reply "
            "with JSON {position, score, evidence}."
        ),
        user="Bob owns the q3_revenue kpi — let's keep the maintainer line clean",
        response=(
            '{"position": "Resource Maintainer (q3_revenue)", '
            '"score": 0.87, "evidence": "explicit ownership claim '
            'with maintainer phrasing"}'
        ),
    ),
    # ----- Autoresearch experiment proposals (research-loop) --------
    DemoPrompt(
        name="research.high-value.exp1",
        backend="kimi",
        system=(
            "Propose an experiment to fill a phenomenon-gap. Reply with "
            "JSON {hypothesis, method, expected_metric}."
        ),
        user=(
            "Phenomenon-gap: 'high_value_customer' is referenced "
            "repeatedly in #data without a metric. Propose a "
            "MRR-tier-based definition."
        ),
        response=(
            '{"hypothesis": "Customers in the top MRR decile drive >60% '
            'of net revenue", "method": "Compute decile-share of net '
            'revenue from q3_revenue join customers", "expected_metric": '
            '"top_mrr_decile_revenue_share"}'
        ),
    ),
    DemoPrompt(
        name="research.high-value.exp2",
        backend="kimi",
        system=(
            "Propose an experiment to fill a phenomenon-gap. Reply with "
            "JSON {hypothesis, method, expected_metric}."
        ),
        user=(
            "Phenomenon-gap: 'high_value_customer' is referenced "
            "repeatedly in #data without a metric. Propose an "
            "engagement-cohort-based definition."
        ),
        response=(
            '{"hypothesis": "Customers in the top engagement-quartile '
            'churn at <50% the rate of the bottom three quartiles", '
            '"method": "Cohort customers by weekly-active days; compute '
            'churn rate per quartile", "expected_metric": '
            '"engagement_quartile_churn_ratio"}'
        ),
    ),
    # ----- Lesson extraction (research-loop) ------------------------
    DemoPrompt(
        name="research.lesson-churn-policy",
        backend="kimi",
        system="Extract a one-sentence lesson from a research outcome.",
        user=(
            "Result: defining churn as 30-day net-zero MRR yielded a "
            "5% lower noise-floor in the Q3 cohort vs the 14-day rule. "
            "The team agreed to lock the 30-day definition in policy."
        ),
        response=(
            "Locking churn as 30-day net-zero MRR cut cohort noise by "
            "5% and removed the recurring redefinition tax."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Cache writer
# ---------------------------------------------------------------------------


@dataclass
class PopulateReport:
    """Outcome of :func:`populate_acme_cache`.

    Mostly for tests + the CLI's pretty-printer; not part of the
    library's behaviour contract.
    """

    cache_path: Path | None
    written: int
    skipped_existing: int
    keys: list[str] = field(default_factory=list)


def populate_acme_cache(
    cache: InferenceCache,
    *,
    cache_path: Path | None = None,
    overwrite: bool = True,
    prompts: tuple[DemoPrompt, ...] = ACME_DEMO_PROMPTS,
) -> PopulateReport:
    """Pre-populate ``cache`` with every Acme demo prompt.

    Idempotent: by default ``overwrite=True`` re-writes every key so
    repeated runs yield identical contents (deterministic by
    construction). Pass ``overwrite=False`` to keep any existing entries
    — useful when cherry-picking new prompts onto a long-lived cache.
    """
    written = 0
    skipped = 0
    keys: list[str] = []
    for prompt in prompts:
        key = prompt.cache_key()
        keys.append(key)
        existing = cache.get(key)
        if existing is not None and not overwrite:
            skipped += 1
            continue
        cache.put(key, prompt.response, model=prompt.model())
        written += 1
    return PopulateReport(
        cache_path=cache_path,
        written=written,
        skipped_existing=skipped,
        keys=keys,
    )


def populate_acme_cache_at_path(
    path: Path,
    *,
    overwrite: bool = True,
    prompts: tuple[DemoPrompt, ...] = ACME_DEMO_PROMPTS,
) -> PopulateReport:
    """Convenience wrapper: open a sqlite cache at ``path`` and populate it.

    The CLI uses this directly; tests can use either this or
    :func:`populate_acme_cache` against an in-memory cache.
    """
    path = Path(path)
    cache = SqliteInferenceCache(path)
    try:
        report = populate_acme_cache(
            cache, cache_path=path, overwrite=overwrite, prompts=prompts,
        )
    finally:
        cache.close()
    return report


__all__ = [
    "ACME_DEMO_PROMPTS",
    "DemoPrompt",
    "PopulateReport",
    "populate_acme_cache",
    "populate_acme_cache_at_path",
]
