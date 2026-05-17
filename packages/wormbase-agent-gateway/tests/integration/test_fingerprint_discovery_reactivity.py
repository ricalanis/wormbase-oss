"""L5 Sub-wave B — Compounding-factory integration tests.

Pins the L5 semantic-type fingerprinting axis end-to-end through a real
``ReactivityRegistry`` + ``ReactivityRunner`` + ``InMemoryLedger``:

  * Default args (None / None) preserve byte-identical pre-L5
    behaviour: factory builds, registers, but emits no proposals.
  * Optional-Effect Injection case 12: each slot independently None
    short-circuits to no-op.
  * Fires per-column on ``external_catalog_imported`` with table state.
  * Quality filter: missing ``source_id`` → no fire.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_agent_gateway.reactivities import (
    make_fingerprint_discovery_reactivity,
)
from wormbase_agent_gateway.semantic_type import (
    ColumnNameFingerprintStrategy,
    make_composite_semantic_type_service,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a005a")


class _FakeCatalogReader:
    """Test double for the L3 :class:`_CatalogReader` Protocol.

    L5 only consumes :meth:`list_tables_for_source`; the
    :meth:`list_candidate_targets` shim is provided for Protocol shape.
    """

    def __init__(self, sources: dict[str, list[Any]] | None = None) -> None:
        self.sources = sources or {}
        self.calls: list[tuple[str, str]] = []

    async def list_tables_for_source(
        self, *, company_id: UUID, source_id: str,
    ) -> list[Any]:
        self.calls.append(("source", source_id))
        return self.sources.get(source_id, [])

    async def list_candidate_targets(
        self, *, company_id: UUID, source_id: str,
    ) -> list[Any]:
        self.calls.append(("candidates", source_id))
        return self.sources.get(source_id, [])


def _table_dict(table_id: str, columns: list[str]) -> dict[str, Any]:
    """Helper — build a CatalogTable-shaped dict."""
    return {"table_id": table_id, "columns": columns}


async def _write_external_catalog_imported(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
    source_kind: str = "dbt",
) -> None:
    """Drive a canonical ``external_catalog_imported`` PEVR cycle."""
    args: dict[str, Any] = {
        "source_id": source_id,
        "source_kind": source_kind,
        "snapshot_hash": "test-hash",
        "table_count": 1,
        "edge_count": 0,
        "metric_count": 0,
        "import_mode": "initial",
        "domain_id": str(uuid4()),
    }
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "external_catalog_imported",
            "source_id": source_id,
            "ref_id": source_id,
            "reason": "test external_catalog_imported",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_external_catalog_imported",
            "args": args,
            "result_ref": source_id,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "external_catalog_imported", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "test external_catalog_imported",
        },
        quadrant="active_deterministic",
    )


def _fetch_semantic_type_proposed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return execute rows for the ``semantic_type_proposed`` cycle."""
    return [
        r for r in rows
        if r["kind"] == "execute"
        and (r.get("payload") or {}).get("tool") == "emit_semantic_type_proposed"
    ]


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_args_preserve_pre_l5_byte_identity() -> None:
    """``fingerprint_service=None`` AND ``catalog_reader=None`` (defaults)
    → no ``semantic_type_proposed`` entries emitted even on triggers."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_fingerprint_discovery_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_semantic_type_proposed(rows) == [], (
        "default factory args MUST preserve byte-identical pre-L5 behaviour "
        "(no semantic_type_proposed without a service+reader)"
    )


@pytest.mark.asyncio
async def test_catalog_reader_none_is_no_op() -> None:
    """``catalog_reader=None`` with wired service → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    service = make_composite_semantic_type_service(
        column_name=ColumnNameFingerprintStrategy(),
    )
    registry.register(
        make_fingerprint_discovery_reactivity(
            fingerprint_service=service,
            catalog_reader=None,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_semantic_type_proposed(rows) == []


@pytest.mark.asyncio
async def test_fingerprint_service_none_is_no_op() -> None:
    """``fingerprint_service=None`` with wired reader → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    reader = _FakeCatalogReader(sources={
        "src-001": [_table_dict("src-001.public.users", ["email"])],
    })
    registry.register(
        make_fingerprint_discovery_reactivity(
            fingerprint_service=None,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_semantic_type_proposed(rows) == []


# ---------------------------------------------------------------------------
# Fire path — external_catalog_imported with productive columns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_catalog_imported_fires_per_productive_column() -> None:
    """Snapshot with productive column names → 1 PEVR cycle per column-type."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    reader = _FakeCatalogReader(sources={
        "src-001": [
            _table_dict(
                "src-001.public.users",
                ["email", "first_name", "noise_xyz"],
            ),
        ],
    })
    service = make_composite_semantic_type_service(
        column_name=ColumnNameFingerprintStrategy(),
    )

    registry.register(
        make_fingerprint_discovery_reactivity(
            fingerprint_service=service,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_semantic_type_proposed(rows)
    # email → email; first_name → pii_name; noise_xyz → no proposal.
    assert len(proposed) >= 2
    semantic_types = {
        (p["payload"] or {}).get("args", {}).get("semantic_type")
        for p in proposed
    }
    assert "email" in semantic_types
    assert "pii_name" in semantic_types
    # The reader was reached
    assert ("source", "src-001") in reader.calls


@pytest.mark.asyncio
async def test_proposal_payload_carries_all_required_fields() -> None:
    """Each emitted proposal carries the canonical payload field set."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    reader = _FakeCatalogReader(sources={
        "src-001": [_table_dict("src-001.public.users", ["email"])],
    })
    service = make_composite_semantic_type_service(
        column_name=ColumnNameFingerprintStrategy(),
    )
    registry.register(
        make_fingerprint_discovery_reactivity(
            fingerprint_service=service,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_semantic_type_proposed(rows)
    assert proposed
    args = (proposed[0]["payload"] or {}).get("args") or {}
    for field in (
        "type_id", "table_id", "column", "semantic_type",
        "confidence", "strategy", "reasoning", "evidence",
    ):
        assert field in args, f"missing payload field {field!r}"
    assert args["table_id"] == "src-001.public.users"
    assert args["column"] == "email"
    assert args["semantic_type"] == "email"
    assert args["strategy"] == "column_name"


# ---------------------------------------------------------------------------
# Empty catalog + idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_catalog_means_no_fire() -> None:
    """Catalog reader returns no tables → no proposals (degrades gracefully)."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    reader = _FakeCatalogReader(sources={"src-001": []})
    service = make_composite_semantic_type_service(
        column_name=ColumnNameFingerprintStrategy(),
    )
    registry.register(
        make_fingerprint_discovery_reactivity(
            fingerprint_service=service,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_semantic_type_proposed(rows) == []
    # Reader IS reached
    assert ("source", "src-001") in reader.calls


@pytest.mark.asyncio
async def test_idempotency_filter_suppresses_recent_re_propose() -> None:
    """A second trigger for the same (table, column) within the propose
    window → idempotency_filter short-circuits."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    reader = _FakeCatalogReader(sources={
        "src-001": [_table_dict("src-001.public.users", ["email"])],
    })
    service = make_composite_semantic_type_service(
        column_name=ColumnNameFingerprintStrategy(),
    )

    registry.register(
        make_fingerprint_discovery_reactivity(
            fingerprint_service=service,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )
    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()
    first = _fetch_semantic_type_proposed(await ledger.fetch(_COMPANY_ID))
    assert len(first) == 1

    # Fresh registry bypasses NotRecentlyFired; idempotency_filter is the
    # remaining short-circuit.
    fresh_registry = ReactivityRegistry(
        ledger=ledger, company_id=_COMPANY_ID,
    )
    fresh_registry.register(
        make_fingerprint_discovery_reactivity(
            fingerprint_service=service,
            catalog_reader=reader,
        ),
    )
    fresh_runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=fresh_registry,
        poll_interval_s=0.01,
    )
    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await fresh_runner.run_once()
    second = _fetch_semantic_type_proposed(await ledger.fetch(_COMPANY_ID))
    assert len(second) == 1, (
        f"idempotency_filter failed: expected 1 semantic_type_proposed "
        f"after re-trigger within window, got {len(second)}"
    )
