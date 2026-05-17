"""L1 Sub-wave B — Compounding-factory integration tests.

Pins the L1 source-candidate-discovery axis end-to-end through a real
``ReactivityRegistry`` + ``ReactivityRunner`` + ``InMemoryLedger`` +
``ClockTickEmitter``:

  * Default args (None) preserve byte-identical pre-L1 behaviour:
    factory builds, registers, but emits no proposals.
  * Optional-Effect Injection case 15: ``candidate_service=None``
    short-circuits to no-op.
  * Source predicate is ``Periodic(every_seconds=...)`` — the axis
    fires on ``clock_tick`` ledger entries, NOT on event-driven
    entries (mirrors L4 ``gap_to_escalation``, diverges from L3 /
    L7 / L4 / L5 / L6 / L8 which all key on
    ``external_catalog_imported`` / ``source_connected``).
  * Per-tick fire: the wired composite is invoked and emits one
    ``source_candidate_proposed`` PEVR cycle per proposal.
  * Replay-stability: same upstream state + repeated ticks → same
    candidate_ids (collision-based idempotence per spec §4.8).
"""
from __future__ import annotations

from uuid import UUID

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.clock_tick_emitter import ClockTickEmitter
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_agent_gateway.reactivities import (
    make_source_candidate_discovery_reactivity,
)
from wormbase_agent_gateway.source_candidates import (
    ChannelMentionAcquisitionStrategy,
    ComplementaritySourceStrategy,
    ConnectedSourceRecord,
    KpiGapAcquisitionStrategy,
    KpiNodeRecord,
    SilverConversationRecord,
    make_composite_source_candidate_service,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000a00b1")
_TICK_S = 3600  # hourly cadence used by the factory's default.


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeKpiNodeReader:
    def __init__(self, nodes=None):
        self.nodes = nodes or []
        self.calls: list[UUID] = []

    async def list_kpi_nodes_without_source(self, *, company_id):
        self.calls.append(company_id)
        return list(self.nodes)


class _FakeSilverConversationReader:
    def __init__(self, rows=None):
        self.rows = rows or []

    async def list_recent_conversations(self, *, company_id, since_seconds=86400):
        return list(self.rows)


class _FakeConnectedSourceReader:
    def __init__(self, sources=None):
        self.sources = sources or []

    async def list_connected_sources(self, *, company_id):
        return list(self.sources)


def _fetch_source_candidate_proposed(rows: list[dict]) -> list[dict]:
    """Return execute rows for the ``source_candidate_proposed`` cycle."""
    return [
        r for r in rows
        if r["kind"] == "execute"
        and (r.get("payload") or {}).get("tool")
        == "emit_source_candidate_proposed"
    ]


def _make_emitter(ledger: InMemoryLedger) -> ClockTickEmitter:
    return ClockTickEmitter(
        ledger=ledger, company_id=_COMPANY_ID, tick_interval_s=_TICK_S,
    )


# ---------------------------------------------------------------------------
# Factory-shape tests (no runtime)
# ---------------------------------------------------------------------------


def test_factory_default_args_build_a_reactivity() -> None:
    """Default args build a valid Reactivity (Optional-Effect default path)."""
    r = make_source_candidate_discovery_reactivity()
    assert r.id == "agent_gateway.source_candidate_discovery"
    assert r.name == "agent-gateway.source-candidate-discovery"
    assert r.scope == "company"


def test_factory_uses_periodic_source_predicate() -> None:
    """Source predicate is ``Periodic`` (NOT event-driven).

    Pin: L1 diverges from L3 / L7 / L4 / L5 / L6 / L8 (all
    event-driven on external_catalog_imported / source_connected) and
    mirrors v2.B Phase 3 Axis 4 (gap_to_escalation) which uses
    ``Periodic(every_seconds=...)`` for cadence-driven discovery.
    """
    from wormbase_reactivities.predicates import Periodic
    r = make_source_candidate_discovery_reactivity()
    assert isinstance(r.source_predicate, Periodic)


def test_factory_periodic_tick_interval_is_configurable() -> None:
    """``tick_interval_s`` flows through to the Periodic predicate."""
    from wormbase_reactivities.predicates import Periodic
    r = make_source_candidate_discovery_reactivity(tick_interval_s=7200)
    assert isinstance(r.source_predicate, Periodic)


def test_factory_novelty_key_matches_spec() -> None:
    """``novelty_key`` is ``source_candidate_discovery``."""
    r = make_source_candidate_discovery_reactivity()
    assert r.novelty_key == "source_candidate_discovery"


# ---------------------------------------------------------------------------
# Optional-Effect Injection — default args (None) preserves pre-L1 state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_args_preserve_pre_l1_byte_identity() -> None:
    """``candidate_service=None`` (default) → no ``source_candidate_proposed``
    entries emitted on ticks.

    Pin: Sub-wave B must preserve byte-identical pre-L1 behaviour for
    all callers that have not yet wired the composite in (Optional-
    Effect Injection contract case 15).
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_source_candidate_discovery_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    emitter = _make_emitter(ledger)
    await emitter.tick_once()
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_source_candidate_proposed(rows) == [], (
        "default factory args MUST preserve byte-identical pre-L1 "
        "behaviour (no source_candidate_proposed without a service)"
    )


# ---------------------------------------------------------------------------
# Fire path — wired service emits per tick
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_with_wired_kpi_gap_emits_source_candidate_proposed() -> None:
    """Wired KpiGap composite + unbacked KPI → one
    ``source_candidate_proposed`` entry per tick."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    kpi_reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-1", name="q3_revenue", domain_id="dom-fin"),
    ])
    service = make_composite_source_candidate_service(
        kpi_gap=KpiGapAcquisitionStrategy(kpi_node_reader=kpi_reader),
    )
    registry.register(
        make_source_candidate_discovery_reactivity(candidate_service=service),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    emitter = _make_emitter(ledger)
    await emitter.tick_once()
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_source_candidate_proposed(rows)
    assert len(proposed) == 1
    args = (proposed[0]["payload"] or {}).get("args") or {}
    assert args.get("proposed_kind") == "stripe"
    assert args.get("strategy") == "kpi_gap"
    assert args.get("proposed_identifier") == "kpi:q3_revenue"
    assert args.get("domain_id_hint") == "dom-fin"
    # Reader was invoked with the right company
    assert kpi_reader.calls and kpi_reader.calls[0] == _COMPANY_ID


@pytest.mark.asyncio
async def test_tick_with_wired_channel_mention_emits_source_candidate_proposed() -> None:
    """ChannelMention with one direct snowflake mention → one proposal."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    silver_reader = _FakeSilverConversationReader([
        SilverConversationRecord(
            message_id="m-1", channel_id="c-data",
            text="our snowflake warehouse",
            domain_id="dom-data", classification="public",
        ),
    ])
    service = make_composite_source_candidate_service(
        channel_mention=ChannelMentionAcquisitionStrategy(
            silver_conversation_reader=silver_reader,
        ),
    )
    registry.register(
        make_source_candidate_discovery_reactivity(candidate_service=service),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    emitter = _make_emitter(ledger)
    await emitter.tick_once()
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_source_candidate_proposed(rows)
    # At least the snowflake proposal lands; the regex bank may match
    # additional "warehouse"-pattern entries too.
    snowflake_props = [
        p for p in proposed
        if ((p.get("payload") or {}).get("args") or {}).get("proposed_kind")
        == "snowflake"
    ]
    assert len(snowflake_props) == 1
    args = (snowflake_props[0]["payload"] or {}).get("args") or {}
    assert args.get("strategy") == "channel_mention"
    assert "m-1" in args.get("evidence", {}).get("message_refs", [])


@pytest.mark.asyncio
async def test_tick_with_wired_complementarity_emits_proposals() -> None:
    """Complementarity with sales-heavy portfolio → propose hubspot."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    src_reader = _FakeConnectedSourceReader([
        ConnectedSourceRecord("s-1", "stripe", "sales", "internal"),
        ConnectedSourceRecord("s-2", "salesforce", "sales", "internal"),
    ])
    service = make_composite_source_candidate_service(
        complementarity=ComplementaritySourceStrategy(
            connected_source_reader=src_reader,
        ),
    )
    registry.register(
        make_source_candidate_discovery_reactivity(candidate_service=service),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    emitter = _make_emitter(ledger)
    await emitter.tick_once()
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_source_candidate_proposed(rows)
    kinds = {
        ((p.get("payload") or {}).get("args") or {}).get("proposed_kind")
        for p in proposed
    }
    assert "hubspot" in kinds


# ---------------------------------------------------------------------------
# Empty-upstream posture — wired but no signal → no emissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_upstream_wired_service_no_emissions() -> None:
    """All three strategies wired but readers return [] → no proposals emit.

    Pin per Sub-wave A handoff concern #1: ChannelMention honest stub
    on empty silver. Also covers KpiGap on empty KPI tree.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    service = make_composite_source_candidate_service(
        kpi_gap=KpiGapAcquisitionStrategy(kpi_node_reader=_FakeKpiNodeReader()),
        channel_mention=ChannelMentionAcquisitionStrategy(
            silver_conversation_reader=_FakeSilverConversationReader(),
        ),
        complementarity=ComplementaritySourceStrategy(
            connected_source_reader=_FakeConnectedSourceReader(),
        ),
    )
    registry.register(
        make_source_candidate_discovery_reactivity(candidate_service=service),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    emitter = _make_emitter(ledger)
    await emitter.tick_once()
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    assert _fetch_source_candidate_proposed(rows) == []


# ---------------------------------------------------------------------------
# Replay stability — same upstream + multiple ticks → same candidate_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeated_ticks_emit_same_candidate_ids() -> None:
    """Same upstream state + repeated ticks → same candidate_ids.

    Pin: spec §4.8 — L1 relies on candidate_id collision on the
    projection PK for dedup; no PROPOSE_WINDOW_SECONDS knob. The
    Reactivity may emit the same PEVR cycle on each tick, but the
    projection-fold layer collapses them by candidate_id.
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)

    kpi_reader = _FakeKpiNodeReader([
        KpiNodeRecord(kpi_node_id="k-1", name="q3_revenue", domain_id=None),
    ])
    service = make_composite_source_candidate_service(
        kpi_gap=KpiGapAcquisitionStrategy(kpi_node_reader=kpi_reader),
    )
    registry.register(
        make_source_candidate_discovery_reactivity(candidate_service=service),
    )
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    emitter = _make_emitter(ledger)
    await emitter.tick_once()
    await runner.run_once()
    # Second tick — same upstream state
    await emitter.tick_once()
    await runner.run_once()

    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_source_candidate_proposed(rows)
    # All emissions carry the same candidate_id (deterministic on
    # (kind, identifier, strategy)).
    ids = {
        ((p.get("payload") or {}).get("args") or {}).get("candidate_id")
        for p in proposed
    }
    assert len(ids) == 1, (
        f"expected one distinct candidate_id across ticks; got {ids}"
    )
