"""L4 Sub-wave C — concrete LedgerLineageEdgeReader for schema-impact discovery.

Sub-wave B introduced the :class:`LineageEdgeReader` Protocol on the
schema-impact subpackage in ``wormbase-agent-gateway``. The Protocol is
the **first cross-axis read** in the lake-side compounding stack — L4
strategies query L3's confirmed lineage edges to propagate downstream
impacts when an upstream source schema changes.

This module ships the production impl that
``agent_gateway_construction.compose_schema_impact_reactivity_if_enabled``
threads into BOTH the :class:`LineageEdgeImpactStrategy` and the
:class:`TypeCoercionImpactStrategy`. A single shared instance is
constructed once per boot wire (per Sub-wave B handoff concern #5) so
both strategies see the same cross-axis read surface.

Implementation approach: ledger-walk + projection-fold replay. We walk
the tenant-scoped ledger for ``lineage_edge_proposed`` /
``lineage_edge_confirmed`` / ``lineage_edge_rejected`` execute entries
and reconstruct the projection_lineage_edges row state in-memory. This
mirrors the rest of the lake-side readers (LedgerCatalogReader,
LedgerDbtManifestReader, LedgerDbtTestReader, LedgerDecisionReader,
LedgerProcessMapReader) which all walk the ledger via
``ledger.fetch(company_id)`` rather than reading Postgres projection
tables directly.

The rationale for ledger-walk over SQL projection-read:

* Works against InMemoryLedger (tests) and DB-backed Ledger (prod)
  with the same code path. Avoids a SQL-only impl that breaks the
  in-memory-ledger test pattern used across worm-core.
* Replay-stable by construction — the ledger IS the source of truth;
  the projection is a materialized view. Walking the ledger yields the
  same result as querying the projection (modulo replay drift, which
  the projection runner protects against).
* Tenant scope rides on ``company_id`` per call — same surface as the
  rest of the lake-side readers.

When the ledger materialises the projection_lineage_edges table via
SQL (Postgres), a future optimization can swap this impl for a direct
SQL reader behind the same Protocol surface — no caller changes.

Filter contract per Sub-wave B Protocol:

* state="confirmed" only (we only propagate impacts via L3-confirmed
  edges; proposed-but-not-confirmed edges are too noisy).
* src_table_id starts with ``"<source_id>."`` (edges sourced from the
  changing source).
* src_column matches exactly (column-grain propagation only; edges
  with ``src_column=None`` are NOT returned — they are whole-table
  dbt-manifest refs that L4 doesn't reason over today).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger("wormbase_core.schema_impact_lineage_reader")

__all__ = [
    "LedgerLineageEdgeReader",
]


class _LedgerFetcher(Protocol):
    """Minimal surface this module needs from a Ledger-like object.

    Matches the shape in :class:`wormbase_core.lineage_catalog_reader._LedgerFetcher`
    — a fetch-by-company_id async call returning ledger row dicts.
    """

    async def fetch(
        self, company_id: UUID, until_ts: Any | None = ...,
    ) -> list[dict[str, Any]]: ...  # pragma: no cover


def _execute_args(entry: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``args`` dict from an execute entry's payload."""
    if entry.get("kind") != "execute":
        return {}
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return {}
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        return {}
    return args


def _is_emit_tool(entry: dict[str, Any], tool: str) -> bool:
    """True iff this is an execute entry whose payload.tool matches ``tool``."""
    if entry.get("kind") != "execute":
        return False
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        return False
    return payload.get("tool") == tool


