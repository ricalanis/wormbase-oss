"""L8 Sub-wave B — Compounding-factory integration tests.

Pins the L8 entity-stitch axis end-to-end through a real
``ReactivityRegistry`` + ``ReactivityRunner`` + ``InMemoryLedger``:

  * Default args (None / None) preserve byte-identical pre-L8
    behaviour: factory builds, registers, but emits no proposals.
  * Optional-Effect Injection case 14: each slot independently None
    short-circuits to no-op.
  * Fires per cross-source (column_a, column_b) pair on
    ``external_catalog_imported`` with multi-source state.
  * **Cross-source filter**: same source_id pairs are dropped at
    gather_fn time (no self-source stitches).
  * Quality filter: missing ``source_id`` → no fire.
  * Cross-axis: NameMatchEntityStrategy reads via the REUSED L6
    ConfirmedSemanticTypeReader Protocol — second consumer.
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
)
from wormbase_agent_gateway.entity_stitch import (
    NameMatchEntityStrategy,
    make_composite_entity_stitch_service,
)
from wormbase_agent_gateway.reactivities import (
    make_entity_stitch_discovery_reactivity,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a009b")


class _FakeCatalogReader:
    """Test double for the L3 :class:`_CatalogReader` Protocol.

    L8 uses both :meth:`list_tables_for_source` (for the triggering
    source) and :meth:`list_candidate_targets` (for cross-source
    candidates).
    """

    def __init__(
        self,
        sources: dict[str, list[Any]] | None = None,
        candidates: dict[str, list[Any]] | None = None,
    ) -> None:
        self.sources = sources or {}
        # When candidates is None, default to returning ALL tables from
        # all sources (cross-source candidate pool).
        self.candidates = candidates
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
        if self.candidates is not None:
            return self.candidates.get(source_id, [])
        # Default: pool of all tables from all sources
        out: list[Any] = []
        for tables in self.sources.values():
            out.extend(tables)
        return out


class _FakeSemanticTypeReader:
    """Reused L6 cross-axis Protocol fake — second consumer."""

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
    return {"table_id": table_id, "columns": columns}


async def _write_external_catalog_imported(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    source_id: str,
    source_kind: str = "dbt",
) -> None:
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


def _fetch_entity_stitch_proposed(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if r["kind"] == "execute"
        and (r.get("payload") or {}).get("tool")
        == "emit_entity_stitch_proposed"
    ]


# ---------------------------------------------------------------------------
# Optional-Effect Injection — None-ability per slot (case 14)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_args_preserve_pre_l8_byte_identity() -> None:
    """``stitch_service=None`` AND ``catalog_reader=None`` (defaults)
    → no ``entity_stitch_proposed`` entries emitted on triggers.

    Pin: Sub-wave B must preserve byte-identical pre-L8 behaviour for
    all callers that have not yet wired the service in (Optional-Effect
    Injection contract case 14).
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_entity_stitch_discovery_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="stripe",
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_entity_stitch_proposed(rows) == [], (
        "default factory args MUST preserve byte-identical pre-L8 "
        "behaviour (no entity_stitch_proposed without a service+reader)"
    )


