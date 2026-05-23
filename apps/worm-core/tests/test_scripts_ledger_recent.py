"""Tests for wormbase_core.scripts.ledger_recent — wormbase-ledger-recent CLI.

Four test cases:
1. Smoke: seed 3 rows for altis, call main programmatically, assert each seq appears.
2. Tenant filter: seed for altis AND baseworm, only altis rows returned.
3. --kind filter: seed propose+execute rows, only propose rows returned.
4. --json: output is parseable JSONL.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid5

import pytest

from wormbase_ledger import InMemoryLedger

from wormbase_core.scripts.ledger_recent import (
    _tenant_to_company_uuid,
    fetch_rows,
    format_table,
    format_jsonl,
    main,
    WORMBASE_TENANT_NAMESPACE,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# altis company_id — uuid5(WORMBASE_TENANT_NAMESPACE, "altis")
ALTIS_COMPANY_ID = uuid5(UUID(WORMBASE_TENANT_NAMESPACE), "altis")
BASEWORM_COMPANY_ID = uuid5(UUID(WORMBASE_TENANT_NAMESPACE), "baseworm")

_NOW = datetime(2026, 5, 25, 9, 1, 12, tzinfo=UTC)


async def _seed_ledger_async(ledger: InMemoryLedger, company_id: UUID, n: int) -> None:
    """Seed n PEVR cycles into `ledger` for `company_id` (async version)."""
    for i in range(n):
        await ledger.write(
            company_id=company_id,
            propose={
                "kind": "chat_received",
                "target_kind": "chat_received",
                "tool": "channel_adapter.emit_chat_received",
                "text": f"hello team message {i}",
                "channel": "120363...@g.us",
            },
            execute_fn=lambda i=i: {
                "kind": "execute",
                "tool": "channel_adapter.emit_chat_received",
                "text": f"hello team message {i}",
                "channel": "120363...@g.us",
            },
            verify_fn=lambda _: {"passed": True},
            resolve_fn=lambda _: {"decision": "keep"},
            timestamp=_NOW,
        )


def _seed_ledger(ledger: InMemoryLedger, company_id: UUID, n: int) -> None:
    """Seed n PEVR cycles synchronously (creates a fresh event loop)."""
    asyncio.run(_seed_ledger_async(ledger, company_id, n))


# ---------------------------------------------------------------------------
# Unit-level helpers
# ---------------------------------------------------------------------------


def test_tenant_to_company_uuid_altis() -> None:
    """Verify altis resolves to the documented UUID."""
    cid = _tenant_to_company_uuid("altis")
    assert str(cid) == "7f032a92-7036-5126-a957-8d2607126169"


def test_tenant_to_company_uuid_case_insensitive() -> None:
    """Slug normalisation: 'Altis' and 'altis' yield same UUID."""
    assert _tenant_to_company_uuid("Altis") == _tenant_to_company_uuid("altis")


def test_tenant_to_company_uuid_empty_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _tenant_to_company_uuid("")


# ---------------------------------------------------------------------------
# Test 1: Smoke — 3 rows for altis, all seqs appear in stdout
# ---------------------------------------------------------------------------


def test_smoke_three_rows_all_seqs_appear(capsys) -> None:
    """Seed 3 PEVR cycles → 12 rows total; call main with ledger kwarg;
    assert each seq (1-12) appears in table output."""
    ledger = InMemoryLedger()
    _seed_ledger(ledger, ALTIS_COMPANY_ID, 3)

    main(
        argv=["--tenant", "altis", "--dsn", "ignored"],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    # 3 PEVR cycles = 12 rows; seqs 1..12 should appear in the output
    for seq in range(1, 13):
        assert str(seq) in out, f"seq {seq} missing from output"


# ---------------------------------------------------------------------------
# Test 2: Tenant filter — only altis rows appear when baseworm also seeded
# ---------------------------------------------------------------------------


def test_tenant_filter_only_altis_rows(capsys) -> None:
    """Rows for baseworm are excluded when --tenant altis is requested."""
    ledger = InMemoryLedger()
    _seed_ledger(ledger, ALTIS_COMPANY_ID, 2)
    _seed_ledger(ledger, BASEWORM_COMPANY_ID, 2)

    main(
        argv=["--tenant", "altis", "--dsn", "ignored"],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    # altis seqs are 1..8 (2 cycles × 4 PEVR rows each)
    for seq in range(1, 9):
        assert str(seq) in out

    # baseworm rows also carry seqs 1-8 but they're in a different company bucket.
    # The presence test above isn't perfect because seq numbers overlap.
    # Instead verify via --json mode (Test 4 confirms company_id filtering).
    # For this test, ensure the company_id tag for baseworm does NOT appear.
    assert str(BASEWORM_COMPANY_ID) not in out


# ---------------------------------------------------------------------------
# Test 3: --kind filter — only propose rows appear
# ---------------------------------------------------------------------------


def test_kind_filter_propose_only(capsys) -> None:
    """--kind propose returns only rows with kind=propose."""
    ledger = InMemoryLedger()
    _seed_ledger(ledger, ALTIS_COMPANY_ID, 2)  # produces propose+execute+verify+resolve

    main(
        argv=["--tenant", "altis", "--kind", "propose", "--dsn", "ignored"],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    # Remove header line to check body
    lines = [l for l in out.strip().splitlines() if l and not l.startswith("seq")]
    for line in lines:
        assert "propose" in line, f"Non-propose row in output: {line!r}"

    # 2 PEVR cycles → 2 propose rows
    assert len(lines) == 2


def test_kind_filter_execute_only(capsys) -> None:
    """--kind execute returns only rows with kind=execute."""
    ledger = InMemoryLedger()
    _seed_ledger(ledger, ALTIS_COMPANY_ID, 3)

    main(
        argv=["--tenant", "altis", "--kind", "execute", "--dsn", "ignored"],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    lines = [l for l in out.strip().splitlines() if l and not l.startswith("seq")]
    assert len(lines) == 3
    for line in lines:
        assert "execute" in line


# ---------------------------------------------------------------------------
# Test 4: --json outputs parseable JSONL
# ---------------------------------------------------------------------------


def test_json_output_is_parseable_jsonl(capsys) -> None:
    """--json produces valid JSONL with expected keys."""
    ledger = InMemoryLedger()
    _seed_ledger(ledger, ALTIS_COMPANY_ID, 2)

    main(
        argv=["--tenant", "altis", "--json", "--dsn", "ignored"],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    lines = [l for l in out.strip().splitlines() if l.strip()]
    assert len(lines) == 8  # 2 PEVR cycles × 4 rows

    for line in lines:
        obj = json.loads(line)  # must not raise
        assert "seq" in obj
        assert "ts" in obj
        assert "kind" in obj
        assert "company_id" in obj
        # All rows must belong to altis
        assert obj["company_id"] == str(ALTIS_COMPANY_ID)


# ---------------------------------------------------------------------------
# Test 5: --limit caps output rows
# ---------------------------------------------------------------------------


def test_limit_caps_rows(capsys) -> None:
    """--limit 3 returns the last 3 rows only."""
    ledger = InMemoryLedger()
    _seed_ledger(ledger, ALTIS_COMPANY_ID, 5)  # 20 rows total

    main(
        argv=["--tenant", "altis", "--limit", "3", "--dsn", "ignored"],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    lines = [l for l in out.strip().splitlines() if l and not l.startswith("seq")]
    assert len(lines) == 3


# ---------------------------------------------------------------------------
# Test 6: fetch_rows helper returns correct company scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_rows_scope() -> None:
    """fetch_rows returns only rows for the given company_id, up to limit."""
    ledger = InMemoryLedger()
    await _seed_ledger_async(ledger, ALTIS_COMPANY_ID, 3)    # 12 rows
    await _seed_ledger_async(ledger, BASEWORM_COMPANY_ID, 2)  # 8 rows

    rows = await fetch_rows(ledger, ALTIS_COMPANY_ID, limit=50, kinds=None)
    assert len(rows) == 12
    for r in rows:
        assert r["company_id"] == ALTIS_COMPANY_ID

    # baseworm rows don't bleed across
    bw_rows = await fetch_rows(ledger, BASEWORM_COMPANY_ID, limit=50, kinds=None)
    assert len(bw_rows) == 8
