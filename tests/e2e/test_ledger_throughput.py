"""W6.A6 — load smoke for the ledger write path.

Gated on ``WORMBASE_LOAD=1``. Writes 1000 chat events through the
wire-replay primitive (the same code path the live channel-adapter
uses) and asserts:

* All 1000 events land — no dropped writes.
* Wall-clock for 1000 in-process writes stays under a generous ceiling
  (60s — the L4 budget; in practice this should clock in <10s on a
  modest laptop).
* The hash chain over the resulting ledger verifies (chain integrity
  preserved at scale).
* The 1000 entries land in seq order (no out-of-order writes).

The "/trace returns recent rows within 1s after the last write"
acceptance criterion in the original plan requires a running
dashboard. We test the equivalent invariant at the ledger layer:
``Ledger.fetch`` returns the most recent entry within 1s of the
last write. If that property holds, the dashboard's /trace surface
inherits it directly.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest

from wormbase_channel_adapter.wire_replay import WireReplayer
from wormbase_ledger import InMemoryLedger


pytestmark = pytest.mark.asyncio


N_EVENTS = 1000
WALL_CLOCK_BUDGET_S = 60.0
TRACE_LATENCY_BUDGET_S = 1.0
TENANT_NAMESPACE = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")


def _company_id_for(slug: str) -> UUID:
    return uuid5(TENANT_NAMESPACE, slug.strip().lower())


def _load_gated() -> bool:
    return os.environ.get("WORMBASE_LOAD", "").strip() == "1"


load_skip = pytest.mark.skipif(
    not _load_gated(),
    reason=(
        "load smoke off by default — set WORMBASE_LOAD=1 to run. "
        "Writes 1000 events; takes ~10-30s of wall-clock."
    ),
)


def _make_throughput_fixture(path: Path, n: int) -> None:
    sender = str(uuid4())
    with path.open("w", encoding="utf-8") as fh:
        for i in range(n):
            rec = {
                "seq": i + 1,
                "ts": f"2026-04-28T00:{i // 60 % 60:02d}:{i % 60:02d}+00:00",
                "tool": "channel_adapter.emit_chat_received",
                "args": {
                    "channel_id": "C-load",
                    "message_id": f"{i:08d}.{i:04d}",
                    "sender_person": sender,
                    "text": f"load event {i:04d}",
                    "classification": "internal",
                },
            }
            fh.write(json.dumps(rec) + "\n")


@load_skip
async def test_load_1000_events_all_land(tmp_path: Path) -> None:
    """All 1000 events land as four-row PEVR cycles in the ledger."""
    fixture = tmp_path / "throughput-1000.jsonl"
    _make_throughput_fixture(fixture, N_EVENTS)
    ledger = InMemoryLedger()
    company_id = _company_id_for("loadtest")
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=fixture,
    )
    n = await replayer.run()
    assert n == N_EVENTS

    rows = await ledger.fetch(company_id)
    assert len(rows) == 4 * N_EVENTS, (
        f"expected {4 * N_EVENTS} rows (4 PEVR per event); got {len(rows)}"
    )


@load_skip
async def test_load_throughput_under_60s(tmp_path: Path) -> None:
    """1000 events through wire-replay finish under 60s wall clock."""
    fixture = tmp_path / "throughput-1000.jsonl"
    _make_throughput_fixture(fixture, N_EVENTS)
    ledger = InMemoryLedger()
    company_id = _company_id_for("loadtest")
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=fixture,
    )
    started = time.monotonic()
    await replayer.run()
    elapsed = time.monotonic() - started
    assert elapsed < WALL_CLOCK_BUDGET_S, (
        f"1000-event load took {elapsed:.1f}s; ceiling is "
        f"{WALL_CLOCK_BUDGET_S}s. Throughput regression."
    )


@load_skip
async def test_load_chain_integrity_preserved_at_scale(
    tmp_path: Path,
) -> None:
    """Hash chain verifies after 1000 events.

    InMemoryLedger.verify walks every row, recomputing the hash
    and asserting prev_hash linkage. A failure here indicates the
    write primitive is producing inconsistent chains under volume.
    """
    fixture = tmp_path / "throughput-1000.jsonl"
    _make_throughput_fixture(fixture, N_EVENTS)
    ledger = InMemoryLedger()
    company_id = _company_id_for("loadtest")
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=fixture,
    )
    await replayer.run()
    report = await ledger.verify(company_id)
    assert report.ok, (
        f"hash chain broken at entry {report.broken_at} after "
        f"{N_EVENTS}-event load"
    )
    assert report.entries_checked == 4 * N_EVENTS


@load_skip
async def test_load_seq_is_contiguous_and_ordered(tmp_path: Path) -> None:
    """Sequence numbers are 1..4N with no gaps after the load.

    Confirms wire-replay's writes are serialized — no holes from
    concurrent appenders, no duplicates from retries.
    """
    fixture = tmp_path / "throughput-1000.jsonl"
    _make_throughput_fixture(fixture, N_EVENTS)
    ledger = InMemoryLedger()
    company_id = _company_id_for("loadtest")
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=fixture,
    )
    await replayer.run()

    rows = await ledger.fetch(company_id)
    seqs = [r["seq"] for r in rows]
    assert seqs == list(range(1, 4 * N_EVENTS + 1)), (
        f"seq is non-contiguous: head={seqs[:5]}, tail={seqs[-5:]}"
    )


@load_skip
async def test_load_trace_fetch_within_1s_of_last_write(
    tmp_path: Path,
) -> None:
    """Fetching the latest entries lands in <1s after the final write.

    /trace's "live updates within 1s" SLA is inherited from this
    underlying property: the ledger fetch path returns the most
    recent entry quickly. This test exercises that at the in-process
    layer; the dashboard's /trace API is a thin wrapper.
    """
    fixture = tmp_path / "throughput-1000.jsonl"
    _make_throughput_fixture(fixture, N_EVENTS)
    ledger = InMemoryLedger()
    company_id = _company_id_for("loadtest")
    replayer = WireReplayer(
        ledger=ledger,
        company_id=company_id,
        jsonl_path=fixture,
    )
    await replayer.run()

    started = time.monotonic()
    rows = await ledger.fetch(company_id)
    fetch_elapsed = time.monotonic() - started
    assert fetch_elapsed < TRACE_LATENCY_BUDGET_S, (
        f"fetch over {len(rows)} rows took {fetch_elapsed:.3f}s; "
        f"/trace SLA is {TRACE_LATENCY_BUDGET_S}s."
    )
    assert len(rows) == 4 * N_EVENTS
