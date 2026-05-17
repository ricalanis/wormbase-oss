"""Advanced predicates for the W5.A3 phenomenon-gap reactivities.

The simple predicates in ``predicates.py`` (``EntryKind``, ``HasTopic``,
``HasOwner``, ``SpeakerNotOwner``) are pure-by-design — they only inspect
the entry's ``payload.args``. Phenomenon-gap detection needs richer
machinery:

  * ``MentionsMetricNotInKpiTree`` — extract metric-shaped phrases from
    chat text, then probe the KPI tree projection to confirm absence.
  * ``MentionsDomainNotInOntology`` — same shape but against the org's
    domain ontology.
  * ``DescribesProcessNotInLake`` — same shape against process_map
    projections.
  * ``DescribesRecurringPattern`` — pure linguistic detection of "every
    time / whenever / every Friday" patterns, no projection probe needed.

All four are async by design. The metric / domain / process detectors will
hit the inference router (Gemma) for marginal cases in a future wave; in
v1 we ship a regex-and-vocab core that's deterministic and cheap.

Why not put these in ``predicates.py``? Because they reach across packages
(``wormbase_core.topic_extractor``, ledger projections), and ``predicates.py``
is intentionally pure to keep the dependency graph clean. ``predicates_advanced.py``
is the explicit "predicates with side-effecting probes" tier — same Protocol,
different intent.

Defensive imports: the topic_extractor module is shipped by the parallel
W5.A2 stream; we lazy-import it inside ``match`` so a partial deployment
(this module landed before A2's) degrades gracefully — the predicate
returns False instead of raising, the Reactivity simply doesn't fire,
and the runner moves on. This is the prescribed behaviour from the task
spec.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from wormbase_reactivities.predicates import _PredicateBase
from wormbase_reactivities.protocol import ReactivityContext

logger = logging.getLogger("wormbase_reactivities.predicates_advanced")


# ---------------------------------------------------------------------------
# Metric vocabulary — the cheap path before LLM
#
# These are common SaaS / fintech / marketplace metrics. Rather than
# compile a global metric ontology, we ship a small high-precision seed
# vocabulary; the topic_extractor (W5.A2) handles fuzzy / domain-specific
# cases. False-positive rate matters more than recall for phenomenon-gap
# detection, so this list is intentionally short.
# ---------------------------------------------------------------------------


_METRIC_VOCAB: frozenset[str] = frozenset(
    {
        "arr",
        "mrr",
        "nps",
        "csat",
        "churn",
        "retention",
        "ltv",
        "cac",
        "dau",
        "mau",
        "wau",
        "gmv",
        "tpv",
        "aov",
        "conversion",
        "conversion rate",
        "active users",
        "revenue",
        "net revenue",
        "gross revenue",
        "growth rate",
        "engagement",
        "uptime",
    }
)

# Confidence floor below which the detector won't fire. Tuned to keep
# false-positive rate low; tunable per-tenant in a future wave.
DEFAULT_CONFIDENCE_THRESHOLD = 0.6


def _entry_text(entry: dict[str, Any]) -> str:
    """Pull the chat text out of an entry's args, defensively."""
    payload = entry.get("payload") or {}
    args = payload.get("args") or {}
    return str(args.get("text") or "")


def _normalize(text: str) -> str:
    return text.lower().strip()


def _extract_metric_candidates(text: str) -> list[tuple[str, float]]:
    """Cheap regex / vocabulary scan. Returns (label, confidence) pairs.

    Confidence rises with explicit "track / measure / monitor" cues
    around the metric label; bare mentions get a baseline 0.6 — just
    enough to clear the default threshold so unambiguous "ARR" still
    fires, while obviously-prose mentions (e.g. "the ARR sound system")
    don't. Cue words push to 0.9.
    """
    out: list[tuple[str, float]] = []
    norm = _normalize(text)
    for label in _METRIC_VOCAB:
        # Word-boundary match keeps "arr" from matching "carrier".
        pattern = rf"\b{re.escape(label)}\b"
        if re.search(pattern, norm):
            cue_words = (
                "track",
                "measure",
                "monitor",
                "report on",
                "kpi",
                "we should",
                "we need",
                "metric",
            )
            confidence = 0.9 if any(c in norm for c in cue_words) else 0.6
            out.append((label, confidence))
    return out


