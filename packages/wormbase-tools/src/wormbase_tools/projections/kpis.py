"""Pure-Python KPI projection fold.

Mirrors the in-memory portion of the worm-core projection logic that
backs ``/kpis``. Given an ordered list of ledger entries (envelopes
with ``kind``, ``payload`` etc.), :func:`fold_kpis` returns a dict
keyed by ``kpi_id`` with the canonical KPI row shape; then
:func:`compute_kpi_value` extracts a numeric value plus the provenance
trail of contributing entries (so the auditor can show *which* ledger
entries produced *which* KPI value).

These functions are deliberately pure: they consume Python dicts (the
parsed JSONL snapshot rows) and produce plain dicts. No DB, no async,
no I/O, no env vars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class KpiNode:
    """Auditor-facing KPI row.

    Mirrors the shape worm-core's ``_fold_kpis`` produces, narrowed to
    the fields auditor replay needs: id, label/name, source linkage,
    and the latest gold-artifact value found for any of its sources.
    """

    kpi_id: str
    label: str | None = None
    name: str | None = None
    formula: str | None = None
    unit: str | None = None
    owner_position: str | None = None
    source_ids: list[str] = field(default_factory=list)
    proposed_at: str | None = None
    # The canonical numeric value pulled from the most-recent
    # source_golded artifact whose gold_artifact_id is one of the kpi's
    # source_ids. None if no such gold artifact has landed yet.
    value: float | int | str | None = None
    value_source_entry_id: str | None = None
    contributing_entry_ids: list[str] = field(default_factory=list)


@dataclass
class ProjectionState:
    """In-memory fold state — the only mutable structure replay touches."""

    kpis: dict[str, KpiNode] = field(default_factory=dict)
    # gold_artifact_id -> most-recent value payload + originating entry id
    gold_artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)


def _payload_args(entry: dict[str, Any]) -> dict[str, Any]:
    """Pull the ``args`` dict from an execute-shaped envelope.

    The ledger payload schema is ``{"tool": "...", "args": {...},
    "result_ref": "..."}`` for ``execute`` entries (see
    ``wormbase_ledger.entries.ExecutePayload``). Auditor-friendly: be
    defensive about missing keys so a slightly-old snapshot still
    folds.
    """
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return {}
    args = payload.get("args") or {}
    return args if isinstance(args, dict) else {}


def _payload_tool(entry: dict[str, Any]) -> str | None:
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return None
    tool = payload.get("tool")
    return tool if isinstance(tool, str) else None


def _is_execute(entry: dict[str, Any]) -> bool:
    return entry.get("kind") == "execute"


def _normalize_value(raw: Any) -> float | int | str | None:
    """Pick a single canonical scalar from a gold-artifact ``value`` dict.

    Gold artifacts carry a free-form ``value`` payload (per
    ``wormbase_ledger.entries.SourceGoldedPayload``). The dashboard's
    ``/kpis`` view shows whichever scalar the producer chose to expose;
    auditor replay must produce the SAME scalar deterministically.

    Convention (matches the worm-core medallion writer):

    * If ``value`` is already a scalar (number / str), return it as-is.
    * If ``value`` is a dict with a "value" key, return that.
    * If ``value`` is a dict with a single key, return its value.
    * Otherwise return the canonical-JSON string of the dict so the
      auditor still has a deterministic surface to compare against.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float, str)):
        return raw
    if isinstance(raw, dict):
        if "value" in raw and isinstance(raw["value"], (int, float, str)):
            return raw["value"]
        if len(raw) == 1:
            inner = next(iter(raw.values()))
            if isinstance(inner, (int, float, str)):
                return inner
        # Deterministic fallback: canonical JSON.
        import json
        return json.dumps(raw, sort_keys=True, separators=(",", ":"))
    if isinstance(raw, (list, tuple)):
        import json
        return json.dumps(list(raw), sort_keys=True, separators=(",", ":"))
    return str(raw)


