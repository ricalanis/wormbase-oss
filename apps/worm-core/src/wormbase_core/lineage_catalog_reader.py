"""L3 Sub-wave C — production CatalogReader + DbtManifestReader for lineage discovery.

Sub-wave B introduced the ``_CatalogReader`` Protocol on the lineage
Compounding factory in ``wormbase-agent-gateway``. The Protocol shape:

  * ``async list_tables_for_source(*, company_id, source_id) -> list[CatalogTable]``
  * ``async list_candidate_targets(*, company_id, source_id) -> list[CatalogTable]``

This module ships the production-impl that the boot wire constructs in
``agent_gateway_construction.compose_lineage_reactivity_if_enabled``.

LedgerCatalogReader walks ``external_catalog_imported``,
``external_lineage_imported``, and ``catalog_table_imported`` ledger
entries. The Wave 1 substrate (catalog summary + lineage edges) ships
table_ids without column structure; the Wave 2 substrate
(``catalog_table_imported``) layers per-table column lists on top so
the reader can return :class:`CatalogTable` records with populated
``columns`` tuples. Pre-Wave-2 snapshots that never emitted
``catalog_table_imported`` continue to read ``columns=()`` —
strategies that need column grain (``NamingHeuristicStrategy``,
``SampleOverlapStrategy``) no-op cleanly. Wave 2 emitters (csv_local,
dbt, snowflake) populate columns and the same strategies become
productive automatically.

``LedgerDbtManifestReader`` walks ``external_lineage_imported`` entries
to expose the per-model ``ref()`` / ``source()`` shape the
``DbtManifestStrategy`` consumes. The catalog mirror does not currently
distinguish ``ref()`` from ``source()`` at the ledger boundary; the
reader treats all upstream edges as ``ref()`` candidates (honest stub
behaviour — a future ``external_dbt_manifest_imported`` payload would
let this split cleanly).

``NoopSampler`` is the production fallback for the
:class:`SampleOverlapStrategy` sampler slot. It returns empty sample
sets and zero table sizes — the strategy will short-circuit to empty
edge lists. Real sampling requires a connector-backed
``CredentialBroker``-issued account and is wired in a future wave;
NoopSampler keeps the env-knob path honest by surfacing "no sampling
performed" via empty proposals rather than crashing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger("wormbase_core.lineage_catalog_reader")

__all__ = [
    "LedgerCatalogReader",
    "LedgerDbtManifestReader",
    "NoopSampler",
]


class _LedgerFetcher(Protocol):
    """Minimal surface this module needs from a Ledger-like object.

    Matches the shape in ``agent_gateway_readers._LedgerFetcher``.
    """

    async def fetch(
        self, company_id: UUID, until_ts: Any | None = ...,
    ) -> list[dict[str, Any]]: ...  # pragma: no cover


def _execute_args(entry: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``args`` dict from an execute entry's payload.

    Returns ``{}`` when the payload shape is unexpected (defensive — a
    ledger-rewrite or schema drift should not crash boot).
    """
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
class LedgerCatalogReader:
    """Reads catalog tables from ``external_catalog_imported`` +
    ``external_lineage_imported`` ledger entries.

    Returns ``CatalogTable``-shaped dicts; the lineage subpackage
    consumes the Protocol structurally so we avoid a hard import on
    ``wormbase_agent_gateway.lineage.CatalogTable``.

    Tenant isolation: every call requires ``company_id`` and we walk
    the per-tenant ledger via ``Ledger.fetch(company_id)`` — the same
    pattern used by ``LedgerDecisionReader`` and friends.

    Candidate-target enumeration: ``list_candidate_targets`` returns
    every distinct table_id seen across ALL ``external_lineage_imported``
    entries for the company, EXCLUDING tables already owned by the
    triggering ``source_id`` (those are the source side, not the
    candidate side). Bounded by ``max_targets`` per the Sub-wave B
    concern to keep the inference candidate set tractable.
    """

    ledger: _LedgerFetcher

    async def list_tables_for_source(
        self,
        *,
        company_id: UUID,
        source_id: str,
    ) -> list[dict[str, Any]]:
        """Return CatalogTable-shaped dicts for the given source.

        Sources tables are derived from two complementary signals:

        1. ``catalog_table_imported`` entries with matching ``source_id``
           — the Wave 2 substrate carrying per-table column metadata.
        2. ``external_lineage_imported`` edges with matching ``source_id``
           — the Wave 1 signal that names tables without column grain.

        Both contribute table_ids; the column tuple comes from (1) when
        present, falling back to ``()`` for table_ids that only appeared
        in lineage edges. This preserves pre-Wave-2 behaviour (no
        per-table entries → empty columns) while productively folding
        the new substrate when emitters write it.

        Returns ``[]`` when the source has no mirrored entries — the
        strategy then no-ops cleanly (empty source-table list).
        """
        entries = await self.ledger.fetch(company_id)
        source_kind = self._source_kind_for_source(entries, source_id)
        sid_str = str(source_id)

        # Pass 1: catalog_table_imported per-table substrate. Most-recent
        # entry wins per table_id (replay-stable: ledger.fetch is
        # oldest-first so the latest emit overwrites earlier ones).
        per_table_columns: dict[str, tuple[Any, ...]] = {}
        for entry in entries:
            if not _is_emit_tool(entry, "emit_catalog_table_imported"):
                continue
            args = _execute_args(entry)
            if str(args.get("source_id") or "") != sid_str:
                continue
            tid = str(args.get("table_id") or "")
            if not tid:
                continue
            per_table_columns[tid] = tuple(args.get("columns") or ())

        # Pass 2: external_lineage_imported edges (Wave 1 signal).
        table_ids: set[str] = set(per_table_columns.keys())
        for entry in entries:
            if not _is_emit_tool(entry, "emit_external_lineage_imported"):
                continue
            args = _execute_args(entry)
            if str(args.get("source_id") or "") != sid_str:
                continue
            for edge in args.get("edges") or ():
                # edges are list[list[upstream, downstream]] after JSON
                # round-trip, or tuple[tuple[str, str], ...] in-memory.
                if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                    up, dn = str(edge[0] or ""), str(edge[1] or "")
                    if up:
                        table_ids.add(up)
                    if dn:
                        table_ids.add(dn)

        out = [
            self._make_catalog_table(
                tid,
                source_kind=source_kind,
                columns_payload=per_table_columns.get(tid),
            )
            for tid in sorted(table_ids)
        ]
        return out

    async def list_candidate_targets(
        self,
        *,
        company_id: UUID,
        source_id: str,
        max_targets: int = 100,
    ) -> list[dict[str, Any]]:
        """Return CatalogTable-shaped dicts for candidate target tables.

        Walks every ``external_lineage_imported`` entry for this tenant
        and collects every distinct table_id seen, EXCLUDING tables
        that belong to the triggering ``source_id`` (those are the
        source side). Bounded by ``max_targets``; deterministic ordering
        (sorted by table_id) for replay stability.

        Tenant isolation rides on the ``company_id`` leg of
        ``ledger.fetch``.

        The Sub-wave B handoff concern flagged unbounded candidate
        enumeration — ``max_targets`` is the bound and the sort order
        keeps which-targets-are-kept deterministic across replays.
        """
        entries = await self.ledger.fetch(company_id)

        # Build a (table_id -> source_kind) mapping so candidates are
        # tagged with their owning source's kind (used by
        # DbtManifestStrategy's source_kind == "dbt" pre-filter).
        table_to_kind: dict[str, str] = {}
        # (source_id, table_id) -> columns payload (Wave 2 substrate).
        per_table_columns: dict[tuple[str, str], tuple[Any, ...]] = {}
        source_owned: dict[str, set[str]] = {}

        # First pass: map source_id -> source_kind from
        # external_catalog_imported.
        source_kinds: dict[str, str] = {}
        for entry in entries:
            if not _is_emit_tool(entry, "emit_external_catalog_imported"):
                continue
            args = _execute_args(entry)
            sid = str(args.get("source_id") or "")
            kind = str(args.get("source_kind") or "")
            if sid:
                # Most-recent wins per (source_id) — ledger fetch is
                # oldest-first, so a later refresh overwrites the
                # initial. Deterministic by ledger order.
                source_kinds[sid] = kind

        # Second pass: walk external_lineage_imported to enumerate tables
        # per source.
        for entry in entries:
            if not _is_emit_tool(entry, "emit_external_lineage_imported"):
                continue
            args = _execute_args(entry)
            sid = str(args.get("source_id") or "")
            if not sid:
                continue
            kind = source_kinds.get(sid, "")
            source_owned.setdefault(sid, set())
            for edge in args.get("edges") or ():
                if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                    up, dn = str(edge[0] or ""), str(edge[1] or "")
                    for tid in (up, dn):
                        if not tid:
                            continue
                        source_owned[sid].add(tid)
                        table_to_kind.setdefault(tid, kind)

        # Third pass: Wave 2 substrate — per-table catalog_table_imported
        # entries contribute table_ids AND populate per-table columns.
        # Includes table_ids that never appeared in lineage edges (e.g.
        # csv_local with no lineage but a populated catalog row).
        for entry in entries:
            if not _is_emit_tool(entry, "emit_catalog_table_imported"):
                continue
            args = _execute_args(entry)
            sid = str(args.get("source_id") or "")
            tid = str(args.get("table_id") or "")
            if not sid or not tid:
                continue
            source_owned.setdefault(sid, set()).add(tid)
            table_to_kind.setdefault(tid, source_kinds.get(sid, ""))
            per_table_columns[(sid, tid)] = tuple(args.get("columns") or ())

        # Collect every table_id NOT owned by the triggering source.
        own_tables = source_owned.get(str(source_id), set())
        # Map candidate table_id back to its owning source_id so we can
        # look up the per-table columns payload below. When the same
        # table_id is owned by multiple sources (rare), the last-walked
        # source wins — deterministic by ledger order.
        candidate_owner: dict[str, str] = {}
        candidate_ids: set[str] = set()
        for sid, tids in source_owned.items():
            if str(sid) == str(source_id):
                continue
            for tid in tids:
                candidate_ids.add(tid)
                candidate_owner[tid] = sid
        # Belt-and-braces: remove any overlap with the triggering source.
        candidate_ids -= own_tables

        # Deterministic ordering for replay stability, then bound.
        sorted_ids = sorted(candidate_ids)[: max(0, int(max_targets))]
        return [
            self._make_catalog_table(
                tid,
                source_kind=table_to_kind.get(tid, ""),
                columns_payload=per_table_columns.get(
                    (candidate_owner.get(tid, ""), tid),
                ),
            )
            for tid in sorted_ids
        ]

    def _source_kind_for_source(
        self, entries: list[dict[str, Any]], source_id: str,
    ) -> str:
        """Return the most-recent source_kind for ``source_id`` from
        ``external_catalog_imported`` entries, or ``""`` if absent.

        Most-recent wins: ledger fetch is oldest-first so the last
        matching entry's kind sticks.
        """
        kind = ""
        for entry in entries:
            if not _is_emit_tool(entry, "emit_external_catalog_imported"):
                continue
            args = _execute_args(entry)
            if str(args.get("source_id") or "") != str(source_id):
                continue
            kind = str(args.get("source_kind") or "")
        return kind

    @staticmethod
    def _make_catalog_table(
        table_id: str,
        *,
        source_kind: str,
        columns_payload: tuple[Any, ...] | None = None,
    ) -> dict[str, Any]:
        """Build a CatalogTable-shaped dict.

        Returned shape matches
        :class:`wormbase_agent_gateway.lineage.CatalogTable`:

          * ``table_id`` — the canonical table-id string.
          * ``columns`` — tuple of :class:`CatalogColumn` records
            populated from a per-table ``catalog_table_imported``
            payload when one exists (Wave 2 substrate); otherwise
            empty (Wave 1 honest-stub for callers operating on
            lineage-edge-only sources).
          * ``source_kind`` — the connector kind from the owning
            ``external_catalog_imported`` entry.
          * ``metadata`` — empty dict.

        We return a plain dict (not a dataclass) so the Protocol is
        consumed structurally on the strategy side — no import from
        ``wormbase_agent_gateway.lineage`` is required here.

        ``columns_payload`` accepts the JSON-round-tripped column
        spec list from the Wave 2 ``catalog_table_imported`` entry
        — each element is ``{"name": str, "type": str | None}``.
        Missing / None payload falls back to ``columns=()`` per the
        pre-Wave-2 behaviour, so existing snapshots without per-table
        entries continue to read columns=() and strategies that need
        column grain (NamingHeuristic / SampleOverlap) yield empty
        column lists. When columns ARE present (csv_local + dbt +
        snowflake post-Wave-2), the same strategies start firing
        productively.

        The lineage subpackage's :class:`CatalogTable` carries
        ``columns: tuple[str, ...]`` (column names only — type info
        is unused by the lineage strategies, which match on column
        names + samples). We project the rich ``CatalogColumnSpec``
        payload down to the name-only tuple here.
        """
        # Lazy import to avoid pulling the lineage subpackage at module
        # import time. Tests may patch this seam.
        from wormbase_agent_gateway.lineage import CatalogTable

        columns: tuple[str, ...] = ()
        if columns_payload:
            built: list[str] = []
            for raw in columns_payload:
                # Each spec is a dict after JSON round-trip
                # ({"name": str, "type": str | None}); be defensive
                # against malformed payloads (skip rather than crash).
                if not isinstance(raw, dict):
                    continue
                name = str(raw.get("name") or "")
                if not name:
                    continue
                built.append(name)
            columns = tuple(built)

        return CatalogTable(
            table_id=table_id,
            columns=columns,
            source_kind=source_kind,
            metadata={},
        )


