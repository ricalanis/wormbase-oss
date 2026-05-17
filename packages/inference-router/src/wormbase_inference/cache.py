"""Block E (cache half) — deterministic inference cache.

Backed by sqlite (single-file, simple, easy to wipe / refresh). Keyed on
``(prompt_hash, model)``. The cache is a substrate-stable layer: same
inputs always yield the same cached output regardless of process boot
order, so demo replays are hash-stable.

The hash is constructed from a canonical JSON of the request — ``messages``
(role + content), ``system``, ``model`` (resolved by the backend), and
``temperature`` — so calls that differ in any user-visible way miss the
cache and calls that are textually identical hit it.

Two implementations:

* :class:`SqliteInferenceCache` — production. Auto-creates the table.
* :class:`NullInferenceCache` — disables caching; used in tests and in
  contexts where determinism is not required (rare).

The router writes an ``inference_served`` ledger entry tagged
``served_by="cache"`` on every cache hit so audit trails distinguish
"answered fresh" from "answered from cache." That tagging happens in
:mod:`router`, not here — the cache itself is a pure key-value store.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Cache key helper — also exported at the public surface so test fakes
# can construct keys identically.
# ---------------------------------------------------------------------------


def make_cache_key(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    extra: dict[str, str] | None = None,
) -> str:
    """SHA256 hex over a canonical JSON of the inputs that define an answer.

    Same inputs → same key — by construction. The router writes this as
    the ``cache_key`` field of the ``inference_served`` payload so a
    ledger reader can correlate two ``inference_served`` rows that
    served the same logical request (one from Kimi, one from cache).
    """
    payload = {
        "model": model,
        "messages": messages,
        "temperature": round(float(temperature), 6),
        "extra": dict(sorted((extra or {}).items())),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# InferenceCache Protocol — minimal surface, one read + one write + one wipe.
# ---------------------------------------------------------------------------


@runtime_checkable
class InferenceCache(Protocol):
    def get(self, key: str) -> str | None: ...
    def put(self, key: str, value: str, *, model: str) -> None: ...
    def invalidate_all(self) -> int:
        """Wipe every entry; return the row count that was deleted."""
        ...


# ---------------------------------------------------------------------------
# NullInferenceCache — no-op fake; used by tests + opt-out path.
# ---------------------------------------------------------------------------


class NullInferenceCache:
    """Disables caching. Every ``get`` returns ``None``; ``put`` no-ops."""

    def get(self, key: str) -> str | None:  # noqa: D401 — Protocol shape
        return None

    def put(self, key: str, value: str, *, model: str) -> None:
        return None

    def invalidate_all(self) -> int:
        return 0


# ---------------------------------------------------------------------------
# SqliteInferenceCache — production default.
# ---------------------------------------------------------------------------


_SCHEMA = """
CREATE TABLE IF NOT EXISTS inference_cache (
    cache_key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    response TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


class SqliteInferenceCache:
    """sqlite-backed cache — single file, single table.

    Thread-safe: a single :class:`threading.Lock` serializes writes. The
    sqlite connection uses ``check_same_thread=False`` so an asyncio
    runtime can call ``get`` / ``put`` from any worker thread.

    Usage:

        cache = SqliteInferenceCache(Path("/var/wormbase/cache.sqlite"))
        if (hit := cache.get(k)) is not None:
            ...
        cache.put(k, response, model="kimi-k2.6:cloud")
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            isolation_level=None,  # autocommit
        )
        self._conn.execute(_SCHEMA)

    def get(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT response FROM inference_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        value = row[0]
        return value if isinstance(value, str) else None

    def put(self, key: str, value: str, *, model: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO inference_cache (cache_key, model, response, created_at)"
                " VALUES (?, ?, ?, ?)",
                (key, model, value, time.time()),
            )

    def invalidate_all(self) -> int:
        """Wipe every row; return the count that was deleted."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM inference_cache")
            return int(cur.rowcount or 0)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = [
    "InferenceCache",
    "NullInferenceCache",
    "SqliteInferenceCache",
    "make_cache_key",
]
