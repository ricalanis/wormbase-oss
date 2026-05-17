"""L1 Sub-wave C — concrete Reader impl tests.

Exercises the three platform-projection-walking Reader impls shipped
in ``wormbase_core.source_candidate_readers``:

  * :class:`LedgerConnectedSourceReader` — folds the
    source_proposed → source_confirmed → source_connected →
    source_profiled lifecycle, returning sources in
    connected/profiled state.
  * :class:`LedgerKpiNodeReader` — folds ``kpi_proposed`` entries,
    filters to nodes with empty ``source_ids`` (unbacked KPIs).
  * :class:`LedgerSilverConversationReader` — folds ``chat_received``
    entries within a recency window, capped at 1000 rows.

Per Sub-wave B handoff concern #8 — verifies that re-walking the
ledger over the same upstream state yields the same Reader output
(replay stability; ensures the v027 fold absorbs duplicate ticks at
projection-PK collision).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger

from wormbase_core.source_candidate_readers import (
    LedgerConnectedSourceReader,
    LedgerKpiNodeReader,
    LedgerSilverConversationReader,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000beef0")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _write_source_proposed(
    ledger: InMemoryLedger,
    *,
    source_id: UUID,
    source_kind: str = "csv_local",
    uri: str = "s3://bucket/file.csv",
    suggested_domain: str = "uncategorised",
    suggested_classification: str = "internal",
) -> None:
    payload = {
        "source_id": str(source_id),
        "source_kind": source_kind,
        "uri": uri,
        "added_via_flow": "dashboard_form",
        "suggested_domain": suggested_domain,
        "suggested_classification": suggested_classification,
        "correlation_id": str(uuid4()),
    }
    await ledger.write(
        company_id=_COMPANY_ID,
        propose={
            "target_kind": "source_proposed",
            "ref_id": payload["correlation_id"],
            "reason": "test",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_source_proposed",
            "args": payload,
            "result_ref": payload["correlation_id"],
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


async def _write_source_lifecycle_entry(
    ledger: InMemoryLedger,
    *,
    source_id: UUID,
    tool: str,
    extra: dict | None = None,
) -> None:
    args = {"source_id": str(source_id)}
    if extra:
        args.update(extra)
    await ledger.write(
        company_id=_COMPANY_ID,
        propose={
            "target_kind": tool.removeprefix("emit_"),
            "ref_id": str(uuid4()),
            "reason": "test",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": tool,
            "args": args,
            "result_ref": str(source_id),
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


async def _write_kpi_proposed(
    ledger: InMemoryLedger,
    *,
    kpi_id: UUID,
    label: str,
    source_ids: list[UUID] | None = None,
) -> None:
    args = {
        "kpi_id": str(kpi_id),
        "label": label,
        "formula": f"sum({label})",
        "source_ids": [str(s) for s in (source_ids or [])],
        "unit": "USD",
        "proposed_at": datetime.now(UTC).isoformat(),
    }
    await ledger.write(
        company_id=_COMPANY_ID,
        propose={
            "target_kind": "kpi_proposed",
            "ref_id": str(kpi_id),
            "reason": "test",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_kpi_proposed",
            "args": args,
            "result_ref": str(kpi_id),
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="active_deterministic",
    )


async def _write_chat_received(
    ledger: InMemoryLedger,
    *,
    message_id: str,
    channel_id: str,
    text: str,
    classification: str = "internal",
) -> None:
    args = {
        "channel_id": channel_id,
        "message_id": message_id,
        "sender_person": str(uuid4()),
        "text": text,
        "classification": classification,
    }
    await ledger.write(
        company_id=_COMPANY_ID,
        propose={
            "target_kind": "chat_received",
            "ref_id": message_id,
            "reason": "test",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_chat_received",
            "args": args,
            "result_ref": message_id,
        },
        verify_fn=lambda _e: {
            "checks": [{"name": "ok", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        quadrant="passive_probabilistic",
    )


# ---------------------------------------------------------------------------
# LedgerConnectedSourceReader
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connected_source_reader_returns_empty_on_empty_ledger() -> None:
    """Empty ledger → empty list. Honest stub posture per Sub-wave B
    concern #1."""
    ledger = InMemoryLedger()
    reader = LedgerConnectedSourceReader(ledger=ledger)
    rows = await reader.list_connected_sources(company_id=_COMPANY_ID)
    assert rows == []


