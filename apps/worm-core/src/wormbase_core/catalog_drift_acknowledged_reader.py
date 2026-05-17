"""L4↦L2 cross-axis adapter — LedgerAcknowledgedDriftReader.

The L4↦L2 cross-axis chain (7th cross-axis chain, first BIDIRECTIONAL
chain — shipped 2026-06-12) adds a PRODUCER-side Reader Protocol on
L2's catalog_drift subpackage:
:class:`wormbase_agent_gateway.catalog_drift.AcknowledgedDriftReader`.
The Protocol describes the read pattern L4's
:class:`AcknowledgedDriftImpactStrategy` needs to elevate schema-
evolution impact severity based on L2's acknowledged catalog drifts.

This module ships the production impl that
``agent_gateway_construction.compose_schema_impact_reactivity_if_enabled``
threads into the strategy via the composite factory (when the env
sub-knob ``WORMBASE_SCHEMA_IMPACT_ACKNOWLEDGED_DRIFT_ENABLED`` is
truthy). A single shared instance is constructed once per boot wire so
the strategy and any future cross-axis consumers see the same read
surface.

Implementation approach: ledger-walk + projection-fold replay. Walks
the tenant-scoped ledger for ``catalog_drift_proposed`` /
``catalog_drift_acknowledged`` / ``catalog_drift_rejected`` execute
entries and reconstructs the projection_catalog_drifts row state in-
memory. Mirrors :class:`LedgerConfirmedClassificationReader` and the
rest of the lake-side readers which all walk the ledger via
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

When the ledger materialises the projection_catalog_drifts table via
SQL (Postgres), a future optimization can swap this impl for a direct
SQL reader behind the same Protocol surface — no caller changes.

Filter contract per Protocol:

* state="acknowledged" only — only L2-acknowledged drifts elevate L4
  impact severity. Drifts in proposed state OR rejected state are NOT
  exposed. A drift acknowledged then later rejected is NOT exposed
  (rejection wins). A drift rejected then re-proposed-and-acknowledged
  IS exposed (last-write-wins per the projection-fold semantics in
  v028).
* The proposal payload (source/table/column/drift_kind/before/after)
  is folded from the original ``catalog_drift_proposed`` entry; the
  acknowledgement payload (acknowledged_by_person_id + ts) is folded
  from the ``catalog_drift_acknowledged`` entry. The Record exposes
  the JOIN.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger(
    "wormbase_core.catalog_drift_acknowledged_reader",
)

__all__ = [
    "LedgerAcknowledgedDriftReader",
]


class _LedgerFetcher(Protocol):
    """Minimal surface this module needs from a Ledger-like object."""

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


def _entry_ts(entry: dict[str, Any]) -> datetime:
    """Best-effort extraction of an entry's timestamp.

    Order of attempts:
      1. ``entry["ts"]`` — canonical InMem ledger field, may be
         datetime or ISO string.
      2. ``entry["payload"]["ts"]`` — some payload shapes carry their
         own ts.
      3. Fallback to epoch (1970-01-01 UTC).
    """
    raw = entry.get("ts")
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    payload = entry.get("payload")
    if isinstance(payload, dict):
        raw2 = payload.get("ts")
        if isinstance(raw2, datetime):
            return raw2
        if isinstance(raw2, str):
            try:
                return datetime.fromisoformat(raw2)
            except ValueError:
                pass
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass
class LedgerAcknowledgedDriftReader:
    """Reads L2's acknowledged catalog drifts via ledger walk + fold replay.

    Implements the
    :class:`wormbase_agent_gateway.catalog_drift.AcknowledgedDriftReader`
    Protocol — the **7th cross-axis read** in the lake stack and the
    **first PRODUCER-side L2 Reader Protocol** for a peer-axis chain
    (L2's :class:`CatalogSnapshotReader` is a platform-substrate reader
    of ``external_catalog_imported`` — distinct category per spec §4.6).
    L4's
    :class:`wormbase_agent_gateway.schema_impact.strategies.AcknowledgedDriftImpactStrategy`
    injects this reader to elevate impact severity based on operator-
    acknowledged catalog drifts.

    Fold semantics applied at read time:

    * ``catalog_drift_proposed`` → seed a drift record (state="proposed",
      capturing source_id/table_id/column/drift_kind/before/after).
    * ``catalog_drift_acknowledged`` → flip state="acknowledged" on the
      matching drift_id; capture ``acknowledged_by_person_id`` +
      ``acknowledged_at`` from the acknowledgement entry.
    * ``catalog_drift_rejected`` → flip state="rejected" on the matching
      drift_id (last-write-wins per the L2 projection-fold semantics;
      re-acknowledgement after rejection emits a new entry, so walking
      ledger-order gives the same final state).

    Tenant scope rides on ``company_id`` per call. No per-instance
    tenant pinning — the reader instance is shared and each strategy
    invocation passes its own company_id.

    Replay-stability: ledger fetch is oldest-first, so iterating
    entries in order gives the same final state across runs. Two
    callers invoking with identical (company_id, source_id, src_column)
    get byte-identical
    :class:`AcknowledgedDriftRecord` tuples — sorted by ``drift_id``
    for deterministic ordering.
    """

    ledger: _LedgerFetcher

    async def _fold_acknowledged_drifts(
        self,
        *,
        company_id: UUID,
    ) -> dict[str, Any]:
        """Walk the tenant ledger and fold the catalog-drift state machine.

        Returns a dict of acknowledged-state drifts keyed by drift_id,
        each carrying the joined proposal payload + acknowledgement
        metadata. Used by both public read methods.
        """
        entries = await self.ledger.fetch(company_id)

        # Track proposal payloads keyed by drift_id (last proposal
        # wins; re-proposal of the same drift_id after rejection seeds
        # a fresh payload).
        drift_payloads: dict[str, dict[str, Any]] = {}
        # Track final state via ledger-order walk.
        drift_states: dict[str, str] = {}
        # Capture acknowledgement metadata when state flips to
        # acknowledged (needed for Record fields acknowledged_at +
        # acknowledged_by_person_id).
        ack_meta: dict[str, dict[str, Any]] = {}

        for entry in entries:
            if _is_emit_tool(entry, "emit_catalog_drift_proposed"):
                args = _execute_args(entry)
                drift_id = str(args.get("drift_id") or "")
                if not drift_id:
                    continue
                drift_payloads[drift_id] = args
                # Re-proposal resets the state to "proposed" (it's a
                # NEW logical drift event even if the drift_id matches
                # — see L2 doctrine on forward-only re-states).
                drift_states[drift_id] = "proposed"
                # Drop any prior acknowledgement meta — re-proposal
                # invalidates the previous ack.
                ack_meta.pop(drift_id, None)
            elif _is_emit_tool(entry, "emit_catalog_drift_acknowledged"):
                args = _execute_args(entry)
                drift_id = str(args.get("drift_id") or "")
                if not drift_id or drift_id not in drift_payloads:
                    continue
                drift_states[drift_id] = "acknowledged"
                ack_meta[drift_id] = {
                    "acknowledged_at": _entry_ts(entry),
                    "acknowledged_by_person_id": str(
                        args.get("acknowledged_by_person_id") or "",
                    ),
                }
            elif _is_emit_tool(entry, "emit_catalog_drift_rejected"):
                args = _execute_args(entry)
                drift_id = str(args.get("drift_id") or "")
                if not drift_id or drift_id not in drift_payloads:
                    continue
                drift_states[drift_id] = "rejected"
                # Drop ack meta if a previously-acknowledged drift was
                # flipped to rejected.
                ack_meta.pop(drift_id, None)

        # Filter to drift_ids whose final state is acknowledged.
        acknowledged: dict[str, Any] = {}
        for drift_id, state in drift_states.items():
            if state != "acknowledged":
                continue
            payload = drift_payloads.get(drift_id)
            if payload is None:
                continue
            meta = ack_meta.get(drift_id) or {}
            acknowledged[drift_id] = {
                "payload": payload,
                "meta": meta,
            }
        return acknowledged

    def _materialise(
        self,
        *,
        drift_id: str,
        joined: dict[str, Any],
    ) -> Any | None:  # AcknowledgedDriftRecord (lazy import)
        """Build a single :class:`AcknowledgedDriftRecord` from joined data.

        Returns ``None`` when the joined data is malformed (no source_id
        / table_id / drift_kind) — defensive against partial payloads.
        """
        from wormbase_agent_gateway.catalog_drift import (
            AcknowledgedDriftRecord,
        )

        payload = joined["payload"]
        meta = joined["meta"]

        source_id = str(payload.get("source_id") or "")
        table_id = str(payload.get("table_id") or "")
        drift_kind = str(payload.get("drift_kind") or "")
        if not source_id or not table_id or not drift_kind:
            logger.warning(
                "skipping drift %s: incomplete payload (source_id=%r table_id=%r drift_kind=%r)",
                drift_id, source_id, table_id, drift_kind,
            )
            return None

        column_raw = payload.get("column")
        column: str | None
        if column_raw is None:
            column = None
        else:
            column = str(column_raw) or None

        before = payload.get("before")
        if before is not None and not isinstance(before, dict):
            before = None
        after = payload.get("after")
        if after is not None and not isinstance(after, dict):
            after = None

        acknowledged_at = meta.get("acknowledged_at")
        if not isinstance(acknowledged_at, datetime):
            acknowledged_at = datetime(1970, 1, 1, tzinfo=timezone.utc)
        acknowledged_by = meta.get("acknowledged_by_person_id") or ""

        return AcknowledgedDriftRecord(
            drift_id=drift_id,
            source_id=source_id,
            table_id=table_id,
            column=column,
            drift_kind=drift_kind,
            before=before,
            after=after,
            acknowledged_at=acknowledged_at,
            acknowledged_by_person_id=acknowledged_by,
        )

    async def list_acknowledged_drifts(
        self,
        *,
        company_id: UUID,
    ) -> list[Any]:  # list[AcknowledgedDriftRecord]
        """Return ALL acknowledged drifts for the tenant.

        Performance note: this walks the full tenant ledger per call.
        For typical lake sizes (10s-100s of acknowledged drifts) the
        cost is negligible. A future optimization can read directly
        from projection_catalog_drifts (where state = 'acknowledged')
        once the projection table is queryable inline.
        """
        acknowledged = await self._fold_acknowledged_drifts(
            company_id=company_id,
        )
        records: list[Any] = []
        for drift_id in sorted(acknowledged):
            rec = self._materialise(
                drift_id=drift_id, joined=acknowledged[drift_id],
            )
            if rec is not None:
                records.append(rec)
        return records

    async def list_acknowledged_drifts_for_source_column(
        self,
        source_id: str,
        src_column: str | None,
        *,
        company_id: UUID,
    ) -> list[Any]:  # list[AcknowledgedDriftRecord]
        """Return acknowledged drifts on ``(source_id, src_column)``.

        Filter contract:

        * state="acknowledged" — only L2-acknowledged drifts.
        * source_id match: exact equal to drift's ``source_id``.
        * src_column match: when non-None, exact column match;
          when None, returns ONLY table-level drifts (drift.column is
          None).

        Returns ``[]`` when no acknowledged drifts match — callers
        treat this as a no-op (the strategy proposes no acknowledged-
        drift-elevated impacts).
        """
        if not source_id:
            return []
        all_acked = await self.list_acknowledged_drifts(company_id=company_id)
        out: list[Any] = []
        for r in all_acked:
            if r.source_id != source_id:
                continue
            if src_column is None:
                if r.column is not None:
                    continue
            else:
                if r.column != src_column:
                    continue
            out.append(r)
        return out
