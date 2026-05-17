"""Unit tests for the pure-Python replay path."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from wormbase_tools.replay import (
    ReplayError,
    replay_snapshot,
    replay_to_json,
)
from wormbase_tools.snapshot import (
    SnapshotError,
    canonical_json,
    compute_entry_hash,
    load_snapshot,
    verify_chain,
)


def test_load_snapshot_returns_sorted_entries(synthetic_kpi_snapshot: dict[str, Any]) -> None:
    entries = load_snapshot(synthetic_kpi_snapshot["path"])
    assert len(entries) == synthetic_kpi_snapshot["entry_count"]
    seqs = [int(e["seq"]) for e in entries]
    assert seqs == sorted(seqs)
    assert seqs[0] == 1


def test_verify_chain_passes_on_canonical_snapshot(
    synthetic_kpi_snapshot: dict[str, Any]
) -> None:
    entries = load_snapshot(synthetic_kpi_snapshot["path"])
    terminal, count = verify_chain(entries)
    assert count == synthetic_kpi_snapshot["entry_count"]
    assert terminal.hex() == synthetic_kpi_snapshot["terminal_hash_hex"]


def test_canonical_json_is_byte_stable() -> None:
    """Canonical JSON encoding must produce identical bytes for identical
    input — this is the foundation of replay determinism."""
    e = {
        "entry_id": "11111111-1111-1111-1111-111111111111",
        "company_id": "22222222-2222-2222-2222-222222222222",
        "seq": 1,
        "ts": "2026-04-28T12:00:00Z",
        "kind": "execute",
        "quadrant": "active_deterministic",
        "payload": {"b": 2, "a": 1, "c": [3, 1, 2]},
        "prev_hash": b"\x00" * 32,
    }
    s1 = canonical_json(e)
    s2 = canonical_json(e)
    assert s1 == s2
    # Bytes must hash identically.
    h1 = compute_entry_hash(e)
    h2 = compute_entry_hash(e)
    assert h1 == h2


def test_replay_returns_byte_identical_kpi_value(
    synthetic_kpi_snapshot: dict[str, Any]
) -> None:
    """Acceptance: replay reproduces the live KPI value bit-for-bit."""
    result = replay_snapshot(
        synthetic_kpi_snapshot["path"],
        tenant_id=synthetic_kpi_snapshot["company_id"],
        kpi_id=synthetic_kpi_snapshot["kpi_id"],
    )
    assert result.value == synthetic_kpi_snapshot["expected_value"]
    assert result.terminal_hash_hex == synthetic_kpi_snapshot["terminal_hash_hex"]
    assert result.entry_count == synthetic_kpi_snapshot["entry_count"]


def test_replay_provenance_trail_is_deterministic(
    synthetic_kpi_snapshot: dict[str, Any]
) -> None:
    """Provenance trail must list the contributing entry ids — auditor
    can show *which* ledger entries produced *which* KPI value."""
    r1 = replay_snapshot(
        synthetic_kpi_snapshot["path"],
        tenant_id=synthetic_kpi_snapshot["company_id"],
        kpi_id=synthetic_kpi_snapshot["kpi_id"],
    )
    r2 = replay_snapshot(
        synthetic_kpi_snapshot["path"],
        tenant_id=synthetic_kpi_snapshot["company_id"],
        kpi_id=synthetic_kpi_snapshot["kpi_id"],
    )
    assert r1.contributing_entry_ids == r2.contributing_entry_ids
    assert len(r1.contributing_entry_ids) >= 2  # gold + kpi_proposed


def test_replay_fails_closed_on_chain_break(broken_chain_snapshot: Path) -> None:
    """A tampered hash in the snapshot must abort replay (fail-closed)."""
    with pytest.raises(SnapshotError) as exc_info:
        replay_snapshot(broken_chain_snapshot, tenant_id=None, kpi_id="any")
    assert "chain break" in str(exc_info.value).lower() or "hash" in str(exc_info.value).lower()


def test_replay_fails_on_missing_kpi(synthetic_kpi_snapshot: dict[str, Any]) -> None:
    with pytest.raises(ReplayError) as exc_info:
        replay_snapshot(
            synthetic_kpi_snapshot["path"],
            tenant_id=synthetic_kpi_snapshot["company_id"],
            kpi_id="nonexistent-kpi-id",
        )
    assert "not found" in str(exc_info.value).lower()


def test_replay_fails_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError):
        replay_snapshot(
            tmp_path / "nonexistent.jsonl", tenant_id=None, kpi_id="any"
        )


def test_replay_fails_on_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    with pytest.raises(SnapshotError):
        replay_snapshot(p, tenant_id=None, kpi_id="any")


def test_replay_fails_on_malformed_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    p.write_text("not valid json\n", encoding="utf-8")
    with pytest.raises(SnapshotError):
        replay_snapshot(p, tenant_id=None, kpi_id="any")


def test_replay_fails_on_missing_required_fields(tmp_path: Path) -> None:
    """Missing required fields must abort replay before chain check."""
    p = tmp_path / "bad.jsonl"
    p.write_text(json.dumps({"entry_id": "x", "seq": 1}) + "\n", encoding="utf-8")
    with pytest.raises(SnapshotError) as exc_info:
        replay_snapshot(p, tenant_id=None, kpi_id="any")
    assert "missing" in str(exc_info.value).lower()


def test_replay_auto_detects_single_tenant(synthetic_kpi_snapshot: dict[str, Any]) -> None:
    """When the snapshot has exactly one tenant, --tenant is optional."""
    result = replay_snapshot(
        synthetic_kpi_snapshot["path"],
        tenant_id=None,
        kpi_id=synthetic_kpi_snapshot["kpi_id"],
    )
    assert result.tenant_id == synthetic_kpi_snapshot["company_id"]
    assert result.value == synthetic_kpi_snapshot["expected_value"]


def test_replay_refuses_ambiguous_tenant(multi_tenant_snapshot: dict[str, Any]) -> None:
    """Two tenants in one snapshot ⇒ caller must pass --tenant."""
    with pytest.raises(ReplayError) as exc_info:
        replay_snapshot(
            multi_tenant_snapshot["path"],
            tenant_id=None,
            kpi_id=multi_tenant_snapshot["a_kpi_id"],
        )
    assert "multiple tenants" in str(exc_info.value).lower()


def test_replay_filters_by_tenant_id(multi_tenant_snapshot: dict[str, Any]) -> None:
    """With --tenant, replay isolates to one tenant cleanly."""
    a = replay_snapshot(
        multi_tenant_snapshot["path"],
        tenant_id=multi_tenant_snapshot["tenant_a"],
        kpi_id=multi_tenant_snapshot["a_kpi_id"],
    )
    assert a.value == multi_tenant_snapshot["a_value"]
    b = replay_snapshot(
        multi_tenant_snapshot["path"],
        tenant_id=multi_tenant_snapshot["tenant_b"],
        kpi_id=multi_tenant_snapshot["b_kpi_id"],
    )
    assert b.value == multi_tenant_snapshot["b_value"]
    # Cross-tenant lookup must miss.
    with pytest.raises(ReplayError):
        replay_snapshot(
            multi_tenant_snapshot["path"],
            tenant_id=multi_tenant_snapshot["tenant_a"],
            kpi_id=multi_tenant_snapshot["b_kpi_id"],
        )


def test_replay_to_json_emits_structured_result(
    synthetic_kpi_snapshot: dict[str, Any]
) -> None:
    js = replay_to_json(
        synthetic_kpi_snapshot["path"],
        tenant_id=synthetic_kpi_snapshot["company_id"],
        kpi_id=synthetic_kpi_snapshot["kpi_id"],
    )
    parsed = json.loads(js)
    assert parsed["kpi_id"] == synthetic_kpi_snapshot["kpi_id"]
    assert parsed["value"] == synthetic_kpi_snapshot["expected_value"]
    assert parsed["terminal_hash"] == synthetic_kpi_snapshot["terminal_hash_hex"]


def test_replay_completes_under_10s_for_large_snapshot(tmp_path: Path) -> None:
    """Acceptance: replay completes in <10s on stock laptop for 1000-entry snapshot."""
    # Build 1000-entry chain via the conftest helper.
    from tests.conftest import _build_chain, _write_jsonl
    from uuid import uuid4

    company_id = uuid4()
    source_id = uuid4()
    gold_id = uuid4()
    kpi_id = uuid4()

    payloads: list[tuple[str, str, dict[str, Any]]] = []
    # Pad with cheap chat_received entries (the bulk of any real
    # ledger), with a single source_golded + kpi_proposed at the end.
    for i in range(998):
        payloads.append(
            (
                "chat_received",
                "passive_probabilistic",
                {
                    "channel_id": f"C-{i % 10}",
                    "message_id": f"m-{i}",
                    "sender_person": str(uuid4()),
                    "text": f"chat number {i}",
                    "classification": "internal",
                },
            )
        )
    payloads.append(
        (
            "execute",
            "active_deterministic",
            {
                "propose_entry_id": str(uuid4()),
                "tool": "emit_source_golded",
                "args": {
                    "source_id": str(source_id),
                    "gold_artifact_id": str(gold_id),
                    "artifact_kind": "kpi",
                    "value": {"value": 99.99},
                    "computed_at": "2026-04-28T12:00:00Z",
                },
                "result_ref": str(gold_id),
            },
        )
    )
    payloads.append(
        (
            "execute",
            "active_deterministic",
            {
                "propose_entry_id": str(uuid4()),
                "tool": "emit_kpi_proposed",
                "args": {
                    "kpi_id": str(kpi_id),
                    "label": "Big KPI",
                    "formula": "sum",
                    "source_ids": [str(source_id)],
                    "unit": "USD",
                    "proposed_at": "2026-04-28T12:00:01Z",
                },
                "result_ref": str(kpi_id),
            },
        )
    )
    entries, _ = _build_chain(company_id, payloads)
    path = tmp_path / "big.jsonl"
    _write_jsonl(path, entries)

    started = time.perf_counter()
    result = replay_snapshot(path, tenant_id=str(company_id), kpi_id=str(kpi_id))
    elapsed = time.perf_counter() - started

    assert result.value == 99.99
    assert result.entry_count == 1000
    assert elapsed < 10.0, f"replay took {elapsed:.2f}s, exceeds 10s budget"


def test_value_normalisation_handles_dict_and_scalar() -> None:
    from wormbase_tools.projections.kpis import _normalize_value

    assert _normalize_value(42) == 42
    assert _normalize_value(3.14) == 3.14
    assert _normalize_value("hi") == "hi"
    assert _normalize_value(None) is None
    assert _normalize_value({"value": 7}) == 7
    assert _normalize_value({"only": "one"}) == "one"
    # multi-key dict ⇒ canonical JSON string (deterministic surface)
    out = _normalize_value({"b": 2, "a": 1})
    assert out == '{"a":1,"b":2}'