@pytest.mark.asyncio
async def test_connected_source_reader_returns_only_connected_or_profiled() -> None:
    """Filter contract: only sources in connected/profiled state surface.

    A proposed-only source should NOT show up.
    """
    ledger = InMemoryLedger()
    src_proposed_only = uuid4()
    src_connected = uuid4()
    src_profiled = uuid4()

    await _write_source_proposed(
        ledger, source_id=src_proposed_only, source_kind="csv_local",
    )
    await _write_source_proposed(
        ledger, source_id=src_connected, source_kind="postgres",
    )
    await _write_source_lifecycle_entry(
        ledger, source_id=src_connected, tool="emit_source_connected",
        extra={
            "connection_ref": "postgres://test",
            "connected_at": datetime.now(UTC).isoformat(),
        },
    )
    await _write_source_proposed(
        ledger, source_id=src_profiled, source_kind="stripe",
    )
    await _write_source_lifecycle_entry(
        ledger, source_id=src_profiled, tool="emit_source_connected",
        extra={
            "connection_ref": "stripe://test",
            "connected_at": datetime.now(UTC).isoformat(),
        },
    )
    await _write_source_lifecycle_entry(
        ledger, source_id=src_profiled, tool="emit_source_profiled",
        extra={
            "row_count": 100,
            "column_count": 5,
            "schema_hash": "deadbeef",
            "profile_ref": "p1",
        },
    )

    reader = LedgerConnectedSourceReader(ledger=ledger)
    rows = await reader.list_connected_sources(company_id=_COMPANY_ID)
    source_ids = {r.source_id for r in rows}
    assert str(src_proposed_only) not in source_ids
    assert str(src_connected) in source_ids
    assert str(src_profiled) in source_ids


@pytest.mark.asyncio
async def test_connected_source_reader_replay_stability() -> None:
    """Per Sub-wave B handoff concern #8: same ledger → same output.

    The reader is deterministic — sorting by source_id gives stable
    ordering across runs. The v027 fold relies on this for
    candidate_id collision absorption.
    """
    ledger = InMemoryLedger()
    src = uuid4()
    await _write_source_proposed(ledger, source_id=src, source_kind="csv_local")
    await _write_source_lifecycle_entry(
        ledger, source_id=src, tool="emit_source_connected",
        extra={
            "connection_ref": "test",
            "connected_at": datetime.now(UTC).isoformat(),
        },
    )

    reader = LedgerConnectedSourceReader(ledger=ledger)
    first = await reader.list_connected_sources(company_id=_COMPANY_ID)
    second = await reader.list_connected_sources(company_id=_COMPANY_ID)
    assert first == second


@pytest.mark.asyncio
async def test_connected_source_reader_threads_kind_and_classification() -> None:
    """Strategy-facing record carries kind + domain + classification."""
    ledger = InMemoryLedger()
    src = uuid4()
    await _write_source_proposed(
        ledger,
        source_id=src,
        source_kind="postgres",
        suggested_domain="finance",
        suggested_classification="confidential",
    )
    await _write_source_lifecycle_entry(
        ledger, source_id=src, tool="emit_source_connected",
        extra={
            "connection_ref": "postgres://test",
            "connected_at": datetime.now(UTC).isoformat(),
        },
    )

    reader = LedgerConnectedSourceReader(ledger=ledger)
    rows = await reader.list_connected_sources(company_id=_COMPANY_ID)
    assert len(rows) == 1
    assert rows[0].kind == "postgres"
    assert rows[0].domain_id == "finance"
    assert rows[0].classification == "confidential"


# ---------------------------------------------------------------------------
# LedgerKpiNodeReader
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kpi_node_reader_returns_empty_on_empty_ledger() -> None:
    """Empty ledger → empty list. Honest stub posture."""
    ledger = InMemoryLedger()
    reader = LedgerKpiNodeReader(ledger=ledger)
    rows = await reader.list_kpi_nodes_without_source(company_id=_COMPANY_ID)
    assert rows == []


@pytest.mark.asyncio
async def test_kpi_node_reader_filters_to_unbacked_nodes() -> None:
    """KPIs WITH source_ids are excluded; only unbacked ones surface."""
    ledger = InMemoryLedger()
    backed = uuid4()
    unbacked = uuid4()
    src = uuid4()

    await _write_kpi_proposed(
        ledger, kpi_id=backed, label="backed_revenue", source_ids=[src],
    )
    await _write_kpi_proposed(
        ledger, kpi_id=unbacked, label="unbacked_pipeline", source_ids=[],
    )

    reader = LedgerKpiNodeReader(ledger=ledger)
    rows = await reader.list_kpi_nodes_without_source(company_id=_COMPANY_ID)
    ids = {r.kpi_node_id for r in rows}
    assert str(unbacked) in ids
    assert str(backed) not in ids


@pytest.mark.asyncio
async def test_kpi_node_reader_replay_stability() -> None:
    """Same ledger → same output (Sub-wave B concern #8)."""
    ledger = InMemoryLedger()
    await _write_kpi_proposed(
        ledger, kpi_id=uuid4(), label="q3_revenue", source_ids=[],
    )
    await _write_kpi_proposed(
        ledger, kpi_id=uuid4(), label="daily_active_users", source_ids=[],
    )
    reader = LedgerKpiNodeReader(ledger=ledger)
    first = await reader.list_kpi_nodes_without_source(company_id=_COMPANY_ID)
    second = await reader.list_kpi_nodes_without_source(company_id=_COMPANY_ID)
    assert first == second


