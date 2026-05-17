"""Topic extraction — pull a canonical topic from a chat statement.

W5.A2 — companion to ``StatementToOwnerReactivity``. Given a chat message
("our churn is up 8% MoM in Europe"), this module returns a ``Topic``
identifying the canonical resource the message refers to (a KPI, a Source,
a Domain, or a Process), along with a confidence score.

Implementation strategy: deterministic, ledger-driven keyword matching.

  1. Walk the live ledger to assemble the org's ontology — every confirmed
     KPI, every confirmed Source, every Domain that has at least one role
     grant, every proposed Process map. Each of these has a label and a
     domain_id (or maps to one); we collect them into a flat catalog.
  2. Tokenise the message text and match each catalog entry's label
     (case-insensitive, whole-word) against the message.
  3. The strongest match (most specific label) wins; ties break on entry
     kind (kpi > source > process > domain — KPIs are the most actionable
     resource the worm can DM about).
  4. Confidence is a small heuristic: 1.0 for exact full-label match,
     0.8 for compound (e.g. "churn rate" matches "churn"), 0.6 for
     partial matches (substring within a longer word). Below the
     0.6 floor we return ``None`` so the caller can defer to phenomenon-
     gap detection.

Why deterministic and not LLM-driven? Two reasons:

  * **Tests**: a deterministic extractor's behaviour is replay-stable.
    Sister-agent tests (W5.A3 phenomenon-gap detectors) and our own
    StatementToOwner tests can assert the exact topic returned for a
    given input without faking an inference call.
  * **Latency**: the reactivity should land within seconds of the
    statement; an LLM hop adds 1-2s of network at minimum. A keyword
    match is microseconds. The LLM upgrade path is a future
    ``OllamaCloudTopicExtractor`` that the composite can fall back to
    when the deterministic path under-confidence-thresholds.

The output ``Topic`` is intentionally a small dataclass (not a Pydantic
model) so it can flow through the Reactivity context without dragging
ledger imports into the protocol layer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from wormbase_ledger import InMemoryLedger, Ledger

logger = logging.getLogger("wormbase_core.topic_extractor")


TopicKind = Literal["kpi", "source", "domain", "process"]


# Confidence floor below which we return None — let phenomenon-gap detection
# (sister W5.A3) handle gap proposals instead of firing a noisy DM. The
# 0.6 default mirrors the threshold the spec calls out.
DEFAULT_CONFIDENCE_THRESHOLD = 0.6


@dataclass(frozen=True)
class Topic:
    """The canonical resource a chat message refers to.

    ``kind``         — kpi / source / domain / process. Discriminator
                       the caller uses to pick the right downstream
                       lookup (owner, related resources, etc.).
    ``id``           — UUID of the resource in the projection. Stable
                       across replays.
    ``label``        — Human-readable label (e.g. "churn", "stripe");
                       used in the DM body.
    ``confidence``   — [0, 1]. Caller compares against threshold.
    ``domain_id``   — UUID of the domain the resource lives in, when
                       known. ``None`` for resources without a domain
                       (rare; KPIs and sources should always have one).
    """

    kind: TopicKind
    id: UUID
    label: str
    confidence: float
    domain_id: UUID | None = None


@dataclass(frozen=True)
class _CatalogEntry:
    """Internal flat representation of one matchable resource."""

    kind: TopicKind
    id: UUID
    label: str
    domain_id: UUID | None


# Stop-words we strip before matching so generic mentions don't false-match.
_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "of", "in", "on", "at", "to", "for", "with", "and", "or",
    "we", "our", "us", "you", "your", "they", "their", "i", "me",
    "this", "that", "these", "those", "it", "its",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_topic(
    message: str,
    *,
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Topic | None:
    """Return the canonical Topic the message refers to, or ``None``.

    Args:
        message: the raw chat message text.
        ledger: tenant-scoped ledger handle.
        company_id: tenant id (multi-tenant gate).
        threshold: confidence floor. Below this we return ``None`` so
            phenomenon-gap detection takes over.

    The function fetches the ledger once per call. For tight loops
    (e.g. tests that walk many messages) the caller should fold over
    the catalog directly via :func:`_build_catalog`.
    """
    if not message or not message.strip():
        return None

    catalog = await _build_catalog(ledger, company_id)
    if not catalog:
        return None

    return match_against_catalog(message, catalog, threshold=threshold)


def match_against_catalog(
    message: str,
    catalog: list[_CatalogEntry],
    *,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Topic | None:
    """Match a message against a precomputed catalog.

    Pure function (no I/O); useful for testing the matching heuristic
    in isolation. The catalog comes from :func:`_build_catalog` which
    walks the ledger — call that once and reuse for many messages.
    """
    text_lower = message.lower()
    tokens = _tokens(text_lower)
    token_set = set(tokens)

    # Score every catalog entry; pick the highest. Ties: prefer kpi >
    # source > process > domain (most-actionable wins).
    kind_priority: dict[TopicKind, int] = {
        "kpi": 4, "source": 3, "process": 2, "domain": 1,
    }

    best: tuple[float, int, _CatalogEntry] | None = None
    for entry in catalog:
        score = _score(entry.label, text_lower, tokens, token_set)
        if score < threshold:
            continue
        # Higher score wins; on tie, higher priority kind wins.
        candidate_key = (score, kind_priority[entry.kind])
        if best is None or candidate_key > (best[0], best[1]):
            best = (score, kind_priority[entry.kind], entry)

    if best is None:
        return None
    score, _priority, entry = best
    return Topic(
        kind=entry.kind,
        id=entry.id,
        label=entry.label,
        confidence=score,
        domain_id=entry.domain_id,
    )


# ---------------------------------------------------------------------------
# Catalog construction — ledger walk
# ---------------------------------------------------------------------------


async def _build_catalog(
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
) -> list[_CatalogEntry]:
    """Walk the ledger; assemble the matchable-resource catalog.

    Reads:
      * ``emit_kpi_node`` — KPI tree nodes (label = node.label).
      * ``emit_source_proposed`` — sources (label = uri's last path segment
        or ``source_kind``).
      * ``emit_source_confirmed`` — confirmed sources carry domain_id, which
        we attach to the source entry. Last-write wins.
      * ``emit_domain_role_assigned`` — used to enumerate domains in play.
        Labels come from the role's domain_id; we synthesise a label from
        the UUID's first chunk in the rare case no source/kpi names it.
      * ``emit_process_map_proposed`` — process maps (label = process_name).

    Idempotent — calling twice returns the same list.
    """
    rows = await ledger.fetch(company_id)
    sources: dict[str, dict[str, Any]] = {}
    kpis: dict[str, dict[str, Any]] = {}
    processes: dict[str, dict[str, Any]] = {}
    domains: dict[str, dict[str, Any]] = {}

    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}

        if tool in ("emit_source_proposed", "channel_adapter.emit_source_proposed"):
            sid = args.get("source_id")
            if sid:
                label = _infer_source_label(args)
                sources.setdefault(sid, {
                    "id": sid,
                    "label": label,
                    "domain_id": args.get("domain_id"),
                    "suggested_domain": args.get("suggested_domain"),
                })
        elif tool == "emit_source_confirmed":
            sid = args.get("source_id")
            if sid and sid in sources:
                if args.get("domain_id"):
                    sources[sid]["domain_id"] = args["domain_id"]
        elif tool == "emit_kpi_node":
            kid = args.get("id") or args.get("kpi_id")
            if kid:
                kpis[str(kid)] = {
                    "id": str(kid),
                    "label": args.get("label", "") or args.get("name", ""),
                    "domain_id": args.get("domain_id"),
                }
        elif tool == "emit_kpi_proposed":
            # Lake medallion gold layer kpi proposals carry label + domain.
            kid = args.get("kpi_id")
            if kid:
                kpis.setdefault(str(kid), {
                    "id": str(kid),
                    "label": args.get("label", ""),
                    "domain_id": args.get("domain_id"),
                })
        elif tool == "emit_process_map_proposed":
            pid = args.get("process_id")
            if pid:
                processes[str(pid)] = {
                    "id": str(pid),
                    "label": args.get("process_name", "") or "",
                    "domain": args.get("domain"),
                }
        elif tool == "emit_domain_role_assigned":
            did = args.get("domain_id")
            if did:
                domains.setdefault(str(did), {
                    "id": str(did),
                    "label": args.get("domain_name") or "",
                })

    catalog: list[_CatalogEntry] = []
    for k in kpis.values():
        if not k.get("label"):
            continue
        try:
            kid = UUID(str(k["id"]))
        except (ValueError, TypeError):
            continue
        domain_uuid = _maybe_uuid(k.get("domain_id"))
        catalog.append(_CatalogEntry(
            kind="kpi", id=kid, label=str(k["label"]).strip(),
            domain_id=domain_uuid,
        ))
    for s in sources.values():
        if not s.get("label"):
            continue
        try:
            sid = UUID(str(s["id"]))
        except (ValueError, TypeError):
            continue
        domain_uuid = _maybe_uuid(s.get("domain_id"))
        catalog.append(_CatalogEntry(
            kind="source", id=sid, label=str(s["label"]).strip(),
            domain_id=domain_uuid,
        ))
    for p in processes.values():
        if not p.get("label"):
            continue
        try:
            pid = UUID(str(p["id"]))
        except (ValueError, TypeError):
            continue
        catalog.append(_CatalogEntry(
            kind="process", id=pid, label=str(p["label"]).strip(),
            domain_id=None,
        ))
    for d in domains.values():
        if not d.get("label"):
            # Skip domain entries without an explicit label — falling back
            # to "domain-<uuid-prefix>" makes for noisy false matches.
            continue
        try:
            did = UUID(str(d["id"]))
        except (ValueError, TypeError):
            continue
        catalog.append(_CatalogEntry(
            kind="domain", id=did, label=str(d["label"]).strip(),
            domain_id=did,
        ))
    return catalog


def _infer_source_label(args: dict[str, Any]) -> str:
    """Best-effort label for a source proposal.

    Sources don't carry a human-readable name on ``emit_source_proposed``;
    we cherrypick the most informative field available: an explicit
    ``name`` if the caller surfaced one, otherwise the URI's last path
    component, otherwise the ``source_kind`` (e.g. "stripe").
    """
    if isinstance(args.get("name"), str) and args["name"].strip():
        return args["name"].strip()
    uri = args.get("uri") or ""
    if isinstance(uri, str) and "/" in uri:
        last = uri.rstrip("/").rsplit("/", 1)[-1]
        last = last.split(".")[0]  # strip extension
        if last:
            return last
    if args.get("source_kind"):
        return str(args["source_kind"])
    return ""


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    """Lower-case alphanum tokens, stop-words removed."""
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        t = m.group(0)
        if t in _STOPWORDS:
            continue
        out.append(t)
    return out


def _score(
    label: str,
    text_lower: str,
    tokens: list[str],
    token_set: set[str],
) -> float:
    """Compute a confidence score for ``label`` against the message.

    Heuristic:
      * 1.0 — full label appears as a contiguous substring AND every
              label-token is in the message token-set (e.g. "churn" in
              "our churn is up").
      * 0.85 — every label-token is in the message token-set, but they
              don't appear contiguously ("retention churn" matches
              "churn rate is up across retention").
      * 0.7 — at least one label-token is in the message token-set and
              the label is multi-word (rough partial match).
      * 0.0 otherwise.

    Single-token labels need exact whole-word match (no substring). This
    is critical: "are" must not match "are you?" — labels like "MRR"
    or "ARR" would otherwise false-match to common verbs. We enforce by
    using token-set membership, not substring search.
    """
    label_lower = label.strip().lower()
    if not label_lower:
        return 0.0
    label_tokens = _tokens(label_lower)
    if not label_tokens:
        return 0.0

    all_present = all(t in token_set for t in label_tokens)
    full_substring = label_lower in text_lower

    if all_present and full_substring:
        return 1.0
    if all_present:
        return 0.85
    if len(label_tokens) > 1:
        # Multi-word label, partial token hit.
        if any(t in token_set for t in label_tokens):
            return 0.7
    return 0.0


def _maybe_uuid(v: Any) -> UUID | None:
    if v is None:
        return None
    try:
        return UUID(str(v))
    except (ValueError, TypeError):
        return None


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "Topic",
    "TopicKind",
    "extract_topic",
    "match_against_catalog",
]
