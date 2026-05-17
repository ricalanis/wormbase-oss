"""L2 Sub-wave C — concrete LedgerCatalogSnapshotReader for catalog-drift detection.

Sub-wave B introduced the :class:`CatalogSnapshotReader` Protocol on
the ``catalog_drift`` subpackage in ``wormbase-agent-gateway``. The
Protocol is the **first platform reader** in the lake-side compounding
stack — it reads catalog-mirror substrate
(``external_catalog_imported`` entries) rather than a peer L-axis
projection. Per spec §4.6 doctrine clarification, this is a
**platform-reader** category and does NOT count as a cross-axis chain
(cross-axis chain count stays at 3: L4→L3, L6→L5, L8→L5).

This module ships the production impl that
``agent_gateway_construction.compose_catalog_drift_reactivity_if_enabled``
threads into the L2 ``Compounding`` Reactivity at install boot. A
single shared instance is constructed per boot wire — the reader
carries no per-instance state.

Implementation approach: ledger-walk + fold replay. We walk the
tenant-scoped ledger via ``ledger.fetch(company_id)`` for execute
entries whose payload ``tool`` equals ``emit_external_catalog_imported``,
filter to the requested ``source_id``, and fold the most-recent two
entries into ``(current, baseline)`` :class:`CatalogSnapshot` objects.

This mirrors the rest of the lake-side readers
(LedgerCatalogReader, LedgerLineageEdgeReader,
LedgerConfirmedSemanticTypeReader, LedgerDomainDefaultReader,
LedgerConnectedSourceReader, LedgerKpiNodeReader,
LedgerSilverConversationReader) which all walk the ledger rather than
querying Postgres projection tables directly. The rationale:

* Works against InMemoryLedger (tests) and DB-backed Ledger (prod)
  with the same code path. Avoids a SQL-only impl that breaks the
  in-memory-ledger test pattern used across worm-core.
* Replay-stable by construction — the ledger IS the source of truth.
* Tenant scope rides on ``company_id`` per call — same surface as the
  rest of the lake-side readers.

Today's snapshot reconstruction posture (Wave 1):

The ``external_catalog_imported`` payload carries ``snapshot_hash`` +
``table_count`` + ``edge_count`` + ``metric_count`` + ``import_mode``
but NOT a per-table column structure (Sub-wave B handoff confirmed
the entry carries only counts/hashes today). The reader therefore
returns a :class:`CatalogSnapshot` whose ``tables`` tuple is empty —
matching Sub-wave B's empty-upstream posture for the ColumnSet /
ColumnType strategies.

The TableSetDriftStrategy operates productively today on richer
signal carried by **``external_catalog_drift_detected``** entries
(which DO carry ``added_table_ids`` / ``removed_table_ids`` /
``changed_table_ids``). The strategies consume those tuples directly
via the existing composite contract — this reader's job is just to
return the snapshot pair anchored at the correct timestamps so the
gather_fn can correlate them.

When richer-diff emitters land (per-table column metadata in
``external_catalog_imported``), the same dataclass shape carries the
columns without any reader-side schema change — the fold extends to
walk per-table records and ``CatalogTable.columns`` becomes
non-empty automatically.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger("wormbase_core.catalog_drift_snapshot_reader")

__all__ = [
    "LedgerCatalogSnapshotReader",
]


class _LedgerFetcher(Protocol):
    """Minimal surface this module needs from a Ledger-like object.

    Matches the shape in
    :class:`wormbase_core.source_candidate_readers._LedgerFetcher` —
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


