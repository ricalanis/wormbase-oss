from datetime import UTC, datetime
from uuid import UUID

from wormbase_ledger.hash_chain import (
    GENESIS_PREV_HASH,
    canonical_json,
    compute_entry_hash,
    verify_chain,
)

ENTRY = {
    "entry_id": UUID("0190a0a0-0000-7000-8000-000000000001"),
    "company_id": UUID("0190a0a0-0000-7000-8000-000000000002"),
    "seq": 1,
    "ts": datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC),
    "kind": "propose",
    "quadrant": "active_deterministic",
    "payload": {"b": 2, "a": 1},
    "prev_hash": b"\x00" * 32,
}


def test_canonical_json_sorts_keys_and_uses_z() -> None:
    js = canonical_json(ENTRY)
    assert js.startswith("{")
    assert '"a":1,"b":2' in js
    assert "2026-04-22T12:00:00Z" in js
    assert '"prev_hash":"' + "00" * 32 + '"' in js


def test_canonical_json_is_byte_stable() -> None:
    assert canonical_json(ENTRY) == canonical_json({**ENTRY})
    assert canonical_json(ENTRY).encode() == canonical_json(ENTRY).encode()


def test_canonical_json_excludes_hash_field() -> None:
    with_hash = {**ENTRY, "hash": b"\xff" * 32}
    assert canonical_json(with_hash) == canonical_json(ENTRY)


def test_genesis_prev_hash_is_32_zero_bytes() -> None:
    assert GENESIS_PREV_HASH == b"\x00" * 32


def test_compute_entry_hash_is_sha256_of_canonical_json() -> None:
    import hashlib

    h = compute_entry_hash(ENTRY)
    expected = hashlib.sha256(canonical_json(ENTRY).encode("utf-8")).digest()
    assert h == expected
    assert len(h) == 32


def test_compute_entry_hash_changes_with_any_field() -> None:
    h1 = compute_entry_hash(ENTRY)
    h2 = compute_entry_hash({**ENTRY, "seq": 2})
    assert h1 != h2


def test_verify_chain_accepts_valid_chain() -> None:
    e1 = {**ENTRY, "seq": 1, "prev_hash": GENESIS_PREV_HASH}
    h1 = compute_entry_hash(e1)
    e2 = {
        **ENTRY,
        "seq": 2,
        "prev_hash": h1,
        "entry_id": UUID("0190a0a0-0000-7000-8000-000000000003"),
    }
    h2 = compute_entry_hash(e2)
    chain = [{**e1, "hash": h1}, {**e2, "hash": h2}]
    ok, broken_at = verify_chain(chain)
    assert ok is True and broken_at is None


def test_verify_chain_detects_tamper() -> None:
    e1 = {**ENTRY, "prev_hash": GENESIS_PREV_HASH}
    h1 = compute_entry_hash(e1)
    tampered = {**e1, "hash": h1, "payload": {"a": 999}}
    ok, broken_at = verify_chain([tampered])
    assert ok is False and broken_at == 0