# ---------------------------------------------------------------------------
# Lazy access to W5.A2's topic_extractor
# ---------------------------------------------------------------------------


async def _try_extract_topic(
    text: str, context: ReactivityContext,
) -> dict[str, Any] | None:
    """Best-effort call into W5.A2's ``extract_topic`` if it exists.

    Returns a dict of ``{label, kind, confidence}`` (the W5.A2 contract)
    or None if topic extraction is unavailable. Wrapping in this helper
    means partial deployments degrade gracefully — the regex-only path
    in this module's detectors handles the load when A2's extractor
    can't be reached.

    The W5.A2 ``extract_topic`` returns a ``Topic`` dataclass; we
    normalise to a plain dict so the predicate doesn't take a type-level
    dep on worm-core's internals. Returns None on any exception so a
    misbehaving topic-extractor can't wedge the reactivity loop.
    """
    try:
        from wormbase_core.topic_extractor import extract_topic  # type: ignore
    except Exception:  # noqa: BLE001 - module may not exist yet
        return None
    try:
        result = await extract_topic(  # type: ignore[no-untyped-call]
            text,
            ledger=context.ledger,
            company_id=context.company_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("topic_extractor.extract_topic raised: %s", exc)
        return None
    if not result:
        return None
    if isinstance(result, dict):
        return result
    # Topic dataclass — pull out the stable fields by attribute access.
    out: dict[str, Any] = {}
    for attr in ("label", "kind", "confidence"):
        if hasattr(result, attr):
            out[attr] = getattr(result, attr)
    return out or None


# ---------------------------------------------------------------------------
# Projection probes — query ledger projections through the registry's ledger
#
# We resist the temptation to import the SQLAlchemy projection tables
# directly. The projections package is owned by ``wormbase_ledger`` and
# may evolve; instead we walk ``ledger.fetch(company_id)`` and filter on
# the entry tool name. This is O(N) in entries but the InMemoryLedger
# common case is tiny (test fixtures), and the production path uses a
# DB-backed cache (TODO: extract a projection-read helper in W5.A6).
# ---------------------------------------------------------------------------


async def _existing_kpi_labels(
    ledger: Any, company_id: Any,
) -> set[str]:
    """Return lowercased KPI labels currently in the org's KPI tree."""
    try:
        rows = await ledger.fetch(company_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ledger.fetch failed in KPI probe: %s", exc)
        return set()
    out: set[str] = set()
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool") or ""
        if not (
            tool.endswith(".emit_kpi_proposed")
            or tool == "emit_kpi_proposed"
        ):
            continue
        args = payload.get("args") or {}
        label = args.get("label")
        if label:
            out.add(_normalize(str(label)))
    return out


async def _existing_domains(
    ledger: Any, company_id: Any,
) -> set[str]:
    """Return lowercased domain identifiers currently in the org's ontology.

    Domains are surfaced as ``args.domain`` strings on every executed
    entry that carries one. Future schema for ``domain_proposed`` lives
    in a follow-up wave; today we treat the de facto set drawn from
    args.domain as the ontology — same logic the dashboard uses.
    """
    try:
        rows = await ledger.fetch(company_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ledger.fetch failed in domain probe: %s", exc)
        return set()
    out: set[str] = set()
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        args = payload.get("args") or {}
        d = args.get("domain")
        if d:
            out.add(_normalize(str(d)))
    return out


async def _existing_process_names(
    ledger: Any, company_id: Any,
) -> set[str]:
    """Return lowercased process names currently in the lake."""
    try:
        rows = await ledger.fetch(company_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ledger.fetch failed in process probe: %s", exc)
        return set()
    out: set[str] = set()
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool") or ""
        if not (
            tool.endswith(".emit_process_map_proposed")
            or tool == "emit_process_map_proposed"
        ):
            continue
        args = payload.get("args") or {}
        name = args.get("process_name")
        if name:
            out.add(_normalize(str(name)))
    return out


async def _existing_reactivity_ids(
    ledger: Any, company_id: Any,
) -> set[str]:
    """Return reactivity ids currently registered.

    Pulls from ``emit_reactivity_proposed`` / ``emit_reactivity_confirmed``
    entries; an admin's confirmed Reactivity counts even if it was
    proposed long ago.
    """
    try:
        rows = await ledger.fetch(company_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ledger.fetch failed in reactivity probe: %s", exc)
        return set()
    out: set[str] = set()
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool") or ""
        if not (
            tool.endswith(".emit_reactivity_proposed")
            or tool == "emit_reactivity_proposed"
            or tool.endswith(".emit_reactivity_confirmed")
            or tool == "emit_reactivity_confirmed"
        ):
            continue
        args = payload.get("args") or {}
        rid = args.get("reactivity_id")
        if rid:
            out.add(str(rid))
    return out


# ---------------------------------------------------------------------------
# MentionsMetricNotInKpiTree
# ---------------------------------------------------------------------------


@dataclass
class MentionsMetricNotInKpiTree(_PredicateBase):
    """Match chat text that references a metric not present in the KPI tree.

    Stashes detection details into ``context.extras`` under
    ``"phenomenon_gap_kpi"`` so the Reactivity's ``fire`` can pick them
    up without re-extracting:

        {"label": "nps", "confidence": 0.9, "novelty_key": "kpi:nps"}

    The W5.A2 ``extract_topic`` is consulted first; on miss we fall back
    to the cheap regex pass over ``_METRIC_VOCAB``. Either way we then
    confirm the label is NOT already in the org's KPI tree.
    """

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        text = _entry_text(entry)
        if not text:
            return False

        # Try W5.A2's structured extractor first; fall back to vocab.
        topic = await _try_extract_topic(text, context)
        candidates: list[tuple[str, float]]
        if topic and str(topic.get("kind", "")).lower() == "kpi":
            label = str(topic.get("label", "")).strip()
            confidence = float(topic.get("confidence", 0.0) or 0.0)
            candidates = [(label.lower(), confidence)] if label else []
        else:
            candidates = _extract_metric_candidates(text)

        if not candidates:
            return False

        # Pick the highest-confidence candidate above threshold.
        candidates.sort(key=lambda x: -x[1])
        label, confidence = candidates[0]
        if confidence < self.confidence_threshold:
            return False

        existing = await _existing_kpi_labels(
            context.ledger, context.company_id,
        )
        if label in existing:
            return False

        # Stash for fire() — keep the keys namespaced so concurrent
        # gap detectors don't trample each other.
        context.extras["phenomenon_gap_kpi"] = {
            "label": label,
            "confidence": confidence,
            "novelty_key": f"kpi:{label}",
        }
        # Set the registry-level novelty_key so NotRecentlyFired can
        # look up "did we already detect this gap recently".
        context.extras["novelty_key"] = f"kpi:{label}"
        return True


# ---------------------------------------------------------------------------
# MentionsDomainNotInOntology
# ---------------------------------------------------------------------------


# A small seed vocabulary of domain-shaped phrases. Same precision-over-recall
# rationale as ``_METRIC_VOCAB``.
_DOMAIN_VOCAB: frozenset[str] = frozenset(
    {
        "compliance",
        "marketing",
        "sales",
        "product",
        "engineering",
        "finance",
        "support",
        "legal",
        "people",
        "ops",
        "operations",
        "security",
        "growth",
        "customer success",
        "data",
    }
)

# Phrases that elevate confidence: "the X team", "X function", "X department".
_DOMAIN_CUE_REGEX = re.compile(
    r"\b(?:the\s+)?(?P<label>[a-z][a-z ]{2,40}?)\s+"
    r"(?:team|department|org|function|group|unit)\b",
    re.IGNORECASE,
)


def _extract_domain_candidates(text: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    norm = _normalize(text)
    # Vocabulary pass.
    for label in _DOMAIN_VOCAB:
        pattern = rf"\b{re.escape(label)}\b"
        if re.search(pattern, norm):
            out.append((label, 0.65))
    # Cue-phrase pass — "the compliance team" => higher confidence.
    for m in _DOMAIN_CUE_REGEX.finditer(text):
        label = _normalize(m.group("label"))
        # Strip leading articles / conjunctions captured by the loose group.
        for prefix in ("the ", "our ", "a ", "an "):
            if label.startswith(prefix):
                label = label[len(prefix):]
        if label and len(label) >= 3:
            out.append((label, 0.85))
    return out


@dataclass
class MentionsDomainNotInOntology(_PredicateBase):
    """Match chat referencing a domain (e.g. "compliance team") not in ontology."""

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        text = _entry_text(entry)
        if not text:
            return False

        topic = await _try_extract_topic(text, context)
        candidates: list[tuple[str, float]]
        if topic and str(topic.get("kind", "")).lower() == "domain":
            label = str(topic.get("label", "")).strip()
            confidence = float(topic.get("confidence", 0.0) or 0.0)
            candidates = [(label.lower(), confidence)] if label else []
        else:
            candidates = _extract_domain_candidates(text)

        if not candidates:
            return False
        candidates.sort(key=lambda x: -x[1])
        label, confidence = candidates[0]
        if confidence < self.confidence_threshold:
            return False

        existing = await _existing_domains(
            context.ledger, context.company_id,
        )
        if label in existing:
            return False

        context.extras["phenomenon_gap_domain"] = {
            "label": label,
            "confidence": confidence,
            "novelty_key": f"domain:{label}",
        }
        context.extras["novelty_key"] = f"domain:{label}"
        return True


# ---------------------------------------------------------------------------
# DescribesProcessNotInLake
# ---------------------------------------------------------------------------


# Process descriptions tend to share a templated shape: a cadence cue +
# an actor-action chain. The regex below captures the cadence; the trailing
# noun phrase (after stripping) becomes the proposed process name.
_PROCESS_CADENCE_REGEX = re.compile(
    r"\b(?:every|each)\s+"
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"day|week|month|quarter|year|sprint|cycle|morning|afternoon)\b",
    re.IGNORECASE,
)
_PROCESS_VERB_REGEX = re.compile(
    r"\b(?:we|i|the team)\s+"
    r"(?P<verb>run|kick off|start|do|hold|conduct|review|reconcile|"
    r"deploy|publish|sync|stand up|close)"
    r"\b\s+(?P<noun>.+?)(?:\.|,|;|$)",
    re.IGNORECASE,
)


def _extract_process_candidate(text: str) -> tuple[str, float] | None:
    """Best-effort extraction of a (process_name, confidence) candidate."""
    norm = text.strip()
    has_cadence = bool(_PROCESS_CADENCE_REGEX.search(norm))
    if not has_cadence:
        return None
    m = _PROCESS_VERB_REGEX.search(norm)
    if not m:
        # Cadence without a clear verb → still a process hint, but
        # weak; surface a stub that the admin must edit.
        return ("recurring activity", 0.65)
    noun_phrase = m.group("noun").strip().rstrip(".")
    # Trim filler ("a", "the") from the noun phrase head.
    for prefix in ("a ", "an ", "the ", "our "):
        if noun_phrase.lower().startswith(prefix):
            noun_phrase = noun_phrase[len(prefix):]
    if not noun_phrase:
        return None
    # Higher confidence when both cadence + verb fired.
    return (noun_phrase, 0.85)


@dataclass
class DescribesProcessNotInLake(_PredicateBase):
    """Match chat describing a process not yet captured in process_map."""

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        text = _entry_text(entry)
        if not text:
            return False

        topic = await _try_extract_topic(text, context)
        candidate: tuple[str, float] | None
        if topic and str(topic.get("kind", "")).lower() == "process":
            label = str(topic.get("label", "")).strip()
            confidence = float(topic.get("confidence", 0.0) or 0.0)
            candidate = (label, confidence) if label else None
        else:
            candidate = _extract_process_candidate(text)

        if candidate is None:
            return False
        label, confidence = candidate
        if confidence < self.confidence_threshold:
            return False

        existing = await _existing_process_names(
            context.ledger, context.company_id,
        )
        if _normalize(label) in existing:
            return False

        context.extras["phenomenon_gap_process"] = {
            "label": label,
            "confidence": confidence,
            "evidence_text": text,
            "novelty_key": f"process:{_normalize(label)}",
        }
        context.extras["novelty_key"] = f"process:{_normalize(label)}"
        return True


# ---------------------------------------------------------------------------
# DescribesRecurringPattern (the meta-detector)
# ---------------------------------------------------------------------------


# The meta-case: linguistic templates where the speaker describes an
# automation-shaped rule. Two regex families:
#
#   1. Conditional: "every time / whenever X, do Y" — high confidence,
#      explicit reactive intent.
#   2. Cadence-action: "every Friday we run X" — overlaps with process
#      detection but distinguished by a follow-up reactive verb
#      (notify, alert, ping, remind, send, dm).
#
# Hybrid approach: regex captures the high-confidence cases; an LLM
# spike (Gemma) is the fallback for ambiguous prose. The LLM hook is
# intentionally not wired in v1 — false-positive rate is the priority,
# and the regex captures most templated phrasings. Document the trade-off
# at module level so future authors know where to extend.

_RECURRING_TRIGGER_REGEX = re.compile(
    r"\b(?:every\s*time|whenever|each\s*time|any\s*time|whenever)\b\s+"
    r"(?P<trigger>.+?)\s*,\s*"
    r"(?P<action>.+?)(?:\.|;|$)",
    re.IGNORECASE,
)

_REACTIVE_VERB_REGEX = re.compile(
    r"\b(?:notify|alert|ping|remind|dm|message|email|post|share)\b",
    re.IGNORECASE,
)

_RECURRING_CADENCE_ACTION_REGEX = re.compile(
    r"\b(?:every|each)\s+"
    r"(?P<cadence>monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"day|week|month|quarter|sprint)\b\s+"
    r"(?:we|i|the\s+team)\s+"
    r"(?P<action>.+?)(?:\.|;|$)",
    re.IGNORECASE,
)


def _extract_recurring_pattern(
    text: str,
) -> tuple[dict[str, Any], float] | None:
    """Best-effort recurring-pattern extraction.

    Returns a ``(spec, confidence)`` pair where ``spec`` is the suggested
    Reactivity skeleton:

        {
            "predicate_description": "every Friday",
            "action_description": "run the data-quality review",
            "natural_language": "every Friday we run the data-quality review",
        }

    Confidence is high (0.85) for explicit "whenever X, Y" matches and
    moderate (0.70) for cadence+reactive-verb matches. Returns None if
    no template fires.
    """
    norm = text.strip()

    # 1. Conditional template.
    m = _RECURRING_TRIGGER_REGEX.search(norm)
    if m:
        trigger = m.group("trigger").strip().rstrip(",")
        action = m.group("action").strip().rstrip(".")
        if trigger and action:
            return (
                {
                    "predicate_description": trigger,
                    "action_description": action,
                    "natural_language": (
                        f"whenever {trigger}, {action}"
                    ),
                },
                0.9,
            )

    # 2. Cadence + reactive verb.
    m = _RECURRING_CADENCE_ACTION_REGEX.search(norm)
    if m:
        cadence = m.group("cadence").strip().lower()
        action = m.group("action").strip().rstrip(".")
        if action:
            confidence = 0.7
            if _REACTIVE_VERB_REGEX.search(action):
                confidence = 0.85
            return (
                {
                    "predicate_description": f"every {cadence}",
                    "action_description": action,
                    "natural_language": (
                        f"every {cadence} we {action}"
                    ),
                },
                confidence,
            )

    return None


@dataclass
class DescribesRecurringPattern(_PredicateBase):
    """Match chat describing an automation-shaped recurring rule.

    The meta-detector for "the worm builds the rules it runs on". Hybrid
    approach: a high-precision regex pass first (cheap, deterministic),
    with an LLM-backed fallback reserved for a future wave. We keep the
    confidence threshold at the default 0.6 and rely on regex specificity
    to keep noise down. The cost of a false-positive Reactivity proposal
    is bounded: it sits in ``proposed`` state forever unless an admin
    confirms.
    """

    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD

    async def match(
        self, entry: dict[str, Any], context: ReactivityContext,
    ) -> bool:
        text = _entry_text(entry)
        if not text:
            return False

        result = _extract_recurring_pattern(text)
        if result is None:
            return False
        spec, confidence = result
        if confidence < self.confidence_threshold:
            return False

        # Reactivity ids are slugged from natural language; keep a stable
        # novelty key so re-mentions of the same rule don't fire repeatedly.
        slug = re.sub(
            r"[^a-z0-9]+", "-",
            _normalize(spec["natural_language"]),
        ).strip("-")[:64]

        # Confirm not already proposed/confirmed.
        existing = await _existing_reactivity_ids(
            context.ledger, context.company_id,
        )
        if slug in existing:
            return False

        context.extras["phenomenon_gap_reactivity"] = {
            "label": spec["natural_language"],
            "spec": spec,
            "confidence": confidence,
            "slug": slug,
            "novelty_key": f"reactivity:{slug}",
        }
        context.extras["novelty_key"] = f"reactivity:{slug}"
        return True


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DescribesProcessNotInLake",
    "DescribesRecurringPattern",
    "MentionsDomainNotInOntology",
    "MentionsMetricNotInKpiTree",
]