def _entry_ts_to_datetime(value: Any) -> datetime:
    """Coerce a ledger entry ``ts`` value to a tz-aware datetime.

    Accepts ISO-8601 strings (``"2026-05-16T12:00:00+00:00"``) and
    :class:`datetime` instances. Falls back to ``datetime.now(UTC)``
    when the value is missing or unparseable (defensive — the reader
    must not crash on schema drift; the synthetic timestamp is still
    deterministic-ish at replay time because the ledger seqs are
    folded in monotonic order before we get here).
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(UTC)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    return datetime.now(UTC)


@dataclass
class LedgerCatalogSnapshotReader:
    """Reads ``external_catalog_imported`` ledger entries to reconstruct snapshots.

    Implements the
    :class:`wormbase_agent_gateway.catalog_drift.CatalogSnapshotReader`
    Protocol. Returns ``(current, baseline)`` where:

    * ``current`` is the most-recent ``external_catalog_imported``
      execute entry for ``(company_id, source_id)``.
    * ``baseline`` is the second-most-recent one, or ``None`` if only
      one snapshot has landed for the source.

    Both snapshots carry the source's ``table_count`` /
    ``snapshot_hash`` lineage via the ``as_of`` timestamp + an empty
    ``tables`` tuple (per Sub-wave A/B handoff: the entry shape does
    not yet expose per-table column structure). When richer-diff
    emitters land, the dataclass shape carries the columns without
    any reader-side schema change.

    Tenant scope rides on ``company_id`` per call. No per-instance
    tenant pinning — the reader instance is shared and each call
    passes its own company_id (same shape as
    :class:`LedgerConfirmedSemanticTypeReader` +
    :class:`LedgerKpiNodeReader`).

    Replay-stability: ``ledger.fetch()`` is oldest-first; walking
    entries in order and picking the last two of-kind yields the
    same ``(current, baseline)`` pair across runs for a fixed ledger
    snapshot.

    Empty-state contract: when no ``external_catalog_imported`` exists
    for ``(company_id, source_id)``, returns
    ``(CatalogSnapshot(source_id, datetime.now(UTC), ()), None)`` —
    the gather_fn treats either signal as "no drift to compute" so
    the synthetic empty current is harmless.
    """

    ledger: _LedgerFetcher

    async def read_current_and_baseline(
        self,
        *,
        company_id: UUID,
        source_id: str,
    ) -> tuple[Any, Any | None]:  # (CatalogSnapshot, CatalogSnapshot | None)
        """Return ``(current, baseline)`` snapshots for ``(company_id, source_id)``.

        Walks the tenant ledger for execute entries whose ``tool`` is
        ``emit_external_catalog_imported`` and ``args.source_id``
        matches the requested source. Folds the most-recent two
        entries into :class:`CatalogSnapshot` records.

        Per Sub-wave B handoff concern #1: imports
        :class:`CatalogSnapshot` from
        :mod:`wormbase_agent_gateway.catalog_drift`, NOT from
        :mod:`wormbase_agent_gateway.lineage` (the two modules carry
        identically-named dataclasses with diverging semantics).
        Lazy-imported to avoid pulling the agent-gateway package at
        module import time (mirrors the L1/L6 reader pattern).
        """
        # Lazy import to avoid importing the agent-gateway package at
        # module import time (mirrors the L1/L6 reader pattern). Per
        # Sub-wave B handoff concern #1 the dataclasses come from the
        # catalog_drift subpackage, NOT from lineage.
        from wormbase_agent_gateway.catalog_drift import CatalogSnapshot

        if not source_id:
            return (
                CatalogSnapshot(
                    source_id=source_id,
                    as_of=datetime.now(UTC),
                    tables=(),
                ),
                None,
            )

        entries = await self.ledger.fetch(company_id)

        # Collect every external_catalog_imported entry for this
        # source in ledger order (oldest-first per fetch semantics).
        # The duplicate-tick absorption notion from the dispatch is
        # handled at the projection PK layer (v028 fold) — re-emitting
        # the same drift_id collapses to the same row. Here on the
        # reader side we just preserve order and pick the last two.
        matched: list[dict[str, Any]] = []
        for entry in entries:
            if not _is_emit_tool(entry, "emit_external_catalog_imported"):
                continue
            args = _execute_args(entry)
            if str(args.get("source_id") or "") != source_id:
                continue
            matched.append(entry)

        if not matched:
            # No snapshots for this source — return an empty
            # synthetic current so the gather_fn sees a well-formed
            # CatalogSnapshot. The empty tables tuple + None baseline
            # signals "no drift to compute" to the strategies.
            return (
                CatalogSnapshot(
                    source_id=source_id,
                    as_of=datetime.now(UTC),
                    tables=(),
                ),
                None,
            )

        # Most-recent is the LAST entry in ledger order (fetch is
        # oldest-first); baseline is the second-to-last when present.
        current_entry = matched[-1]
        baseline_entry: dict[str, Any] | None = (
            matched[-2] if len(matched) >= 2 else None
        )

        current = CatalogSnapshot(
            source_id=source_id,
            as_of=_entry_ts_to_datetime(current_entry.get("ts")),
            tables=(),
        )
        baseline: Any | None = None
        if baseline_entry is not None:
            baseline = CatalogSnapshot(
                source_id=source_id,
                as_of=_entry_ts_to_datetime(baseline_entry.get("ts")),
                tables=(),
            )
        return (current, baseline)