@dataclass
class LedgerDbtManifestReader:
    """Reads dbt-manifest-shaped lineage from ``external_lineage_imported``.

    Honest stub for the ``DbtManifestStrategy.manifest_reader`` Protocol
    slot. The strategy expects ``get_refs_for_model`` /
    ``get_source_refs``; the catalog mirror does not currently
    distinguish ref()-vs-source() at the ledger boundary, so this
    reader exposes every upstream edge as a ``ref()`` candidate and
    returns an empty list for ``get_source_refs``. The strategy then
    proposes (upstream → source_table) edges with confidence 0.99 for
    every ledger-mirrored ref.

    Tenant scope is NOT in this Protocol — strategies operate on a
    single ``source_table.table_id`` and the ledger fetch is scoped by
    ``company_id`` at construction time. We accept a ``company_id``
    constructor arg to keep the read tenant-isolated.
    """

    ledger: _LedgerFetcher
    company_id: UUID

    async def get_refs_for_model(self, model_id: str) -> list[str]:
        """Return upstream table_ids referenced by ``model_id``.

        Walks ``external_lineage_imported`` entries; every edge whose
        ``downstream == model_id`` contributes the ``upstream`` side
        as a ref. Deterministic ordering (sorted) for replay
        stability; duplicate suppression via a set.
        """
        entries = await self.ledger.fetch(self.company_id)
        refs: set[str] = set()
        for entry in entries:
            if not _is_emit_tool(entry, "emit_external_lineage_imported"):
                continue
            args = _execute_args(entry)
            for edge in args.get("edges") or ():
                if isinstance(edge, (list, tuple)) and len(edge) >= 2:
                    up, dn = str(edge[0] or ""), str(edge[1] or "")
                    if dn == str(model_id) and up and up != str(model_id):
                        refs.add(up)
        return sorted(refs)

    async def get_source_refs(self, _model_id: str) -> list[str]:
        """Return source() refs for the model.

        The catalog mirror does not split ref() vs source() at the
        ledger boundary today; we return an empty list so the strategy
        emits only ref()-derived edges from
        :meth:`get_refs_for_model`. Future ``external_dbt_manifest_imported``
        payload will let this split cleanly.
        """
        return []


class NoopSampler:
    """Honest stub for the ``SampleOverlapStrategy.sampler`` Protocol.

    Returns empty sample sets + zero table-size estimates so the
    SampleOverlapStrategy short-circuits to empty edge lists even when
    env-enabled. Documents the "env-enabled but data layer not wired"
    state — operators see the strategy fire telemetry counter but no
    edges materialise.

    Real sampling requires a CredentialBroker-issued account on the
    upstream warehouse + a connector-backed query path; that wiring
    lands in a future wave. NoopSampler is the canonical fallback
    until then.
    """

    async def sample_column(
        self, table_id: str, column: str, n: int,
    ) -> set[str]:
        """Return an empty set — no sampling performed.

        ``table_id`` / ``column`` / ``n`` are accepted for Protocol
        compatibility; unused.
        """
        del table_id, column, n  # documentation-only
        return set()

    async def estimate_table_size(self, table_id: str) -> int:
        """Return 0 — no size estimation performed.

        Strategy's max_table_size pre-filter is satisfied (0 < any cap)
        but the per-column sample is empty so no edges propose.
        """
        del table_id
        return 0
