"""Canonical JSON encoding + sha256 entry hashing + chain verification.

Hash semantics
--------------
For each entry we compute::

    hash = sha256(canonical_json(entry_minus_hash_field).encode("utf-8"))

This is **stronger** than the literal PRD §4.8 phrasing
(``sha256(prev_hash || entry_payload)``): we hash the canonical JSON of every
field of the entry except the hash itself. The `prev_hash` is therefore
included inside the hashed body (preserving chain semantics) along with
`entry_id`, `company_id`, `seq`, `ts`, `kind`, `quadrant`, and `payload`. Any
single-field tamper changes the hash. The Wave-2 review (2026-04-22) approved
this divergence; see ``docs/superpowers/notes/2026-04-22-wave2-plan-review.md``.

Canonical JSON rules
--------------------
- UTF-8, no whitespace separators (``,`` / ``:`` only), keys sorted ascending.
- Datetimes must be timezone-aware; serialized as RFC 3339 with trailing ``Z``.
- ``UUID`` → string; ``bytes`` → lowercase hex.
- The output is byte-identical for byte-identical inputs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

GENESIS_PREV_HASH: bytes = b"\x00" * 32


def _default(o: Any) -> Any:
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
    """Render `entry` (minus the `hash` field) as canonical UTF-8 JSON."""
    view = {k: v for k, v in entry.items() if k != "hash"}
    return json.dumps(
        view,
        sort_keys=True,
        separators=(",", ":"),
        default=_default,
        ensure_ascii=False,
    )


def compute_entry_hash(entry: dict[str, Any]) -> bytes:
    """Compute the 32-byte sha256 of `canonical_json(entry minus hash)`."""
    return hashlib.sha256(canonical_json(entry).encode("utf-8")).digest()


def verify_chain(entries: Iterable[dict[str, Any]]) -> tuple[bool, int | None]:
    """Walk `entries` (in seq order) and verify the hash chain.

    Returns
    -------
    (ok, broken_at)
        ``ok`` is True iff every entry's prev_hash matches the running chain
        head AND every entry's stored hash matches the recomputed hash.
        ``broken_at`` is the 0-based index of the first failing entry, or None.
    """
    prev = GENESIS_PREV_HASH
    for i, e in enumerate(entries):
        if e.get("prev_hash") != prev:
            return False, i
        expected = compute_entry_hash(e)
        if e.get("hash") != expected:
            return False, i
        prev = expected
    return True, None