def fold_kpis(entries: list[dict[str, Any]]) -> ProjectionState:
    """Fold ledger entries into KPI projection state.

    Iterates in order, applying ``emit_kpi_node``, ``emit_kpi_proposed``,
    and ``emit_source_golded`` rows. The latter populates
    ``gold_artifacts`` keyed by the artifact's UUID so KPIs can resolve
    their numeric value via ``source_ids`` cross-reference.

    Determinism: the input list is consumed in caller-provided order
    (replay always sorts by ``seq`` first, see ``replay.py``). The
    output dicts are deterministic functions of the input.
    """
    state = ProjectionState()

    for entry in entries:
        if not _is_execute(entry):
            continue

        tool = _payload_tool(entry)
        args = _payload_args(entry)
        entry_id = str(entry.get("entry_id") or "")

        if tool == "emit_kpi_node":
            # Generic KPI tree write. The KPI carries a stable string id
            # (e.g. "revenue.q3"). Mirrors
            # wormbase_ledger.projections.builder._apply_execute branch.
            kpi_id = args.get("id")
            if not kpi_id:
                continue
            existing = state.kpis.get(kpi_id) or KpiNode(kpi_id=kpi_id)
            existing.name = args.get("name") or existing.name
            existing.label = args.get("label") or existing.label
            existing.formula = args.get("formula") or existing.formula
            existing.owner_position = (
                args.get("owner_position") or existing.owner_position
            )
            existing.source_ids = list(args.get("source_ids", existing.source_ids))
            existing.contributing_entry_ids.append(entry_id)
            state.kpis[kpi_id] = existing
        elif tool == "emit_kpi_proposed":
            # Bridge from gold aggregate into KPI tree. kpi_id is a UUID
            # string; this is the form the demo's --to flag expects when
            # the audit doc says `--to kpi_q3_revenue`.
            kpi_id = args.get("kpi_id")
            if not kpi_id:
                continue
            kpi_id = str(kpi_id)
            ts = entry.get("ts")
            existing = state.kpis.get(kpi_id) or KpiNode(kpi_id=kpi_id)
            existing.label = args.get("label") or existing.label
            existing.name = existing.name or args.get("label")
            existing.formula = args.get("formula") or existing.formula
            existing.unit = args.get("unit") or existing.unit
            existing.owner_position = (
                args.get("owner_position") or existing.owner_position
            )
            # Convert UUID source ids to strings for downstream lookup.
            src_ids = args.get("source_ids") or []
            if src_ids:
                existing.source_ids = [str(s) for s in src_ids]
            existing.proposed_at = (
                str(args.get("proposed_at"))
                if args.get("proposed_at")
                else (str(ts) if ts else existing.proposed_at)
            )
            existing.contributing_entry_ids.append(entry_id)
            state.kpis[kpi_id] = existing
        elif tool == "emit_source_golded":
            # Each source_golded entry stamps a value for one
            # gold_artifact_id. Retain the latest per artifact id so a
            # subsequent recompute (in real deployments, rare) overrides.
            gold_id = args.get("gold_artifact_id")
            if not gold_id:
                continue
            gold_id = str(gold_id)
            state.gold_artifacts[gold_id] = {
                "value": args.get("value"),
                "artifact_kind": args.get("artifact_kind"),
                "computed_at": str(args.get("computed_at") or entry.get("ts") or ""),
                "source_id": str(args.get("source_id") or ""),
                "entry_id": entry_id,
            }

    # Resolve KPI values from gold artifacts. A KPI's ``source_ids`` is
    # the list of source_id (resource) UUIDs the proposer derived it
    # from; we pick the most-recent gold artifact whose ``source_id``
    # matches any of those.
    for kpi in state.kpis.values():
        latest_value: Any = None
        latest_entry: str | None = None
        latest_ts = ""
        for gold in state.gold_artifacts.values():
            if gold.get("source_id") in kpi.source_ids and gold.get("artifact_kind") == "kpi":
                ts = gold.get("computed_at", "")
                if ts >= latest_ts:
                    latest_value = gold.get("value")
                    latest_entry = gold.get("entry_id")
                    latest_ts = ts
        if latest_value is not None:
            kpi.value = _normalize_value(latest_value)
            kpi.value_source_entry_id = latest_entry
            if latest_entry and latest_entry not in kpi.contributing_entry_ids:
                kpi.contributing_entry_ids.append(latest_entry)

    return state


def compute_kpi_value(
    state: ProjectionState, kpi_id: str
) -> tuple[float | int | str | None, list[str]]:
    """Look up ``kpi_id`` in ``state`` and return its value + provenance.

    Returns ``(value, contributing_entry_ids)``. ``value`` is ``None`` if
    the KPI is not present in the snapshot or has no resolved gold
    artifact value yet.
    """
    kpi = state.kpis.get(kpi_id)
    if kpi is None:
        return None, []
    return kpi.value, list(kpi.contributing_entry_ids)


__all__ = [
    "KpiNode",
    "ProjectionState",
    "compute_kpi_value",
    "fold_kpis",
]
