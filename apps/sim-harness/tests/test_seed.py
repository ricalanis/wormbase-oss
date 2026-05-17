"""Tests for ``wormbase_sim_harness.seed.seed_tenant``.

The seed module's public surface is two things:

* ``seed_tenant`` — async tenant bootstrap (reset + warmup + history).
* ``SeedReport`` — Pydantic model returned by the above.

These tests exercise both with an ``InMemoryLedger`` so they don't need
Postgres. The seed module's ``_reset_tenant`` helper has a documented
in-memory fallback (clears ``_entries`` directly when no engine is
attached) that we deliberately rely on here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from wormbase_ledger import InMemoryLedger
from wormbase_sim_harness.seed import (
    _HISTORY_BEATS,
    SeedReport,
    seed_tenant,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_chat_received_seed_rows(
    ledger: InMemoryLedger, company_id: UUID
) -> int:
    """Count execute rows whose tool is the seed-history emitter."""
    rows = ledger._entries.get(company_id, [])
    return sum(
        1
        for r in rows
        if r.get("kind") == "execute"
        and (r.get("payload") or {}).get("tool")
        == "sim-harness.seed.emit_chat_received"
    )


def _count_warmup_completed_rows(
    ledger: InMemoryLedger, company_id: UUID
) -> int:
    rows = ledger._entries.get(company_id, [])
    n = 0
    for r in rows:
        if r.get("kind") != "execute":
            continue
        args = (r.get("payload") or {}).get("args") or {}
        if args.get("content", "").startswith("company_warmup_completed"):
            n += 1
    return n


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_tenant_warmup_only_grows_ledger() -> None:
    """Default flow: reset_first=False, write_history defaults to False.

    Fresh tenants start with no chat history (production-equivalent
    baseline). Wire-replay via ``--replay-history`` is the supported way
    to fast-forward a tenant past empty-channel state.
    """
    ledger = InMemoryLedger()
    report = await seed_tenant(
        ledger=ledger,
        tenant="baseworm",
        domain_pack="saas",
        reset_first=False,
    )
    assert isinstance(report, SeedReport)
    assert report.tenant == "baseworm"
    assert report.warmup_ran is True
    assert report.warmup_already_warm is False
    assert report.warmup_entries_written > 0
    assert report.history_entries_written == 0
    assert report.history_entries_skipped == 0

    # Warmup wrote at least the company_warmup_completed marker.
    assert _count_warmup_completed_rows(ledger, report.company_id) == 1
    # And no seed-history rows yet.
    assert _count_chat_received_seed_rows(ledger, report.company_id) == 0


@pytest.mark.asyncio
async def test_seed_tenant_default_skips_history() -> None:
    """Without explicit ``write_history=True`` the seed flow writes no
    chat history. This protects against the legacy
    ``sim-harness.seed.emit_chat_received`` direct-write path leaking
    back into the default ``wormbase demo seed`` flow.
    """
    ledger = InMemoryLedger()
    report = await seed_tenant(ledger=ledger, tenant="baseworm")
    assert report.history_entries_written == 0
    assert _count_chat_received_seed_rows(ledger, report.company_id) == 0


@pytest.mark.asyncio
async def test_seed_tenant_reset_then_history_writes_all_beats() -> None:
    """reset_first=True + write_history=True → clears + warmup + history."""
    ledger = InMemoryLedger()
    # Pre-populate with a stray entry under the same tenant — reset
    # should sweep it.
    company_uuid_for_baseworm = (
        await seed_tenant(
            ledger=ledger,
            tenant="baseworm",
            write_history=False,
        )
    ).company_id
    pre_reset_count = len(ledger._entries.get(company_uuid_for_baseworm, []))
    assert pre_reset_count > 0

    report = await seed_tenant(
        ledger=ledger,
        tenant="baseworm",
        domain_pack="saas",
        reset_first=True,
        write_history=True,
        history_days=7,
        now=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
    )
    assert report.reset is True
    assert report.rows_deleted == pre_reset_count
    assert report.warmup_ran is True
    assert report.warmup_already_warm is False
    # Every in-window beat should have been written. _HISTORY_BEATS is
    # the canonical set; with history_days=7 all of them are in window.
    expected_beats = sum(1 for b in _HISTORY_BEATS if b.days_ago <= 7)
    assert report.history_entries_written == expected_beats
    assert report.history_entries_skipped == 0
    # Verify rows physically present in the ledger.
    assert (
        _count_chat_received_seed_rows(ledger, report.company_id)
        == expected_beats
    )


@pytest.mark.asyncio
async def test_seed_tenant_history_dedupes_on_replay() -> None:
    """Re-running with the same beats must not double-write."""
    ledger = InMemoryLedger()
    fixed_now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)

    first = await seed_tenant(
        ledger=ledger,
        tenant="baseworm",
        reset_first=True,
        write_history=True,
        now=fixed_now,
    )
    rows_after_first = len(ledger._entries[first.company_id])
    seed_rows_after_first = _count_chat_received_seed_rows(
        ledger, first.company_id
    )
    assert first.history_entries_written == seed_rows_after_first

    # Second call: no reset, same beats. Warmup short-circuits as
    # already_warm; history entries dedupe on (channel_id, message_id).
    second = await seed_tenant(
        ledger=ledger,
        tenant="baseworm",
        reset_first=False,
        write_history=True,
        now=fixed_now,
    )
    assert second.warmup_already_warm is True
    assert second.history_entries_written == 0
    assert second.history_entries_skipped == seed_rows_after_first
    # Ledger size unchanged after the dedupe pass.
    assert len(ledger._entries[second.company_id]) == rows_after_first


@pytest.mark.asyncio
async def test_seed_tenant_idempotent_across_two_calls() -> None:
    """Two consecutive seeds with reset_first=True land in identical state."""
    ledger_a = InMemoryLedger()
    ledger_b = InMemoryLedger()
    fixed_now = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)

    # Run seed twice into ledger_a (second call resets first).
    await seed_tenant(
        ledger=ledger_a,
        tenant="baseworm",
        reset_first=False,
        write_history=True,
        now=fixed_now,
    )
    rep_a = await seed_tenant(
        ledger=ledger_a,
        tenant="baseworm",
        reset_first=True,
        write_history=True,
        now=fixed_now,
    )

    # Run seed once into ledger_b with the same fixed_now and reset.
    rep_b = await seed_tenant(
        ledger=ledger_b,
        tenant="baseworm",
        reset_first=True,
        write_history=True,
        now=fixed_now,
    )

    # Same company_id (deterministic from tenant slug).
    assert rep_a.company_id == rep_b.company_id
    cid = rep_a.company_id

    rows_a = ledger_a._entries[cid]
    rows_b = ledger_b._entries[cid]
    # Same row count and same per-kind distribution. Warmup rows use
    # datetime.now(UTC) internally so their ts won't match across runs;
    # the assertion focuses on the structural shape (kinds + tool names)
    # and on full equality for the seed-history beats (which honor
    # ``fixed_now`` deterministically).
    assert len(rows_a) == len(rows_b)
    for ra, rb in zip(rows_a, rows_b, strict=True):
        assert ra["kind"] == rb["kind"]
        # Tool name (where present) should match.
        tool_a = (ra.get("payload") or {}).get("tool")
        tool_b = (rb.get("payload") or {}).get("tool")
        assert tool_a == tool_b
        # Seed history rows must be byte-identical apart from entry_id.
        if tool_a == "sim-harness.seed.emit_chat_received":
            assert ra["ts"] == rb["ts"]
            args_a = (ra.get("payload") or {}).get("args") or {}
            args_b = (rb.get("payload") or {}).get("args") or {}
            assert args_a.get("message_id") == args_b.get("message_id")
            assert args_a.get("channel_id") == args_b.get("channel_id")
            assert args_a.get("text") == args_b.get("text")
            assert args_a.get("sender_person") == args_b.get("sender_person")


@pytest.mark.asyncio
async def test_seed_report_round_trips_via_model_dump() -> None:
    ledger = InMemoryLedger()
    report = await seed_tenant(
        ledger=ledger,
        tenant="acme",
        domain_pack="saas",
        write_history=False,
    )
    dumped = report.model_dump()
    assert dumped["tenant"] == "acme"
    assert isinstance(dumped["company_id"], UUID)
    assert dumped["warmup_ran"] is True

    # JSON-mode dump should serialize UUID to str and round-trip.
    json_dump = report.model_dump(mode="json")
    assert isinstance(json_dump["company_id"], str)
    rebuilt = SeedReport.model_validate(json_dump)
    assert rebuilt.tenant == report.tenant
    assert rebuilt.company_id == report.company_id
    assert rebuilt.warmup_ran is True


@pytest.mark.asyncio
async def test_seed_tenant_history_days_window_clips_beats() -> None:
    """history_days=3 should drop beats whose days_ago > 3."""
    ledger = InMemoryLedger()
    report = await seed_tenant(
        ledger=ledger,
        tenant="baseworm",
        reset_first=True,
        write_history=True,
        history_days=3,
    )
    expected = sum(1 for b in _HISTORY_BEATS if b.days_ago <= 3)
    assert report.history_entries_written == expected
    # Sanity: at least one beat is outside the 3-day window.
    assert any(b.days_ago > 3 for b in _HISTORY_BEATS)


@pytest.mark.asyncio
async def test_seed_tenant_requires_ledger_or_dsn() -> None:
    with pytest.raises(ValueError):
        await seed_tenant(tenant="x")
