"""L7 Sub-wave C — production DbtTestReader + HistoricalStatsReader for quality discovery.

Sub-wave B introduced :class:`DbtTestReader` and
:class:`HistoricalStatsReader` Protocols on the
:class:`DbtTestsStrategy` / :class:`HistoricalStatsStrategy` slots in
``wormbase-agent-gateway``. This module ships the production-impls that
the boot wire constructs in
``agent_gateway_construction.compose_quality_reactivity_if_enabled``.

:class:`LedgerDbtTestReader` walks ``external_lineage_imported`` ledger
entries emitted by ``wormbase-catalog-mirror``'s catalog snapshot
Reactivity. The Wave 1 catalog mirror carries dbt model metadata on
those entries; this reader lifts the per-model test descriptors. The
five mapped test types — ``not_null``, ``unique``, ``accepted_values``,
``dbt_utils.row_count``, ``dbt_utils.test_freshness`` — drive the
:class:`DbtTestsStrategy` proposals (see
:data:`wormbase_agent_gateway.quality.strategies._DBT_TEST_MAP`).

The Wave 1 catalog mirror does NOT currently emit per-model test
arrays on ``external_lineage_imported`` (it carries the
``(upstream, downstream)`` edge tuples only). This reader returns
``[]`` for every ``get_tests_for_model`` call until a future wave
grows the catalog mirror to mirror the dbt manifest's ``tests``
array onto a richer payload (e.g. an
``external_dbt_tests_imported`` entry kind, future wave). Until
then, the strategy fires telemetry counters but no checks materialise
— honest-stub posture, identical to the L3
:class:`LedgerDbtManifestReader` shape.

:class:`NoopHistoricalStatsReader` is the production fallback for the
:class:`HistoricalStatsStrategy.reader` slot. It returns empty snapshot
lists — the strategy short-circuits to empty proposal lists. Real
historical-stats reading requires the Wave 1 catalog mirror to emit
column-level statistical snapshots (row_count / latest_timestamp_age /
distinct_values per column) onto a future ``catalog_table_stats_imported``
payload. NoopHistoricalStatsReader keeps the env-knob path honest by
surfacing "no stats history" via empty snapshots rather than crashing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

logger = logging.getLogger("wormbase_core.quality_catalog_reader")

__all__ = [
    "LedgerDbtTestReader",
    "NoopHistoricalStatsReader",
]


class _LedgerFetcher(Protocol):
    """Minimal surface this module needs from a Ledger-like object.

    Matches the shape in
    :class:`wormbase_core.lineage_catalog_reader._LedgerFetcher` —
    a fetch-by-company_id async call returning ledger row dicts.
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
class LedgerDbtTestReader:
    """Reads dbt test descriptors from ``external_lineage_imported`` entries.

    Honest stub for the
    :class:`wormbase_agent_gateway.quality.strategies.DbtTestReader`
    Protocol slot. The Wave 1 catalog mirror does NOT currently mirror
    the dbt manifest's per-model ``tests`` array onto the ledger
    boundary — it carries only the ``(upstream, downstream)`` edge
    tuples on ``external_lineage_imported``. This reader walks those
    entries looking for a ``tests`` arg key (future-compat: a
    catalog-mirror upgrade that emits per-model tests on the same entry
    kind would be picked up automatically).

    Until that wave lands, every call returns ``[]``. The strategy
    still fires its per-table invocation counter so operators can see
    the wiring is live, but no checks materialise.

    Tenant scope is NOT in the Protocol — strategies operate on a
    single ``table.table_id`` and the ledger fetch is scoped by
    ``company_id`` at construction time. We accept a ``company_id``
    constructor arg to keep the read tenant-isolated.

    Returned shape (when the future payload lands) follows the
    Sub-wave B Protocol:

      * ``test_name``: ``"not_null" | "unique" | "accepted_values" |
        "dbt_utils.row_count" | "dbt_utils.test_freshness"``
      * ``column``: column name, or ``None`` for table-grain tests
      * ``config``: per-test dbt config (e.g.
        ``{"values": ["a", "b"]}`` for accepted_values)
    """

    ledger: _LedgerFetcher
    company_id: UUID

    async def get_tests_for_model(
        self, model_id: str,
    ) -> list[dict[str, Any]]:
        """Return dbt test descriptors attached to ``model_id``.

        Walks ``external_lineage_imported`` execute entries for the
        tenant; collects test descriptors from a ``tests`` arg key on
        any entry whose ``models`` arg lists ``model_id`` (or whose
        edges name ``model_id`` as an endpoint when ``tests`` is keyed
        by model).

        Today the Wave 1 catalog mirror does not emit a ``tests`` key
        on ``external_lineage_imported`` entries, so this returns
        ``[]`` for every model. When a future wave grows the catalog
        mirror to mirror dbt manifest tests, this reader picks up the
        richer shape automatically without code change.

        Defensive parsing: unknown / malformed entries are skipped
        silently so a future schema drift does not crash the strategy.
        Deterministic ordering (input ledger order preserved) for
        replay stability.
        """
        entries = await self.ledger.fetch(self.company_id)
        tests: list[dict[str, Any]] = []
        for entry in entries:
            if not _is_emit_tool(entry, "emit_external_lineage_imported"):
                continue
            args = _execute_args(entry)
            # Future-compat: pick up a ``tests`` arg keyed by model_id
            # OR a flat list of test descriptors carrying their own
            # ``model`` field. Both shapes are nascent grammar; until
            # the catalog mirror commits to one, we accept both.
            raw_tests = args.get("tests")
            if isinstance(raw_tests, dict):
                model_tests = raw_tests.get(model_id) or raw_tests.get(
                    str(model_id),
                )
                if isinstance(model_tests, list):
                    for t in model_tests:
                        if isinstance(t, dict) and isinstance(
                            t.get("test_name"), str,
                        ):
                            tests.append(t)
            elif isinstance(raw_tests, list):
                for t in raw_tests:
                    if not isinstance(t, dict):
                        continue
                    if t.get("model") != model_id and t.get(
                        "model_id"
                    ) != model_id:
                        continue
                    if isinstance(t.get("test_name"), str):
                        tests.append(t)
        return tests


class NoopHistoricalStatsReader:
    """Honest stub for the
    :class:`wormbase_agent_gateway.quality.strategies.HistoricalStatsReader`
    Protocol slot.

    Returns empty snapshot lists for every call — the
    :class:`HistoricalStatsStrategy` then short-circuits to empty
    proposal lists (its ``len(snapshots) < min_snapshots`` check
    fires immediately).

    Real historical-stats reading requires the Wave 1 catalog mirror
    to emit column-level statistical snapshots — per-table
    ``row_count``, ``latest_timestamp_age_hours``, per-column
    ``distinct_values`` — on a future ``catalog_table_stats_imported``
    payload (or as an additive blob on ``external_catalog_imported``).
    NoopHistoricalStatsReader keeps the env-knob path honest by
    surfacing "no stats history" via empty snapshots rather than
    crashing.

    Sub-wave C gates the entire strategy behind
    ``WORMBASE_QUALITY_HISTORICAL_STATS_ENABLED=true`` so this
    honest-stub posture is auditable: operators flipping the knob see
    the strategy fire telemetry counters but no checks materialise.
    """

    async def get_snapshots_for_table(
        self, table_id: str,
    ) -> list[dict[str, Any]]:
        """Return historical snapshot blobs for ``table_id`` (newest last).

        Always ``[]`` until a future wave grows the catalog mirror to
        emit column-level stats. ``table_id`` is accepted for Protocol
        compatibility; unused.
        """
        del table_id  # documentation-only
        return []
