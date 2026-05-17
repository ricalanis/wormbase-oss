"""Resource aggregation — collect related resources for a Topic.

W5.A2 — companion to ``StatementToOwnerReactivity``. When the worm DMs an
owner about a topic ("Carol, churn is up in Europe"), the DM body pins the
five most useful resources the owner already owns:

  * KPIs in the topic's domain (most recent first)
  * Sources in the topic's domain (active sources)
  * Decisions tagged with the domain (most recent)
  * Process maps tagged with the domain
  * Data products in the domain (most recent)

These are all derived from ledger projections via the ledger handle. The
aggregator returns a ``ResourceBundle`` carrying small summary
dataclasses — one per resource — that the DM template renders directly.

Bundle shape is intentionally narrow: we want the DM to read tightly.
``max_per_kind`` (default 3) caps each list. Excess goes into a separate
"more" count the dashboard can surface.

Why deterministic, not LLM-driven? Same reason as topic_extractor:
replay-stable, fast, and the LLM upgrade path is straight-forward (a
future ``smart_aggregator`` can re-rank by relevance using the inference
router).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from wormbase_ledger import InMemoryLedger, Ledger

from wormbase_core.topic_extractor import Topic

logger = logging.getLogger("wormbase_core.resource_aggregator")


# ---------------------------------------------------------------------------
# Summary dataclasses — narrow, DM-renderable shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KpiSummary:
    """One KPI line in the DM body."""

    kpi_id: UUID
    label: str
    formula: str = ""
    unit: str = ""
    domain_id: UUID | None = None


@dataclass(frozen=True)
class SourceSummary:
    """One Source line in the DM body."""

    source_id: UUID
    label: str
    status: str = "proposed"
    domain_id: UUID | None = None


@dataclass(frozen=True)
class DecisionSummary:
    """One Decision line in the DM body."""

    decision_id: UUID
    decision_text: str
    decision_at: str = ""
    channel_id: str = ""


@dataclass(frozen=True)
class ProcessSummary:
    """One Process map line in the DM body."""

    process_id: UUID
    process_name: str
    step_count: int = 0
    domain: str = ""


@dataclass(frozen=True)
class DataProductSummary:
    """One Data Product line in the DM body."""

    data_product_id: UUID
    name: str
    kind: str = "report"
    domain_id: UUID | None = None


@dataclass(frozen=True)
class ResourceBundle:
    """The pinned-resources bundle shown in the resource-conversation DM."""

    kpis: list[KpiSummary] = field(default_factory=list)
    sources: list[SourceSummary] = field(default_factory=list)
    decisions: list[DecisionSummary] = field(default_factory=list)
    processes: list[ProcessSummary] = field(default_factory=list)
    data_products: list[DataProductSummary] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.kpis or self.sources or self.decisions
            or self.processes or self.data_products
        )

    def to_payload(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the ledger payload."""
        return {
            "kpis": [
                {
                    "kpi_id": str(k.kpi_id),
                    "label": k.label,
                    "formula": k.formula,
                    "unit": k.unit,
                    "domain_id": str(k.domain_id) if k.domain_id else None,
                }
                for k in self.kpis
            ],
            "sources": [
                {
                    "source_id": str(s.source_id),
                    "label": s.label,
                    "status": s.status,
                    "domain_id": str(s.domain_id) if s.domain_id else None,
                }
                for s in self.sources
            ],
            "decisions": [
                {
                    "decision_id": str(d.decision_id),
                    "decision_text": d.decision_text,
                    "decision_at": d.decision_at,
                    "channel_id": d.channel_id,
                }
                for d in self.decisions
            ],
            "processes": [
                {
                    "process_id": str(p.process_id),
                    "process_name": p.process_name,
                    "step_count": p.step_count,
                    "domain": p.domain,
                }
                for p in self.processes
            ],
            "data_products": [
                {
                    "data_product_id": str(d.data_product_id),
                    "name": d.name,
                    "kind": d.kind,
                    "domain_id": str(d.domain_id) if d.domain_id else None,
                }
                for d in self.data_products
            ],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def gather_related_resources(
    topic: Topic,
    *,
    ledger: Ledger | InMemoryLedger,
    company_id: UUID,
    max_per_kind: int = 3,
) -> ResourceBundle:
    """Build the pinned-resource bundle for a Topic.

    Args:
        topic: the topic being discussed.
        ledger: tenant-scoped ledger handle.
        company_id: tenant id.
        max_per_kind: cap per resource list (default 3).

    The aggregator filters resources by the topic's ``domain_id`` when
    present. For topics without a domain (rare), we fall back to the
    most recent resources of each kind across the whole tenant —
    better than an empty bundle.

    Time-ordering: rows arrive sorted by ledger seq (asc); we reverse to
    surface the most-recent first, then take the first ``max_per_kind``.
    """
    rows = await ledger.fetch(company_id)
    rows.sort(key=lambda r: int(r.get("seq", 0)))

    target_domain = str(topic.domain_id) if topic.domain_id else None

    kpis = _extract_kpis(rows, target_domain, max_per_kind)
    sources = _extract_sources(rows, target_domain, max_per_kind)
    decisions = _extract_decisions(rows, target_domain, max_per_kind)
    processes = _extract_processes(rows, target_domain, max_per_kind)
    data_products = _extract_data_products(rows, target_domain, max_per_kind)

    return ResourceBundle(
        kpis=kpis,
        sources=sources,
        decisions=decisions,
        processes=processes,
        data_products=data_products,
    )


# ---------------------------------------------------------------------------
# Per-kind extractors. Each one walks ``rows`` once and returns the latest
# ``max_per_kind`` matching the domain filter.
# ---------------------------------------------------------------------------


def _extract_kpis(
    rows: list[dict[str, Any]],
    target_domain: str | None,
    cap: int,
) -> list[KpiSummary]:
    """Pull the latest KPIs in the target domain (or any if no domain)."""
    found: dict[str, KpiSummary] = {}
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool")
        if tool not in ("emit_kpi_node", "emit_kpi_proposed"):
            continue
        args = payload.get("args") or {}
        kid = args.get("id") or args.get("kpi_id")
        if not kid:
            continue
        domain_id_raw = args.get("domain_id")
        if (
            target_domain is not None
            and domain_id_raw is not None
            and str(domain_id_raw) != target_domain
        ):
            continue
        try:
            kpi_uuid = UUID(str(kid))
        except (ValueError, TypeError):
            continue
        domain_uuid = _maybe_uuid(domain_id_raw)
        # Last write wins.
        found[str(kid)] = KpiSummary(
            kpi_id=kpi_uuid,
            label=str(args.get("label") or args.get("name") or "(unnamed)"),
            formula=str(args.get("formula") or ""),
            unit=str(args.get("unit") or ""),
            domain_id=domain_uuid,
        )
    # Reverse insertion order = most-recent-first; cap at ``cap``.
    items = list(found.values())
    items.reverse()
    return items[:cap]


def _extract_sources(
    rows: list[dict[str, Any]],
    target_domain: str | None,
    cap: int,
) -> list[SourceSummary]:
    """Pull the latest active sources in the target domain."""
    sources: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        tool = payload.get("tool")
        args = payload.get("args") or {}
        sid = args.get("source_id")
        if not sid:
            continue
        if tool == "emit_source_proposed":
            sources.setdefault(sid, {
                "source_id": sid,
                "label": _infer_source_label(args),
                "status": "proposed",
                "domain_id": args.get("domain_id"),
            })
        elif tool == "emit_source_confirmed":
            if sid in sources:
                if args.get("domain_id"):
                    sources[sid]["domain_id"] = args["domain_id"]
                sources[sid]["status"] = "confirmed"
        elif tool == "emit_source_connected":
            if sid in sources:
                sources[sid]["status"] = "connected"
        elif tool == "emit_source_profiled":
            if sid in sources:
                sources[sid]["status"] = "profiled"

    summaries: list[SourceSummary] = []
    for sid, s in sources.items():
        if (
            target_domain is not None
            and s.get("domain_id") is not None
            and str(s["domain_id"]) != target_domain
        ):
            continue
        if (
            target_domain is not None
            and s.get("domain_id") is None
        ):
            # Source not yet confirmed to a domain — exclude when
            # filtering by domain.
            continue
        try:
            sid_uuid = UUID(str(sid))
        except (ValueError, TypeError):
            continue
        summaries.append(SourceSummary(
            source_id=sid_uuid,
            label=str(s.get("label") or "(unnamed source)"),
            status=str(s.get("status") or "proposed"),
            domain_id=_maybe_uuid(s.get("domain_id")),
        ))
    summaries.reverse()
    return summaries[:cap]


def _extract_decisions(
    rows: list[dict[str, Any]],
    target_domain: str | None,
    cap: int,
) -> list[DecisionSummary]:
    """Pull the latest decisions in the target domain (best-effort).

    Decisions don't carry a domain id directly. We approximate by
    matching channel_id substrings against the domain — but for v1 we
    return all recent decisions when a target_domain is set; the DM
    template surfaces three of the most-recent regardless. A future
    upgrade can index decisions by domain via a projection.
    """
    found: dict[str, DecisionSummary] = {}
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_decision_recorded":
            continue
        args = payload.get("args") or {}
        did = args.get("decision_id")
        if not did:
            continue
        try:
            d_uuid = UUID(str(did))
        except (ValueError, TypeError):
            continue
        found[str(did)] = DecisionSummary(
            decision_id=d_uuid,
            decision_text=str(args.get("decision_text") or "(no text)"),
            decision_at=str(args.get("decision_at") or ""),
            channel_id=str(args.get("channel_id") or ""),
        )
    items = list(found.values())
    items.reverse()
    return items[:cap]


def _extract_processes(
    rows: list[dict[str, Any]],
    target_domain: str | None,
    cap: int,
) -> list[ProcessSummary]:
    """Pull the latest process maps tagged with the target domain.

    Process maps carry a ``domain`` string field (free-form, not UUID).
    When ``target_domain`` is a UUID the match would be vacuous; we
    therefore match on the topic's domain string only when it's
    available via the topic — at this layer we return all recent
    processes and let the caller filter further if needed.
    """
    found: dict[str, ProcessSummary] = {}
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_process_map_proposed":
            continue
        args = payload.get("args") or {}
        pid = args.get("process_id")
        if not pid:
            continue
        try:
            p_uuid = UUID(str(pid))
        except (ValueError, TypeError):
            continue
        steps = args.get("steps") or []
        found[str(pid)] = ProcessSummary(
            process_id=p_uuid,
            process_name=str(args.get("process_name") or "(unnamed process)"),
            step_count=len(steps) if isinstance(steps, list) else 0,
            domain=str(args.get("domain") or ""),
        )
    items = list(found.values())
    items.reverse()
    return items[:cap]


def _extract_data_products(
    rows: list[dict[str, Any]],
    target_domain: str | None,
    cap: int,
) -> list[DataProductSummary]:
    """Pull the latest data products in the target domain."""
    found: dict[str, DataProductSummary] = {}
    for r in rows:
        if r.get("kind") != "execute":
            continue
        payload = r.get("payload") or {}
        if payload.get("tool") != "emit_data_product_proposed":
            continue
        args = payload.get("args") or {}
        dpid = args.get("data_product_id")
        if not dpid:
            continue
        domain_id_raw = args.get("domain_id")
        if (
            target_domain is not None
            and domain_id_raw is not None
            and str(domain_id_raw) != target_domain
        ):
            continue
        if (
            target_domain is not None
            and domain_id_raw is None
        ):
            continue
        try:
            dp_uuid = UUID(str(dpid))
        except (ValueError, TypeError):
            continue
        found[str(dpid)] = DataProductSummary(
            data_product_id=dp_uuid,
            name=str(args.get("name") or "(unnamed)"),
            kind=str(args.get("kind") or "report"),
            domain_id=_maybe_uuid(domain_id_raw),
        )
    items = list(found.values())
    items.reverse()
    return items[:cap]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_source_label(args: dict[str, Any]) -> str:
    """Best-effort source label, matching topic_extractor's heuristic."""
    if isinstance(args.get("name"), str) and args["name"].strip():
        return args["name"].strip()
    uri = args.get("uri") or ""
    if isinstance(uri, str) and "/" in uri:
        last = uri.rstrip("/").rsplit("/", 1)[-1]
        last = last.split(".")[0]
        if last:
            return last
    if args.get("source_kind"):
        return str(args["source_kind"])
    return "(unnamed source)"


def _maybe_uuid(v: Any) -> UUID | None:
    if v is None:
        return None
    try:
        return UUID(str(v))
    except (ValueError, TypeError):
        return None


__all__ = [
    "DataProductSummary",
    "DecisionSummary",
    "KpiSummary",
    "ProcessSummary",
    "ResourceBundle",
    "SourceSummary",
    "gather_related_resources",
]
