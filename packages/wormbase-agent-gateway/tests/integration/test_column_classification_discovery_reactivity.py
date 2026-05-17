"""L6 Sub-wave B — Compounding-factory integration tests.

Pins the L6 column-classification axis end-to-end through a real
``ReactivityRegistry`` + ``ReactivityRunner`` + ``InMemoryLedger``:

  * Default args (None / None) preserve byte-identical pre-L6
    behaviour: factory builds, registers, but emits no proposals.
  * Optional-Effect Injection case 13: each slot independently None
    short-circuits to no-op.
  * Fires per-column on ``external_catalog_imported`` with table state.
  * Quality filter: missing ``source_id`` → no fire.
  * Cross-axis: SemanticTypeClassificationStrategy reads via the
    injected ConfirmedSemanticTypeReader (the new cross-axis Protocol).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_agent_gateway.column_classification import (
    ConfirmedSemanticTypeRecord,
    NamingPatternClassificationStrategy,
    SemanticTypeClassificationStrategy,
    make_composite_column_classification_service,
)
from wormbase_agent_gateway.reactivities import (
    make_column_classification_discovery_reactivity,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a006b")


class _FakeCatalogReader:
    """Test double for the L3 :class:`_CatalogReader` Protocol.

    L6 only consumes :meth:`list_tables_for_source`; the
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


class _FakeSemanticTypeReader:
    """Test double for the new L6-owned cross-axis Protocol."""

    def __init__(
        self,
        types: dict[
            tuple[str, str], list[ConfirmedSemanticTypeRecord],
        ] | None = None,
    ) -> None:
        self.types = types or {}
        self.calls: list[tuple[str, str, UUID]] = []

    async def list_confirmed_types_for_table_column(
        self, *, table_id, column, company_id,
    ):
        self.calls.append((table_id, column, company_id))
        return self.types.get((table_id, column), [])


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