@dataclass
class LedgerLineageEdgeReader:
    """Reads L3's confirmed lineage edges via ledger walk + fold replay.

    Implements the :class:`wormbase_agent_gateway.schema_impact.LineageEdgeReader`
    Protocol — the first cross-axis read in the lake stack. L4 strategies
    (LineageEdgeImpactStrategy, TypeCoercionImpactStrategy) inject this
    reader to look up confirmed edges originating at a changed
    ``(source_id, src_column)`` and propose downstream impacts.

    Fold semantics applied at read time:

    * ``lineage_edge_proposed`` → seed an edge record (state="proposed",
      tracking proposal payload).
    * ``lineage_edge_confirmed`` → flip state="confirmed" on the matching
      edge_id.
    * ``lineage_edge_rejected`` → flip state="rejected" on the matching
      edge_id (last-write-wins on conflicting state changes per the L3
      projection-fold semantics; re-confirmation after rejection emits a
      new entry, so walking ledger-order gives the same final state).

    Tenant scope rides on ``company_id`` per call. No per-instance
    tenant pinning — the reader instance is shared across strategies
    and tests, and each strategy invocation passes its own company_id.

    Replay-stability: ledger fetch is oldest-first, so iterating entries
    in order gives the same final state across runs. Two callers
    invoking with identical (company_id, source_id, src_column) get
    byte-identical LineageEdgeRecord tuples.
    """

    ledger: _LedgerFetcher

    async def list_confirmed_edges_for_source_column(
        self,
        *,
        source_id: str,
        src_column: str,
        company_id: UUID,
    ) -> list[Any]:  # list[LineageEdgeRecord]; Any to defer import
        """Return L3-confirmed edges originating at ``(source_id, src_column)``.

        Filter contract:

        * state="confirmed" — only L3-confirmed edges propagate impacts.
        * src_table_id starts with ``"<source_id>."`` — edges sourced
          from the changing source.
        * src_column equals the changed column. Edges with
          ``src_column=None`` (whole-table dbt-manifest refs) are
          skipped — L4 only reasons over column-grain propagation.

        Returns ``[]`` when no confirmed edges match — callers treat
        this as a no-op (the strategy proposes no impacts).

        Performance note: this walks the full tenant ledger per call.
        For typical lake sizes (10s-100s of confirmed edges) the cost
        is negligible. A future optimization can index by
        (company_id, src_table_id_prefix, src_column) once the
        projection_lineage_edges table is queryable.
        """
        # Lazy import to avoid importing the agent-gateway package at
        # module import time (mirrors the lineage_catalog_reader pattern).
        from wormbase_agent_gateway.schema_impact import LineageEdgeRecord

        if not source_id or not src_column:
            return []

        entries = await self.ledger.fetch(company_id)

        # First pass: gather lineage_edge_proposed payloads keyed by edge_id.
        # Multiple proposals for the same edge_id collapse to the
        # latest-confidence row (last-write-wins, matching the L3 fold's
        # UPDATE-evidence-on-re-proposal semantics).
        edge_payloads: dict[str, dict[str, Any]] = {}
        # Second pass: track final state via ledger order.
        edge_states: dict[str, str] = {}

        source_prefix = f"{source_id}."

        for entry in entries:
            if _is_emit_tool(entry, "emit_lineage_edge_proposed"):
                args = _execute_args(entry)
                edge_id = str(args.get("edge_id") or "")
                if not edge_id:
                    continue
                src_table_id = str(args.get("src_table_id") or "")
                if not src_table_id.startswith(source_prefix):
                    continue
                raw_src_col = args.get("src_column")
                if not isinstance(raw_src_col, str) or raw_src_col != src_column:
                    continue
                # Record / overwrite the proposal payload for this edge.
                edge_payloads[edge_id] = args
                # Initialise state on first proposal; re-proposal does not
                # change state (matches L3 fold semantics — state stays
                # "proposed" on re-proposal).
                edge_states.setdefault(edge_id, "proposed")
            elif _is_emit_tool(entry, "emit_lineage_edge_confirmed"):
                args = _execute_args(entry)
                edge_id = str(args.get("edge_id") or "")
                if not edge_id or edge_id not in edge_payloads:
                    continue
                edge_states[edge_id] = "confirmed"
            elif _is_emit_tool(entry, "emit_lineage_edge_rejected"):
                args = _execute_args(entry)
                edge_id = str(args.get("edge_id") or "")
                if not edge_id or edge_id not in edge_payloads:
                    continue
                edge_states[edge_id] = "rejected"

        # Materialise into LineageEdgeRecord tuples for every edge whose
        # final state is "confirmed". Deterministic ordering by edge_id
        # for replay stability.
        records: list[Any] = []
        for edge_id in sorted(edge_payloads):
            if edge_states.get(edge_id) != "confirmed":
                continue
            args = edge_payloads[edge_id]
            tgt_col = args.get("tgt_column")
            # Skip records with empty/None tgt_column — downstream
            # impact propagation needs a column-grain target.
            if not isinstance(tgt_col, str) or not tgt_col:
                continue
            confidence_raw = args.get("confidence")
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                # Defensive: skip malformed rows rather than crash the
                # reader (a schema drift in the ledger should not break
                # cross-axis read).
                logger.warning(
                    "skipping lineage edge %s: confidence not float (%r)",
                    edge_id, confidence_raw,
                )
                continue
            records.append(
                LineageEdgeRecord(
                    edge_id=edge_id,
                    src_table_id=str(args.get("src_table_id") or ""),
                    src_column=src_column,
                    tgt_table_id=str(args.get("tgt_table_id") or ""),
                    tgt_column=tgt_col,
                    confidence=confidence,
                    strategy=str(args.get("strategy") or ""),
                ),
            )
        return records
