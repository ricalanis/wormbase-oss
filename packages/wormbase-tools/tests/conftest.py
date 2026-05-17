"""Test fixtures for wormbase-tools.

These fixtures synthesise realistic ledger snapshots in pure Python,
using the same canonical-JSON + sha256 hash chain wormbase-ledger
writes in production. The point is to keep the test path Postgres-free
(matching the auditor's clean-venv install) while still producing
snapshots that exercise the same byte-level invariants the hosted
plane enforces.

The fixtures generate three kinds of synthetic ledgers:

* ``synthetic_kpi_snapshot`` — a small but realistic ledger with a
  source profile, a gold artifact, and a kpi_proposed entry. The KPI
  resolves to a concrete numeric value via the gold artifact's
  ``source_id``.
* ``broken_chain_snapshot`` — same structure, but with one entry's
  ``hash`` field tampered. Drives the fail-closed test.
* ``multi_tenant_snapshot`` — two tenants in one file, exercises the
  tenant-pin disambiguation path.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest


GENESIS_PREV_HASH: bytes = b"\x00" * 32


def _canon_default(o: Any) -> Any:
    if isinstance(o, UUID):
        return str(o)
    if isinstance(o, datetime):
        if o.tzinfo is None:
            raise ValueError("ts must be tz-aware")
        u = o.astimezone(UTC).replace(tzinfo=UTC)
        base = u.strftime("%Y-%m-%dT%H:%M:%S")
        frac = ""
        if u.microsecond:
            frac = f".{u.microsecond:06d}".rstrip("0").rstrip(".")
        return base + frac + "Z"
    if isinstance(o, (bytes, bytearray)):
        return bytes(o).hex()
    raise TypeError(f"unserialisable: {type(o).__name__}")


def _canon(entry: dict[str, Any]) -> str:
    view = {k: v for k, v in entry.items() if k != "hash"}
    return json.dumps(
        view,
        sort_keys=True,
        separators=(",", ":"),
        default=_canon_default,
        ensure_ascii=False,
    )


def _hash(entry: dict[str, Any]) -> bytes:
    return hashlib.sha256(_canon(entry).encode("utf-8")).digest()


def _build_chain(
    company_id: UUID,
    payloads: list[tuple[str, str, dict[str, Any]]],
    *,
    start_ts: datetime | None = None,
    start_seq: int = 1,
    prev_hash: bytes = GENESIS_PREV_HASH,
) -> tuple[list[dict[str, Any]], bytes]:
    """Build a hash-chained list of ledger entries.

    Each input tuple is ``(kind, quadrant, payload_dict)``. Returns the
    list of fully-formed entries plus the terminal hash.
    """
    if start_ts is None:
        start_ts = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)
    out: list[dict[str, Any]] = []
    cur_prev = prev_hash
    for i, (kind, quadrant, payload) in enumerate(payloads):
        entry = {
            "entry_id": str(uuid4()),
            "company_id": str(company_id),
            "seq": start_seq + i,
            "ts": (start_ts + timedelta(seconds=i)).isoformat().replace(
                "+00:00", "Z"
            ),
            "kind": kind,
            "quadrant": quadrant,
            "payload": payload,
            "prev_hash": cur_prev.hex(),
            # hash filled in below
        }
        h = _hash(entry)
        entry["hash"] = h.hex()
        out.append(entry)
        cur_prev = h
    return out, cur_prev


def _write_jsonl(path: Path, entries: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, sort_keys=True, separators=(",", ":")) + "\n")


@pytest.fixture
def synthetic_kpi_snapshot(tmp_path: Path) -> dict[str, Any]:
    """A 6-entry ledger that produces one concrete KPI value.

    Sequence:
        1. source_proposed       (resource lifecycle)
        2. source_confirmed
        3. source_profiled
        4. source_bronzed
        5. source_golded   ← carries the value
        6. kpi_proposed    ← references the gold via source_ids
    """
    company_id = uuid4()
    source_id = uuid4()
    domain_id = uuid4()
    person_id = uuid4()
    gold_artifact_id = uuid4()
    kpi_id = uuid4()
    expected_value = 142857.42  # arbitrary, distinctive

    payloads: list[tuple[str, str, dict[str, Any]]] = [
        (
            "execute",
            "active_deterministic",
            {
                "propose_entry_id": str(uuid4()),
                "tool": "emit_source_proposed",
                "args": {
                    "source_id": str(source_id),
                    "source_kind": "file",
                    "uri": "file:///tmp/q3.csv",
                    "added_via_flow": "drop_and_profile",
                    "suggested_domain": "finance",
                    "suggested_classification": "internal",
                },
                "result_ref": str(source_id),
            },
        ),
        (
            "execute",
            "active_deterministic",
            {
                "propose_entry_id": str(uuid4()),
                "tool": "emit_source_confirmed",
                "args": {
                    "source_id": str(source_id),
                    "confirmed_by_person": str(person_id),
                    "domain_id": str(domain_id),
                    "classification": "internal",
                },
                "result_ref": str(source_id),
            },
        ),
        (
            "execute",
            "active_deterministic",
            {
                "propose_entry_id": str(uuid4()),
                "tool": "emit_source_profiled",
                "args": {
                    "source_id": str(source_id),
                    "row_count": 200,
                    "column_count": 8,
                    "schema_hash": "0xdeadbeef",
                    "profile_ref": "p:profile-1",
                },
                "result_ref": "p:profile-1",
            },
        ),
        (
            "execute",
            "active_deterministic",
            {
                "propose_entry_id": str(uuid4()),
                "tool": "emit_source_bronzed",
                "args": {
                    "source_id": str(source_id),
                    "byte_count": 12000,
                    "row_count": 200,
                    "col_count": 8,
                    "schema_hash": "0xdeadbeef",
                    "mime": "text/csv",
                    "raw_uri": "file:///tmp/q3.csv",
                    "profiled_at": "2026-04-28T12:00:03Z",
                },
                "result_ref": str(source_id),
            },
        ),
        (
            "execute",
            "active_deterministic",
            {
                "propose_entry_id": str(uuid4()),
                "tool": "emit_source_golded",
                "args": {
                    "source_id": str(source_id),
                    "gold_artifact_id": str(gold_artifact_id),
                    "artifact_kind": "kpi",
                    "value": {"value": expected_value, "unit": "USD"},
                    "computed_at": "2026-04-28T12:00:04Z",
                },
                "result_ref": str(gold_artifact_id),
            },
        ),
        (
            "execute",
            "active_deterministic",
            {
                "propose_entry_id": str(uuid4()),
                "tool": "emit_kpi_proposed",
                "args": {
                    "kpi_id": str(kpi_id),
                    "label": "Q3 Net Revenue",
                    "formula": "sum(net_revenue) where quarter=Q3",
                    "source_ids": [str(source_id)],
                    "unit": "USD",
                    "owner_position": "finance.cfo",
                    "proposed_at": "2026-04-28T12:00:05Z",
                },
                "result_ref": str(kpi_id),
            },
        ),
    ]
    entries, terminal = _build_chain(company_id, payloads)
    path = tmp_path / "snapshot.jsonl"
    _write_jsonl(path, entries)

    return {
        "path": path,
        "company_id": str(company_id),
        "kpi_id": str(kpi_id),
        "expected_value": expected_value,
        "terminal_hash_hex": terminal.hex(),
        "entry_count": len(entries),
        "source_id": str(source_id),
        "gold_artifact_id": str(gold_artifact_id),
    }


@pytest.fixture
def broken_chain_snapshot(
    tmp_path: Path, synthetic_kpi_snapshot: dict[str, Any]
) -> Path:
    """The same snapshot, but with one entry's hash tampered.

    Drives the fail-closed test: replay must refuse to run.
    """
    src = synthetic_kpi_snapshot["path"]
    dst = tmp_path / "broken.jsonl"
    lines = src.read_text(encoding="utf-8").splitlines()
    # Tamper the 4th entry's hash field by flipping a hex digit.
    rec = json.loads(lines[3])
    h = rec["hash"]
    # Flip the first hex digit so the chain breaks deterministically.
    rec["hash"] = ("0" if h[0] != "0" else "1") + h[1:]
    lines[3] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dst


@pytest.fixture
def multi_tenant_snapshot(tmp_path: Path) -> dict[str, Any]:
    """Two tenants in one snapshot file.

    Each tenant has its own short chain. Auditor replay must
    refuse to auto-detect a tenant in this case (and require
    --tenant), and must successfully filter when --tenant is given.
    """
    tenant_a = uuid4()
    tenant_b = uuid4()
    a_kpi_id = uuid4()
    b_kpi_id = uuid4()
    a_source = uuid4()
    b_source = uuid4()
    a_gold = uuid4()
    b_gold = uuid4()

    def _kpi_chain(
        cid: UUID, src: UUID, gold: UUID, kpi: UUID, value: int
    ) -> list[tuple[str, str, dict[str, Any]]]:
        return [
            (
                "execute",
                "active_deterministic",
                {
                    "propose_entry_id": str(uuid4()),
                    "tool": "emit_source_golded",
                    "args": {
                        "source_id": str(src),
                        "gold_artifact_id": str(gold),
                        "artifact_kind": "kpi",
                        "value": {"value": value},
                        "computed_at": "2026-04-28T12:00:00Z",
                    },
                    "result_ref": str(gold),
                },
            ),
            (
                "execute",
                "active_deterministic",
                {
                    "propose_entry_id": str(uuid4()),
                    "tool": "emit_kpi_proposed",
                    "args": {
                        "kpi_id": str(kpi),
                        "label": "Tenant KPI",
                        "formula": "sum",
                        "source_ids": [str(src)],
                        "unit": "USD",
                        "proposed_at": "2026-04-28T12:00:01Z",
                    },
                    "result_ref": str(kpi),
                },
            ),
        ]

    a_entries, _ = _build_chain(
        tenant_a, _kpi_chain(tenant_a, a_source, a_gold, a_kpi_id, 1000)
    )
    b_entries, _ = _build_chain(
        tenant_b, _kpi_chain(tenant_b, b_source, b_gold, b_kpi_id, 2000)
    )
    path = tmp_path / "multi.jsonl"
    _write_jsonl(path, a_entries + b_entries)

    return {
        "path": path,
        "tenant_a": str(tenant_a),
        "tenant_b": str(tenant_b),
        "a_kpi_id": str(a_kpi_id),
        "b_kpi_id": str(b_kpi_id),
        "a_value": 1000,
        "b_value": 2000,
    }