def _fetch_column_classification_proposed(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return execute rows for the ``column_classification_proposed`` cycle."""
    return [
        r for r in rows
        if r["kind"] == "execute"
        and (r.get("payload") or {}).get("tool")
        == "emit_column_classification_proposed"
    ]


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot (case 13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_args_preserve_pre_l6_byte_identity() -> None:
    """``classification_service=None`` AND ``catalog_reader=None`` (defaults)
    → no ``column_classification_proposed`` entries emitted on triggers.

    Pin: Sub-wave B must preserve byte-identical pre-L6 behaviour for
    all callers that have not yet wired the service in (Optional-Effect
    Injection contract case 13).
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_column_classification_discovery_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-001",
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_column_classification_proposed(rows) == [], (
        "default factory args MUST preserve byte-identical pre-L6 "
        "behaviour (no column_classification_proposed without a "
        "service+reader)"
    )


@pytest.mark.asyncio
async def test_catalog_reader_none_is_no_op() -> None:
    """``catalog_reader=None`` with wired service → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    service = make_composite_column_classification_service(
        naming_pattern=NamingPatternClassificationStrategy(),
    )
    registry.register(
        make_column_classification_discovery_reactivity(
            classification_service=service,
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
    assert _fetch_column_classification_proposed(rows) == []


@pytest.mark.asyncio
async def test_classification_service_none_is_no_op() -> None:
    """``classification_service=None`` with wired reader → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    reader = _FakeCatalogReader(sources={
        "src-001": [_table_dict("src-001.public.users", ["user_ssn"])],
    })
    registry.register(
        make_column_classification_discovery_reactivity(
            classification_service=None,
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
    assert _fetch_column_classification_proposed(rows) == []


# ---------------------------------------------------------------------------
# Fire path — external_catalog_imported with productive columns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_catalog_imported_fires_per_productive_column() -> None:
    """Snapshot with productive column names → 1+ PEVR cycle per column-level
    via the naming_pattern strategy (independent of L5)."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    catalog = _FakeCatalogReader(sources={
        "src-001": [
            _table_dict(
                "src-001.public.users",
                ["user_ssn", "user_api_key", "noise_xyz"],
            ),
        ],
    })
    service = make_composite_column_classification_service(
        naming_pattern=NamingPatternClassificationStrategy(),
    )

    registry.register(
        make_column_classification_discovery_reactivity(
            classification_service=service,
            catalog_reader=catalog,
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
    proposed = _fetch_column_classification_proposed(rows)
    # user_ssn → regulated; api_key (matches *_api_key) → confidential;
    # noise_xyz → no proposal.
    assert len(proposed) >= 2
    levels = {
        (p["payload"] or {}).get("args", {}).get("classification_level")
        for p in proposed
    }
    assert "regulated" in levels
    assert "confidential" in levels
    # The reader was reached
    assert ("source", "src-001") in catalog.calls


@pytest.mark.asyncio
async def test_proposal_payload_carries_all_required_fields() -> None:
    """Each emitted proposal carries the canonical payload field set."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    catalog = _FakeCatalogReader(sources={
        "src-001": [_table_dict("src-001.public.users", ["user_ssn"])],
    })
    service = make_composite_column_classification_service(
        naming_pattern=NamingPatternClassificationStrategy(),
    )
    registry.register(
        make_column_classification_discovery_reactivity(
            classification_service=service,
            catalog_reader=catalog,
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
    proposed = _fetch_column_classification_proposed(rows)
    assert len(proposed) >= 1
    args = (proposed[0]["payload"] or {}).get("args") or {}
    # The 9 payload fields
    expected_keys = {
        "classification_id", "table_id", "column", "classification_level",
        "upstream_semantic_type_id", "confidence", "strategy",
        "reasoning", "evidence",
    }
    assert expected_keys.issubset(set(args.keys()))


@pytest.mark.asyncio
async def test_cross_axis_chain_to_l5_propagates_upstream_id() -> None:
    """SemanticTypeClassificationStrategy reads L5 → upstream id propagates
    onto :attr:`ProposedColumnClassification.upstream_semantic_type_id`.

    Pin: the cross-axis chain works end-to-end. The new
    :class:`ConfirmedSemanticTypeReader` Protocol is injected into the
    strategy at construction time and the strategy returns proposals
    with ``upstream_semantic_type_id`` set so the /lake/column-
    classification surface can render the "view L5 semantic type →"
    link.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    catalog = _FakeCatalogReader(sources={
        "src-001": [_table_dict("src-001.public.users", ["card_number"])],
    })
    semantic_reader = _FakeSemanticTypeReader(types={
        ("src-001.public.users", "card_number"): [
            ConfirmedSemanticTypeRecord(
                type_id="l5-cc-id",
                semantic_type="pii_credit_card",
                confidence=0.95,
                strategy="value_pattern",
            ),
        ],
    })
    service = make_composite_column_classification_service(
        semantic_type=SemanticTypeClassificationStrategy(
            semantic_type_reader=semantic_reader,
        ),
    )

    registry.register(
        make_column_classification_discovery_reactivity(
            classification_service=service,
            catalog_reader=catalog,
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
    proposed = _fetch_column_classification_proposed(rows)
    assert len(proposed) >= 1
    # The semantic_type strategy got called — cross-axis read fired.
    assert any(
        (c[0], c[1]) == ("src-001.public.users", "card_number")
        for c in semantic_reader.calls
    )
    # And the upstream id propagated into the ledger entry.
    args = (proposed[0]["payload"] or {}).get("args") or {}
    assert args.get("upstream_semantic_type_id") == "l5-cc-id"
    assert args.get("classification_level") == "regulated"
    assert args.get("strategy") == "semantic_type"


@pytest.mark.asyncio
async def test_no_proposals_when_no_tables() -> None:
    """No tables for the source → no proposals."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    catalog = _FakeCatalogReader(sources={})  # empty
    service = make_composite_column_classification_service(
        naming_pattern=NamingPatternClassificationStrategy(),
    )
    registry.register(
        make_column_classification_discovery_reactivity(
            classification_service=service,
            catalog_reader=catalog,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="src-empty",
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_column_classification_proposed(rows) == []