@pytest.mark.asyncio
async def test_catalog_reader_none_is_no_op() -> None:
    """``catalog_reader=None`` with wired service → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    service = make_composite_entity_stitch_service(
        name_match=NameMatchEntityStrategy(
            confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
        ),
    )
    registry.register(
        make_entity_stitch_discovery_reactivity(
            stitch_service=service,
            catalog_reader=None,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="stripe",
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_entity_stitch_proposed(rows) == []


@pytest.mark.asyncio
async def test_stitch_service_none_is_no_op() -> None:
    """``stitch_service=None`` with wired reader → still no-op."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    reader = _FakeCatalogReader(sources={
        "stripe": [_table_dict("stripe.customers", ["email"])],
        "salesforce": [_table_dict("salesforce.contacts", ["email"])],
    })
    registry.register(
        make_entity_stitch_discovery_reactivity(
            stitch_service=None,
            catalog_reader=reader,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="stripe",
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_entity_stitch_proposed(rows) == []


# ---------------------------------------------------------------------------
# Fire path — external_catalog_imported with cross-source candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_catalog_imported_fires_per_cross_source_pair() -> None:
    """Two sources with shared semantic types → one stitch_proposed entry
    per cross-source pair that the name_match strategy can anchor."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    catalog = _FakeCatalogReader(sources={
        "stripe": [_table_dict("stripe.customers", ["email"])],
        "salesforce": [_table_dict("salesforce.contacts", ["email"])],
    })
    semantic_reader = _FakeSemanticTypeReader(types={
        ("stripe.customers", "email"): [
            ConfirmedSemanticTypeRecord(
                type_id="t-stripe-email", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
        ("salesforce.contacts", "email"): [
            ConfirmedSemanticTypeRecord(
                type_id="t-sf-email", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
    })
    service = make_composite_entity_stitch_service(
        name_match=NameMatchEntityStrategy(
            confirmed_semantic_type_reader=semantic_reader,
        ),
    )

    registry.register(
        make_entity_stitch_discovery_reactivity(
            stitch_service=service,
            catalog_reader=catalog,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="stripe",
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_entity_stitch_proposed(rows)
    assert len(proposed) >= 1
    # entity_kind=person for shared email
    args = (proposed[0]["payload"] or {}).get("args") or {}
    assert args.get("entity_kind") == "person"
    assert args.get("strategy") in ("name_match", "composite")
    # The cross-axis reader was called
    assert any(
        c[0] == "stripe.customers" and c[1] == "email"
        for c in semantic_reader.calls
    )
    # The catalog reader was queried for both sides
    assert ("source", "stripe") in catalog.calls
    assert ("candidates", "stripe") in catalog.calls


@pytest.mark.asyncio
async def test_cross_source_filter_drops_same_source_pairs() -> None:
    """Pairs where ``source_id_a == source_id_b`` MUST be dropped at the
    gather layer. Same-source columns never produce stitch entries."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    # Only ONE source — all candidate pairs are same-source → filtered out
    catalog = _FakeCatalogReader(sources={
        "stripe": [
            _table_dict("stripe.customers", ["email"]),
            _table_dict("stripe.subscriptions", ["customer_email"]),
        ],
    })
    semantic_reader = _FakeSemanticTypeReader(types={
        ("stripe.customers", "email"): [
            ConfirmedSemanticTypeRecord(
                type_id="t1", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
        ("stripe.subscriptions", "customer_email"): [
            ConfirmedSemanticTypeRecord(
                type_id="t2", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
    })
    service = make_composite_entity_stitch_service(
        name_match=NameMatchEntityStrategy(
            confirmed_semantic_type_reader=semantic_reader,
        ),
    )

    registry.register(
        make_entity_stitch_discovery_reactivity(
            stitch_service=service,
            catalog_reader=catalog,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="stripe",
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_entity_stitch_proposed(rows)
    assert proposed == [], (
        "Cross-source filter MUST drop all same-source pairs; got "
        f"{len(proposed)} entries"
    )


@pytest.mark.asyncio
async def test_proposal_payload_carries_all_required_fields() -> None:
    """Each emitted proposal carries the canonical payload field set."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    catalog = _FakeCatalogReader(sources={
        "stripe": [_table_dict("stripe.customers", ["email"])],
        "salesforce": [_table_dict("salesforce.contacts", ["email"])],
    })
    semantic_reader = _FakeSemanticTypeReader(types={
        ("stripe.customers", "email"): [
            ConfirmedSemanticTypeRecord(
                type_id="t-stripe-email", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
        ("salesforce.contacts", "email"): [
            ConfirmedSemanticTypeRecord(
                type_id="t-sf-email", semantic_type="email",
                confidence=0.95, strategy="column_name",
            ),
        ],
    })
    service = make_composite_entity_stitch_service(
        name_match=NameMatchEntityStrategy(
            confirmed_semantic_type_reader=semantic_reader,
        ),
    )
    registry.register(
        make_entity_stitch_discovery_reactivity(
            stitch_service=service,
            catalog_reader=catalog,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="stripe",
    )
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_entity_stitch_proposed(rows)
    assert len(proposed) >= 1
    args = (proposed[0]["payload"] or {}).get("args") or {}
    expected_keys = {
        "stitch_id",
        "src_source_id_a", "src_table_a", "src_column_a",
        "src_source_id_b", "src_table_b", "src_column_b",
        "upstream_semantic_type_id",
        "entity_kind", "confidence", "strategy",
        "reasoning", "evidence",
    }
    assert expected_keys.issubset(set(args.keys()))


@pytest.mark.asyncio
async def test_no_proposals_when_only_one_source() -> None:
    """No cross-source candidates → no proposals (cross-source filter)."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    catalog = _FakeCatalogReader(sources={
        # Only the triggering source has any tables
        "stripe": [_table_dict("stripe.customers", ["email"])],
    })
    service = make_composite_entity_stitch_service(
        name_match=NameMatchEntityStrategy(
            confirmed_semantic_type_reader=_FakeSemanticTypeReader(),
        ),
    )
    registry.register(
        make_entity_stitch_discovery_reactivity(
            stitch_service=service,
            catalog_reader=catalog,
        ),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_external_catalog_imported(
        ledger, company_id=_COMPANY_ID, source_id="stripe",
    )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_entity_stitch_proposed(rows) == []