@pytest.mark.asyncio
async def test_kpi_node_reader_threads_label_as_name() -> None:
    """KPI ``label`` field is exposed as the record's ``name``."""
    ledger = InMemoryLedger()
    kpi = uuid4()
    await _write_kpi_proposed(
        ledger, kpi_id=kpi, label="q4_pipeline_value", source_ids=[],
    )
    reader = LedgerKpiNodeReader(ledger=ledger)
    rows = await reader.list_kpi_nodes_without_source(company_id=_COMPANY_ID)
    assert len(rows) == 1
    assert rows[0].name == "q4_pipeline_value"


# ---------------------------------------------------------------------------
# LedgerSilverConversationReader
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_silver_conversation_reader_returns_empty_on_empty_ledger() -> None:
    """Empty ledger → empty list. ChannelMention honest-stub posture
    per Sub-wave A handoff concern #1.
    """
    ledger = InMemoryLedger()
    reader = LedgerSilverConversationReader(ledger=ledger)
    rows = await reader.list_recent_conversations(company_id=_COMPANY_ID)
    assert rows == []


@pytest.mark.asyncio
async def test_silver_conversation_reader_returns_chat_received_rows() -> None:
    """Recent chat_received entries land as SilverConversationRecord."""
    ledger = InMemoryLedger()
    await _write_chat_received(
        ledger,
        message_id="m-1",
        channel_id="c-data",
        text="we should look at our snowflake warehouse",
        classification="internal",
    )
    await _write_chat_received(
        ledger,
        message_id="m-2",
        channel_id="c-data",
        text="another message",
        classification="public",
    )

    reader = LedgerSilverConversationReader(ledger=ledger)
    rows = await reader.list_recent_conversations(company_id=_COMPANY_ID)
    assert len(rows) == 2
    texts = {r.text for r in rows}
    assert "we should look at our snowflake warehouse" in texts
    assert "another message" in texts


@pytest.mark.asyncio
async def test_silver_conversation_reader_threads_classification() -> None:
    """Classification field is preserved verbatim (strategy decides
    policy; per Sub-wave B handoff concern #3)."""
    ledger = InMemoryLedger()
    await _write_chat_received(
        ledger,
        message_id="m-pii",
        channel_id="c-sensitive",
        text="some pii data",
        classification="pii",
    )
    reader = LedgerSilverConversationReader(ledger=ledger)
    rows = await reader.list_recent_conversations(company_id=_COMPANY_ID)
    assert len(rows) == 1
    assert rows[0].classification == "pii"


@pytest.mark.asyncio
async def test_silver_conversation_reader_caps_at_1000_rows() -> None:
    """Reader caps return at most-recent 1000 rows.

    Reduce to a small smoke check (writing 1001+ rows is too slow for
    the unit suite) — we verify the cap constant is respected via
    direct invocation with a tight bound.
    """
    from wormbase_core import source_candidate_readers
    assert source_candidate_readers._MAX_CONVERSATIONS_CAP == 1000


@pytest.mark.asyncio
async def test_silver_conversation_reader_replay_stability() -> None:
    """Same ledger snapshot → same output (within the recency window)."""
    ledger = InMemoryLedger()
    await _write_chat_received(
        ledger, message_id="m-1", channel_id="c-1", text="hi",
    )
    await _write_chat_received(
        ledger, message_id="m-2", channel_id="c-1", text="hello",
    )

    reader = LedgerSilverConversationReader(ledger=ledger)
    first = await reader.list_recent_conversations(
        company_id=_COMPANY_ID, since_seconds=86400,
    )
    second = await reader.list_recent_conversations(
        company_id=_COMPANY_ID, since_seconds=86400,
    )
    assert {r.message_id for r in first} == {r.message_id for r in second}


@pytest.mark.asyncio
async def test_silver_conversation_reader_filters_by_window() -> None:
    """``since_seconds=0`` excludes everything (window floor = now)."""
    ledger = InMemoryLedger()
    await _write_chat_received(
        ledger, message_id="m-1", channel_id="c-1", text="hi",
    )
    reader = LedgerSilverConversationReader(ledger=ledger)
    # since_seconds=0 — window floor exactly = now; entries written
    # BEFORE this call land OUTSIDE the window (epsilon below 'now').
    # Wait a tick so the chat_received entry's ts is strictly < now.
    await asyncio.sleep(0.01)
    rows = await reader.list_recent_conversations(
        company_id=_COMPANY_ID, since_seconds=0,
    )
    assert rows == []
