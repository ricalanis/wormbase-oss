"""Tests for assert_demo_invariants — feed a fake ledger and assert results."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from wormbase_sim_harness.acceptance import assert_demo_invariants


class FakeLedger:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetch(
        self, company_id: UUID, until_ts: datetime | None = None
    ) -> list[dict[str, Any]]:
        return list(self._rows)


def _exec(tool: str, ts: datetime) -> dict[str, Any]:
    return {
        "kind": "execute",
        "ts": ts,
        "payload": {"tool": tool, "args": {}, "result_ref": "x"},
    }


@pytest.mark.asyncio
async def test_all_checks_pass_on_complete_ledger() -> None:
    started = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    rows = [
        # Pre-run noise — ignored because ts < started.
        _exec("channel_adapter.emit_chat_received", started - timedelta(minutes=5)),
        # In-window entries.
        _exec("channel_adapter.emit_chat_received", started + timedelta(seconds=1)),
        _exec("channel_adapter.emit_chat_received", started + timedelta(seconds=2)),
        _exec("channel_adapter.emit_file_received", started + timedelta(seconds=15)),
        _exec("emit_source_proposed", started + timedelta(seconds=20)),
        _exec("channel_adapter.emit_chat_sent", started + timedelta(seconds=30)),
        # Decoy: a propose row with the same tool name should NOT count.
        {
            "kind": "propose",
            "ts": started + timedelta(seconds=5),
            "payload": {"tool": "channel_adapter.emit_chat_received"},
        },
    ]
    led = FakeLedger(rows)
    report = await assert_demo_invariants(led, uuid4(), started)
    assert report.passed is True
    assert report.entries_scanned == 6  # 7 rows - 1 pre-window
    names = {c.name for c in report.checks}
    assert names == {
        "chat_received >= 1",
        "file_received >= 1",
        "source_proposed >= 1",
        "chat_sent >= 1",
    }


@pytest.mark.asyncio
async def test_fails_when_no_chat_sent() -> None:
    started = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    rows = [
        _exec("channel_adapter.emit_chat_received", started + timedelta(seconds=1)),
        _exec("channel_adapter.emit_file_received", started + timedelta(seconds=2)),
        _exec("emit_source_proposed", started + timedelta(seconds=3)),
        # No chat_sent.
    ]
    led = FakeLedger(rows)
    report = await assert_demo_invariants(led, uuid4(), started)
    assert report.passed is False
    failed = [c.name for c in report.checks if not c.passed]
    assert failed == ["chat_sent >= 1"]


@pytest.mark.asyncio
async def test_can_relax_individual_checks() -> None:
    started = datetime(2026, 4, 25, 12, 0, tzinfo=UTC)
    rows = [_exec("channel_adapter.emit_chat_received", started + timedelta(seconds=1))]
    led = FakeLedger(rows)
    report = await assert_demo_invariants(
        led,
        uuid4(),
        started,
        expect_file_in=False,
        expect_source_proposed=False,
        expect_chat_out=False,
    )
    assert report.passed is True
    names = [c.name for c in report.checks]
    assert names == ["chat_received >= 1"]
