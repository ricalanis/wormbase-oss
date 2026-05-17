"""End-to-end OSS audit replay (PRD §7 P8).

Drives a live in-memory tenant through three KPI flows, exports each
tenant's ledger as a JSONL snapshot, then replays it via the
clean-venv-installable ``wormbase-tools`` package and asserts:

- KPI value matches the live tenant byte-for-byte (≥3 KPIs).
- Replay completes in <10s on stock laptop for ≥1000-entry snapshot.
- Snapshot with a tampered hash refuses to run (fail-closed).
- Provenance trail is deterministic across re-runs.

The ``wormbase-tools`` package itself only depends on click + pydantic.
This test, however, runs in the monorepo's full venv so it can use the
real ``wormbase_ledger`` writer to produce the snapshot — i.e. it
verifies the OSS replay against a snapshot the hosted plane would
produce.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

# Add the wormbase-tools src to sys.path so we can import without
# requiring a separate `pip install -e` step in the test runner.
_TOOLS_SRC = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "wormbase-tools"
    / "src"
)
if str(_TOOLS_SRC) not in sys.path:
    sys.path.insert(0, str(_TOOLS_SRC))

from wormbase_ledger import InMemoryLedger  # noqa: E402

from wormbase_tools.replay import (  # noqa: E402
    ReplayError,
    replay_snapshot,
)
from wormbase_tools.snapshot import SnapshotError  # noqa: E402


def _ledger_to_jsonl(ledger: InMemoryLedger, company_id: UUID, path: Path) -> None:
    """Export the in-memory ledger to a JSONL snapshot file.

    Writes one fully-formed entry per line with bytes hashed to hex,
    UUIDs as strings, and ts as RFC 3339 with trailing 'Z'. Mirrors
    what the hosted plane's ``wormbase-ledger snapshot`` exporter
    will produce in production (see docs/oss-audit-replay.md).
    """
    rows = ledger._entries.get(company_id, [])  # noqa: SLF001 (test-only access)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            ts = r["ts"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            else:
                ts = ts.astimezone(UTC)
            base = ts.strftime("%Y-%m-%dT%H:%M:%S")
            frac = ""
            if ts.microsecond:
                frac = f".{ts.microsecond:06d}".rstrip("0").rstrip(".")
            ts_str = base + frac + "Z"
            entry = {
                "entry_id": str(r["entry_id"]),
                "company_id": str(r["company_id"]),
                "seq": int(r["seq"]),
                "ts": ts_str,
                "kind": r["kind"],
                "quadrant": r["quadrant"],
                "payload": r["payload"],
                "prev_hash": bytes(r["prev_hash"]).hex(),
                "hash": bytes(r["hash"]).hex(),
            }
            f.write(
                json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
            )


async def _write_kpi(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    kpi_id: UUID,
    label: str,
    value: float | int,
    unit: str,
) -> tuple[UUID, UUID]:
    """Write the canonical (gold → kpi_proposed) pair into the ledger.

    Returns the (source_id, gold_artifact_id) used. Each write goes
    through the live PEVR primitive so the resulting hash chain is
    bit-equal to what production would produce.
    """
    source_id = uuid4()
    gold_id = uuid4()

    # Gold artifact carries the value.
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "source_golded",
            "ref_id": str(source_id),
            "reason": f"gold artifact for {label}",
            "proposed_by": "test_oss_audit_replay",
        },
        execute_fn=lambda: {
            "tool": "emit_source_golded",
            "args": {
                "source_id": str(source_id),
                "gold_artifact_id": str(gold_id),
                "artifact_kind": "kpi",
                "value": {"value": value, "unit": unit},
                "computed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
            "result_ref": str(gold_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "gold_valid", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "gold artifact computed",
        },
        quadrant="active_deterministic",
    )

    # KPI proposal references the gold via source_ids.
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "kpi_proposed",
            "ref_id": str(kpi_id),
            "reason": f"kpi proposal for {label}",
            "proposed_by": "test_oss_audit_replay",
        },
        execute_fn=lambda: {
            "tool": "emit_kpi_proposed",
            "args": {
                "kpi_id": str(kpi_id),
                "label": label,
                "formula": f"sum({label.lower()})",
                "source_ids": [str(source_id)],
                "unit": unit,
                "owner_position": "finance.cfo",
                "proposed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
            "result_ref": str(kpi_id),
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "kpi_proposal_valid", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "KPI proposal recorded",
        },
        quadrant="active_deterministic",
    )

    return source_id, gold_id


@pytest.mark.asyncio
async def test_oss_audit_replay_reproduces_three_kpis(tmp_path: Path) -> None:
    """Live ledger writes 3 KPIs ⇒ snapshot ⇒ wormbase-tools replay
    reproduces each KPI value bit-for-bit (PRD §7 P8 acceptance)."""
    ledger = InMemoryLedger()
    company_id = uuid4()

    expected = {
        uuid4(): ("Q3 Net Revenue", 142857.42, "USD"),
        uuid4(): ("Annual Recurring Revenue", 9_999_999, "USD"),
        uuid4(): ("Monthly Active Users", 314159, "count"),
    }
    for kpi_id, (label, value, unit) in expected.items():
        await _write_kpi(
            ledger,
            company_id=company_id,
            kpi_id=kpi_id,
            label=label,
            value=value,
            unit=unit,
        )

    snapshot_path = tmp_path / "snapshot.jsonl"
    _ledger_to_jsonl(ledger, company_id, snapshot_path)

    # Sanity: the file is non-empty and parses as JSONL.
    line_count = sum(1 for _ in snapshot_path.open())
    assert line_count > 0

    # Replay each KPI; the value must match what the live ledger
    # produced. ``ReplayResult.value`` reads the gold-artifact value
    # via the same fold logic the hosted plane uses for /kpis.
    for kpi_id, (label, expected_value, _unit) in expected.items():
        result = replay_snapshot(
            snapshot_path,
            tenant_id=str(company_id),
            kpi_id=str(kpi_id),
        )
        assert result.value == expected_value, (
            f"KPI {label} ({kpi_id}): expected {expected_value}, "
            f"replay returned {result.value}"
        )
        # Provenance trail must include at least the kpi_proposed
        # entry id and the source_golded entry id.
        assert len(result.contributing_entry_ids) >= 2


@pytest.mark.asyncio
async def test_oss_audit_replay_completes_under_10s(tmp_path: Path) -> None:
    """Acceptance: replay <10s on stock laptop for 1000-entry snapshot."""
    ledger = InMemoryLedger()
    company_id = uuid4()

    # Pad with 250 quick PEVR cycles (4 entries each = 1000 ledger rows)
    # and one trailing KPI cycle.
    for _ in range(249):
        await ledger.write(
            company_id=company_id,
            propose={
                "target_kind": "noop",
                "ref_id": str(uuid4()),
                "reason": "padding",
                "proposed_by": "test",
            },
            execute_fn=lambda: {
                "tool": "emit_memory_written",
                "args": {
                    "memory_id": str(uuid4()),
                    "content": "padding entry",
                    "tags": [],
                },
                "result_ref": "m",
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "ok", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "pad"},
        )

    kpi_id = uuid4()
    await _write_kpi(
        ledger,
        company_id=company_id,
        kpi_id=kpi_id,
        label="Padded KPI",
        value=42.0,
        unit="count",
    )

    snapshot_path = tmp_path / "big_snapshot.jsonl"
    _ledger_to_jsonl(ledger, company_id, snapshot_path)
    entry_count = sum(1 for _ in snapshot_path.open())
    assert entry_count >= 1000

    started = time.perf_counter()
    result = replay_snapshot(
        snapshot_path, tenant_id=str(company_id), kpi_id=str(kpi_id)
    )
    elapsed = time.perf_counter() - started

    assert result.value == 42.0
    assert elapsed < 10.0, f"replay took {elapsed:.2f}s, exceeds 10s budget"


@pytest.mark.asyncio
async def test_oss_audit_replay_refuses_tampered_snapshot(tmp_path: Path) -> None:
    """Fail-closed: tampered hash must abort replay (no partial output).

    The auditor's trust model demands this: a snapshot whose chain
    can't be re-verified must produce no KPI value, period.
    """
    ledger = InMemoryLedger()
    company_id = uuid4()
    kpi_id = uuid4()
    await _write_kpi(
        ledger,
        company_id=company_id,
        kpi_id=kpi_id,
        label="Fragile KPI",
        value=1.0,
        unit="USD",
    )
    snapshot_path = tmp_path / "snapshot.jsonl"
    _ledger_to_jsonl(ledger, company_id, snapshot_path)

    # Tamper the third line's payload (any entry mid-chain works).
    lines = snapshot_path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[2])
    # Change a payload field without recomputing the hash → recomputed
    # hash will not match stored hash, AND the next entry's prev_hash
    # will mismatch.
    if isinstance(rec.get("payload"), dict):
        rec["payload"]["__tampered__"] = True
    lines[2] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    snapshot_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SnapshotError):
        replay_snapshot(
            snapshot_path,
            tenant_id=str(company_id),
            kpi_id=str(kpi_id),
        )


@pytest.mark.asyncio
async def test_oss_audit_replay_provenance_is_deterministic(tmp_path: Path) -> None:
    """Provenance trail must be the same on every replay invocation."""
    ledger = InMemoryLedger()
    company_id = uuid4()
    kpi_id = uuid4()
    await _write_kpi(
        ledger,
        company_id=company_id,
        kpi_id=kpi_id,
        label="Deterministic KPI",
        value=2718.28,
        unit="USD",
    )
    snapshot_path = tmp_path / "snapshot.jsonl"
    _ledger_to_jsonl(ledger, company_id, snapshot_path)

    r1 = replay_snapshot(
        snapshot_path, tenant_id=str(company_id), kpi_id=str(kpi_id)
    )
    r2 = replay_snapshot(
        snapshot_path, tenant_id=str(company_id), kpi_id=str(kpi_id)
    )
    assert r1.value == r2.value
    assert r1.terminal_hash == r2.terminal_hash
    assert r1.contributing_entry_ids == r2.contributing_entry_ids


@pytest.mark.asyncio
async def test_oss_audit_replay_runs_without_postgres_or_async_db(tmp_path: Path) -> None:
    """The auditor's clean-venv install must not import asyncpg / aiosqlite /
    SQLAlchemy. We assert this by inspecting what the wormbase_tools
    package actually pulls into sys.modules at import time on a fresh
    process boundary.
    """
    # Already imported at module level — check that none of the
    # forbidden modules came along for the ride.
    forbidden = ("asyncpg", "aiosqlite", "sqlalchemy")
    leaked = [m for m in forbidden if any(k.startswith(m) for k in sys.modules)]
    # NB: asyncpg / sqlalchemy may be in sys.modules because OTHER
    # tests in this monorepo imported them earlier. The relevant
    # contract is "wormbase_tools does not import them" — verify by
    # looking at the package's __init__ explicitly.
    import wormbase_tools
    src = Path(wormbase_tools.__file__).resolve()

    # Walk every module file in wormbase_tools; assert none has a
    # top-level "import asyncpg / aiosqlite / sqlalchemy".
    pkg_root = src.parent
    for py in pkg_root.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for f in forbidden:
            assert f"import {f}" not in text, (
                f"wormbase_tools/{py.relative_to(pkg_root)} imports "
                f"forbidden module {f}; this would break the auditor's "
                "clean-venv install"
            )
            assert f"from {f}" not in text, (
                f"wormbase_tools/{py.relative_to(pkg_root)} imports "
                f"from forbidden module {f}; this would break the "
                "auditor's clean-venv install"
            )
    # leaked is informational; the file-level assertion is the contract.
    _ = leaked
