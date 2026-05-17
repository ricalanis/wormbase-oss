"""Snapshot file format + hash-chain verification.

Snapshot format (JSONL ledger snapshot)
=======================================

One ledger entry per line, JSON-encoded with the following shape::

    {
      "entry_id": "<uuid>",
      "company_id": "<uuid>",
      "seq": <int>,
      "ts": "<RFC 3339 with trailing Z>",
      "kind": "<entry kind>",
      "quadrant": "<quadrant>",
      "payload": { ... },
      "prev_hash": "<64-hex>",
      "hash": "<64-hex>"
    }

This is the same on-disk view the hosted plane materialises (one
entry → one row in the ``ledger`` SQL table); a tenant operator
exports it via ``wormbase-ledger snapshot --tenant <id> > snapshot.jsonl``
(see ``docs/oss-audit-replay.md``). Wire-event JSONL — the
``channel_adapter.emit_*`` events the sim-harness's wire-recorder
produces — is a different shape; see :mod:`wormbase_tools.wire_replay`
for that path.

Hash chain (vendored)
=====================

The verifier mirrors ``wormbase_ledger.hash_chain.verify_chain`` exactly:

* ``hash = sha256(canonical_json(entry minus hash field))``
* canonical JSON: UTF-8, sort_keys=True, no whitespace separators,
  UUIDs as strings, datetimes as RFC 3339 with trailing ``Z``,
  bytes as lowercase hex.

We re-implement these primitives here rather than importing
``wormbase_ledger`` so the auditor's pip install stays Postgres-free.
The vendored implementation is byte-compatible with the production
verifier (a contract test in ``tests/`` asserts this on every
snapshot the test suite produces).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID


GENESIS_PREV_HASH: bytes = b"\x00" * 32


class SnapshotError(Exception):
    """Raised when a snapshot is malformed, truncated, or chain-broken.

    Replay is fail-closed: any of these conditions exits the CLI with
    code 1 and writes a diagnostic to stderr.
    """


def _canonical_default(o: Any) -> Any:
    """Match wormbase_ledger.hash_chain._default exactly."""
    if isinstance(o, UUID):
        return str(o)
    if isinstance(o, datetime):
        if o.tzinfo is None:
            raise ValueError("datetimes must be tz-aware to be canonicalized")
        u = o.astimezone(UTC).replace(tzinfo=UTC)
        base = u.strftime("%Y-%m-%dT%H:%M:%S")
        frac = ""
        if u.microsecond:
            frac = f".{u.microsecond:06d}".rstrip("0").rstrip(".")
        return base + frac + "Z"
    if isinstance(o, (bytes, bytearray)):
        return bytes(o).hex()
    raise TypeError(f"Unserializable type: {type(o).__name__}")


def canonical_json(entry: dict[str, Any]) -> str:
    """Render ``entry`` (minus the ``hash`` field) as canonical UTF-8 JSON."""
    view = {k: v for k, v in entry.items() if k != "hash"}
    return json.dumps(
        view,
        sort_keys=True,
        separators=(",", ":"),
        default=_canonical_default,
        ensure_ascii=False,
    )


def compute_entry_hash(entry: dict[str, Any]) -> bytes:
    return hashlib.sha256(canonical_json(entry).encode("utf-8")).digest()


def _hex_to_bytes(s: Any) -> bytes:
    """Parse a hex-string hash field into bytes, raising SnapshotError on
    malformed input."""
    if not isinstance(s, str):
        raise SnapshotError(f"hash field must be a hex string, got {type(s).__name__}")
    try:
        b = bytes.fromhex(s)
    except ValueError as exc:
        raise SnapshotError(f"hash field is not valid hex: {s!r}") from exc
    if len(b) != 32:
        raise SnapshotError(
            f"hash field must decode to 32 bytes, got {len(b)} bytes"
        )
    return b


def _ts_from_str(s: Any) -> datetime:
    """Parse an RFC 3339 timestamp (trailing 'Z' allowed)."""
    if isinstance(s, datetime):
        if s.tzinfo is None:
            raise SnapshotError("ts must be tz-aware")
        return s
    if not isinstance(s, str):
        raise SnapshotError(f"ts must be a string, got {type(s).__name__}")
    try:
        # fromisoformat handles +00:00; convert trailing 'Z' first.
        normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
        out = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SnapshotError(f"ts is not RFC 3339: {s!r}") from exc
    if out.tzinfo is None:
        raise SnapshotError(f"ts must be tz-aware: {s!r}")
    return out.astimezone(UTC)


REQUIRED_ENTRY_FIELDS: tuple[str, ...] = (
    "entry_id",
    "company_id",
    "seq",
    "ts",
    "kind",
    "quadrant",
    "payload",
    "prev_hash",
    "hash",
)


def _parse_line(idx: int, line: str) -> dict[str, Any]:
    """Parse one JSONL line into a normalized entry envelope.

    Normalises ``prev_hash``/``hash`` from hex strings to bytes, ``ts``
    to a tz-aware datetime, and validates all required fields are
    present. Raises :class:`SnapshotError` on any defect — fail-closed.
    """
    try:
        rec = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SnapshotError(
            f"snapshot line {idx + 1} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(rec, dict):
        raise SnapshotError(
            f"snapshot line {idx + 1} is not a JSON object"
        )
    missing = [f for f in REQUIRED_ENTRY_FIELDS if f not in rec]
    if missing:
        raise SnapshotError(
            f"snapshot line {idx + 1} missing required fields: {missing}"
        )
    rec["prev_hash"] = _hex_to_bytes(rec["prev_hash"])
    rec["hash"] = _hex_to_bytes(rec["hash"])
    rec["ts"] = _ts_from_str(rec["ts"])
    return rec


def iter_snapshot(path: Path) -> Iterator[dict[str, Any]]:
    """Yield normalized ledger entries from a JSONL snapshot file."""
    if not path.exists():
        raise SnapshotError(f"snapshot file does not exist: {path}")
    with path.open("r", encoding="utf-8") as f:
        for idx, raw in enumerate(f):
            line = raw.strip()
            if not line:
                continue
            yield _parse_line(idx, line)


def load_snapshot(path: Path) -> list[dict[str, Any]]:
    """Load and validate a JSONL snapshot, returning entries sorted by seq."""
    entries = list(iter_snapshot(path))
    if not entries:
        raise SnapshotError(f"snapshot is empty: {path}")
    entries.sort(key=lambda e: int(e["seq"]))
    return entries


def verify_chain(entries: list[dict[str, Any]]) -> tuple[bytes, int]:
    """Walk the hash chain. Returns ``(terminal_hash, entry_count)``.

    Raises :class:`SnapshotError` on any chain break: missing prev_hash
    linkage, recomputed hash mismatch, or duplicate seq. Replay is
    fail-closed — broken chain ⇒ no KPI value is produced.
    """
    if not entries:
        raise SnapshotError("cannot verify empty snapshot")
    prev = GENESIS_PREV_HASH
    seen_seq: set[int] = set()
    for i, e in enumerate(entries):
        seq = int(e["seq"])
        if seq in seen_seq:
            raise SnapshotError(
                f"snapshot contains duplicate seq={seq} at index {i}"
            )
        seen_seq.add(seq)
        if e.get("prev_hash") != prev:
            raise SnapshotError(
                f"chain break at seq={seq} (index {i}): "
                "prev_hash does not match running chain head"
            )
        expected = compute_entry_hash(e)
        if e.get("hash") != expected:
            raise SnapshotError(
                f"chain break at seq={seq} (index {i}): "
                f"recomputed hash does not match stored hash "
                f"(expected {expected.hex()}, stored {e['hash'].hex()})"
            )
        prev = expected
    return prev, len(entries)


def filter_by_tenant(
    entries: list[dict[str, Any]], tenant_id: str | UUID | None
) -> list[dict[str, Any]]:
    """Return only entries whose ``company_id`` matches ``tenant_id``.

    If ``tenant_id`` is None, all entries are returned. Multi-tenant
    snapshots are technically possible (a hosted plane export of more
    than one tenant) but the auditor flow always pins to one tenant per
    replay invocation — verifying a single tenant's chain is the unit
    of trust.
    """
    if tenant_id is None:
        return entries
    target = str(tenant_id)
    return [e for e in entries if str(e.get("company_id")) == target]


__all__ = [
    "GENESIS_PREV_HASH",
    "REQUIRED_ENTRY_FIELDS",
    "SnapshotError",
    "canonical_json",
    "compute_entry_hash",
    "filter_by_tenant",
    "iter_snapshot",
    "load_snapshot",
    "verify_chain",
]
