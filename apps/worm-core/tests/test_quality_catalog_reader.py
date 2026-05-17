"""L7 Sub-wave C — LedgerDbtTestReader + NoopHistoricalStatsReader tests.

Pins the production DbtTestReader behaviour against the
``external_lineage_imported`` ledger entries emitted by the
wormbase-catalog-mirror Reactivity. Until the catalog mirror grows
a ``tests`` arg-key on those entries (future wave), the reader
returns ``[]`` — honest-stub posture, identical to the L3
LedgerDbtManifestReader pattern.

NoopHistoricalStatsReader is exercised structurally — it always
returns ``[]`` so the HistoricalStatsStrategy short-circuits.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from wormbase_ledger import InMemoryLedger

from wormbase_core.quality_catalog_reader import (
    LedgerDbtTestReader,
    NoopHistoricalStatsReader,
)


_COMPANY_A = UUID("00000000-0000-0000-0000-0000000c0001")
_COMPANY_B = UUID("00000000-0000-0000-0000-0000000c0002")


async def _emit_external_lineage_imported(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
    edges: list[tuple[str, str]] | None = None,
    tests: Any = None,
) -> None:
    """Drive a minimal ``external_lineage_imported`` PEVR cycle.

    ``tests`` is the future-compat optional arg the catalog mirror may
    eventually emit. When None we omit it so the entry mirrors today's
    catalog-mirror grammar exactly.
    """
    args: dict[str, Any] = {
        "source_id": source_id,
        "edges": list(edges or []),
    }
    if tests is not None:
        args["tests"] = tests
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "external_lineage_imported",
            "ref_id": source_id,
            "reason": "test seed",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_external_lineage_imported",
            "args": args,
            "result_ref": source_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


async def test_dbt_test_reader_empty_when_no_entries() -> None:
    """No ``external_lineage_imported`` entries → empty test list."""
    ledger = InMemoryLedger()
    reader = LedgerDbtTestReader(ledger=ledger, company_id=_COMPANY_A)
    tests = await reader.get_tests_for_model("model.sales.orders")
    assert tests == []


async def test_dbt_test_reader_today_grammar_returns_empty() -> None:
    """Wave-1 catalog mirror today doesn't emit a ``tests`` key → empty."""
    ledger = InMemoryLedger()
    # Emit a current-grammar entry — edges only, no ``tests`` arg.
    await _emit_external_lineage_imported(
        ledger,
        company_id=_COMPANY_A,
        source_id="dbt-1",
        edges=[("model.sales.raw_orders", "model.sales.orders")],
    )
    reader = LedgerDbtTestReader(ledger=ledger, company_id=_COMPANY_A)
    tests = await reader.get_tests_for_model("model.sales.orders")
    # Honest stub: no ``tests`` arg on the entry → empty list.
    assert tests == []


async def test_dbt_test_reader_picks_up_future_dict_shape() -> None:
    """Future-compat: a ``tests`` arg keyed by model → tests surface."""
    ledger = InMemoryLedger()
    future_tests = {
        "model.sales.orders": [
            {"test_name": "not_null", "column": "order_id"},
            {"test_name": "unique", "column": "order_id"},
        ],
    }
    await _emit_external_lineage_imported(
        ledger,
        company_id=_COMPANY_A,
        source_id="dbt-1",
        edges=[],
        tests=future_tests,
    )
    reader = LedgerDbtTestReader(ledger=ledger, company_id=_COMPANY_A)
    tests = await reader.get_tests_for_model("model.sales.orders")
    assert len(tests) == 2
    assert tests[0]["test_name"] == "not_null"
    assert tests[0]["column"] == "order_id"
    assert tests[1]["test_name"] == "unique"


async def test_dbt_test_reader_picks_up_future_list_shape() -> None:
    """Future-compat: a flat ``tests`` list with per-entry model key."""
    ledger = InMemoryLedger()
    future_tests = [
        {
            "model": "model.sales.orders",
            "test_name": "accepted_values",
            "column": "status",
            "config": {"values": ["paid", "pending", "refunded"]},
        },
        {
            "model": "model.other.users",
            "test_name": "not_null",
            "column": "id",
        },
    ]
    await _emit_external_lineage_imported(
        ledger,
        company_id=_COMPANY_A,
        source_id="dbt-1",
        edges=[],
        tests=future_tests,
    )
    reader = LedgerDbtTestReader(ledger=ledger, company_id=_COMPANY_A)
    # Only the entry whose ``model`` matches surfaces.
    tests = await reader.get_tests_for_model("model.sales.orders")
    assert len(tests) == 1
    assert tests[0]["test_name"] == "accepted_values"
    assert tests[0]["config"]["values"] == ["paid", "pending", "refunded"]


async def test_dbt_test_reader_tenant_isolation() -> None:
    """Tests from tenant B never leak into tenant A's reader."""
    ledger = InMemoryLedger()
    # Tenant B has the only ``tests`` payload.
    future_tests = {
        "model.sales.orders": [{"test_name": "not_null", "column": "id"}],
    }
    await _emit_external_lineage_imported(
        ledger,
        company_id=_COMPANY_B,
        source_id="dbt-b",
        edges=[],
        tests=future_tests,
    )
    # Tenant A's reader should not see any tests.
    reader_a = LedgerDbtTestReader(ledger=ledger, company_id=_COMPANY_A)
    tests = await reader_a.get_tests_for_model("model.sales.orders")
    assert tests == []
    # Tenant B's reader does see them.
    reader_b = LedgerDbtTestReader(ledger=ledger, company_id=_COMPANY_B)
    tests = await reader_b.get_tests_for_model("model.sales.orders")
    assert len(tests) == 1


async def test_noop_historical_stats_reader_returns_empty() -> None:
    """The honest-stub HistoricalStatsReader always returns empty snapshots."""
    reader = NoopHistoricalStatsReader()
    snapshots = await reader.get_snapshots_for_table("any.table.id")
    assert snapshots == []
