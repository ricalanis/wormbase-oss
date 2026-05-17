"""L6 Sub-wave C — concrete LedgerConfirmedSemanticTypeReader for column-classification discovery.

Sub-wave B introduced the :class:`ConfirmedSemanticTypeReader` Protocol
on the column_classification subpackage in ``wormbase-agent-gateway``.
The Protocol is the **second cross-axis read** in the lake-side
compounding stack (after L4's :class:`LineageEdgeReader`) — L6
strategies query L5's confirmed semantic types when proposing
column-level governance classifications.

This module ships the production impl that
``agent_gateway_construction.compose_column_classification_reactivity_if_enabled``
threads into the :class:`SemanticTypeClassificationStrategy` via the
composite factory. A single shared instance is constructed once per
boot wire so the strategy and any future cross-axis consumers see the
same read surface.

Implementation approach: ledger-walk + projection-fold replay. We walk
the tenant-scoped ledger for ``semantic_type_proposed`` /
``semantic_type_confirmed`` / ``semantic_type_rejected`` execute entries
and reconstruct the projection_semantic_types row state in-memory.
This mirrors the rest of the lake-side readers (LedgerCatalogReader,
LedgerDbtManifestReader, LedgerDbtTestReader, LedgerDecisionReader,
LedgerProcessMapReader, LedgerLineageEdgeReader) which all walk the
ledger via ``ledger.fetch(company_id)`` rather than reading Postgres
projection tables directly.

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

When the ledger materialises the projection_semantic_types table via
SQL (Postgres), a future optimization can swap this impl for a direct
SQL reader behind the same Protocol surface — no caller changes.

Filter contract per Sub-wave B Protocol:

* state="confirmed" only (we only propagate classifications from
  L5-confirmed semantic types; proposed-but-not-confirmed types are too
  noisy and would create premature governance proposals).
* table_id matches exactly (per-column-per-table grain).
* column matches exactly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger("wormbase_core.column_classification_semantic_reader")

__all__ = [
    "LedgerConfirmedSemanticTypeReader",
]


class _LedgerFetcher(Protocol):
    """Minimal surface this module needs from a Ledger-like object.

    Matches the shape in
    :class:`wormbase_core.schema_impact_lineage_reader._LedgerFetcher` —
    a fetch-by-company_id async call returning ledger row dicts.
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
class LedgerConfirmedSemanticTypeReader:
    """Reads L5's confirmed semantic types via ledger walk + fold replay.

    Implements the
    :class:`wormbase_agent_gateway.column_classification.ConfirmedSemanticTypeReader`
    Protocol — the **second cross-axis read** in the lake stack
    (after L4's :class:`LedgerLineageEdgeReader`). L6's
    :class:`SemanticTypeClassificationStrategy` injects this reader to
    look up confirmed semantic types for the column under
    classification.

    Fold semantics applied at read time:

    * ``semantic_type_proposed`` → seed a type record (state="proposed",
      tracking proposal payload).
    * ``semantic_type_confirmed`` → flip state="confirmed" on the
      matching type_id.
    * ``semantic_type_rejected`` → flip state="rejected" on the matching
      type_id (last-write-wins on conflicting state changes per the L5
      projection-fold semantics; re-confirmation after rejection emits a
      new entry, so walking ledger-order gives the same final state).

    Tenant scope rides on ``company_id`` per call. No per-instance
    tenant pinning — the reader instance is shared and each strategy
    invocation passes its own company_id.

    Replay-stability: ledger fetch is oldest-first, so iterating entries
    in order gives the same final state across runs. Two callers
    invoking with identical (company_id, table_id, column) get
    byte-identical :class:`ConfirmedSemanticTypeRecord` tuples — sorted
    by ``type_id`` for deterministic ordering.
    """

    ledger: _LedgerFetcher

    async def list_confirmed_types_for_table_column(
        self,
        *,
        table_id: str,
        column: str,
        company_id: UUID,
    ) -> list[Any]:  # list[ConfirmedSemanticTypeRecord]; Any defers import
        """Return L5-confirmed semantic types for ``(table_id, column)``.

        Filter contract:

        * state="confirmed" — only L5-confirmed types feed L6.
        * table_id matches exactly.
        * column matches exactly.

        Returns ``[]`` when no confirmed types match — callers treat
        this as a no-op (the strategy proposes no classifications via
        the semantic-type path; the ``naming_pattern`` +
        ``domain_default`` strategies still fire independently).

        Performance note: this walks the full tenant ledger per call.
        For typical lake sizes (10s-100s of confirmed types) the cost
        is negligible. A future optimization can index by
        (company_id, table_id, column) once the
        projection_semantic_types table is queryable.
        """
        # Lazy import to avoid importing the agent-gateway package at
        # module import time (mirrors the schema_impact_lineage_reader
        # pattern).
        from wormbase_agent_gateway.column_classification import (
            ConfirmedSemanticTypeRecord,
        )

        if not table_id or not column:
            return []

        entries = await self.ledger.fetch(company_id)

        # First pass: gather semantic_type_proposed payloads keyed by
        # type_id. Multiple proposals for the same type_id collapse to
        # the latest row (last-write-wins, matching the L5 fold's
        # UPDATE-evidence-on-re-proposal semantics).
        type_payloads: dict[str, dict[str, Any]] = {}
        # Second pass: track final state via ledger order.
        type_states: dict[str, str] = {}

        for entry in entries:
            if _is_emit_tool(entry, "emit_semantic_type_proposed"):
                args = _execute_args(entry)
                type_id = str(args.get("type_id") or "")
                if not type_id:
                    continue
                entry_table = str(args.get("table_id") or "")
                entry_column = str(args.get("column") or "")
                if entry_table != table_id or entry_column != column:
                    continue
                # Record / overwrite the proposal payload for this type.
                type_payloads[type_id] = args
                type_states.setdefault(type_id, "proposed")
            elif _is_emit_tool(entry, "emit_semantic_type_confirmed"):
                args = _execute_args(entry)
                type_id = str(args.get("type_id") or "")
                if not type_id or type_id not in type_payloads:
                    continue
                type_states[type_id] = "confirmed"
            elif _is_emit_tool(entry, "emit_semantic_type_rejected"):
                args = _execute_args(entry)
                type_id = str(args.get("type_id") or "")
                if not type_id or type_id not in type_payloads:
                    continue
                type_states[type_id] = "rejected"

        # Materialise into ConfirmedSemanticTypeRecord tuples for every
        # type whose final state is "confirmed". Deterministic ordering
        # by type_id for replay stability.
        records: list[Any] = []
        for type_id in sorted(type_payloads):
            if type_states.get(type_id) != "confirmed":
                continue
            args = type_payloads[type_id]
            semantic_type = args.get("semantic_type")
            if not isinstance(semantic_type, str) or not semantic_type:
                continue
            confidence_raw = args.get("confidence")
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                # Defensive: skip malformed rows rather than crash the
                # reader (a schema drift in the ledger should not break
                # cross-axis read).
                logger.warning(
                    "skipping semantic type %s: confidence not float (%r)",
                    type_id, confidence_raw,
                )
                continue
            strategy = str(args.get("strategy") or "")
            records.append(
                ConfirmedSemanticTypeRecord(
                    type_id=type_id,
                    semantic_type=semantic_type,
                    confidence=confidence,
                    strategy=strategy,
                ),
            )
        return records
