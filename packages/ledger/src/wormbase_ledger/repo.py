"""Thin async repository layer over the `ledger` table.

`insert_entry` writes a single row; `fetch_entries` returns all entries for a
company in seq order, optionally filtered by `until_ts`. Returned rows are
plain dicts (mapping column names → values) so callers can compute hashes
without needing SQLAlchemy ORM objects.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wormbase_ledger.schema import ledger


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Ensure ts is tz-aware and prev_hash/hash are bytes (SQLite returns them
    as memoryview-ish objects; coerce to plain bytes for stable comparison)."""
    out: dict[str, Any] = dict(row)
    ts = out.get("ts")
    if isinstance(ts, datetime) and ts.tzinfo is None:
        out["ts"] = ts.replace(tzinfo=UTC)
    for k in ("prev_hash", "hash"):
        v = out.get(k)
        if v is not None and not isinstance(v, bytes):
            out[k] = bytes(v)
    return out


async def insert_entry(session: AsyncSession, entry: dict[str, Any]) -> None:
    await session.execute(ledger.insert().values(**entry))


async def fetch_entries(
    session: AsyncSession, company_id: UUID, until_ts: datetime | None = None
) -> list[dict[str, Any]]:
    stmt = select(ledger).where(ledger.c.company_id == company_id)
    if until_ts is not None:
        stmt = stmt.where(ledger.c.ts <= until_ts)
    stmt = stmt.order_by(ledger.c.seq.asc())
    rows = (await session.execute(stmt)).mappings().all()
    return [_normalize_row(dict(r)) for r in rows]


async def get_entry_by_id(
    session: AsyncSession, company_id: UUID, entry_id: UUID
) -> dict[str, Any] | None:
    """Return a single ledger entry by ``(entry_id, company_id)`` or None.

    O(1) direct lookup (indexed primary key on ``entry_id`` + tenant
    scoping on ``company_id``) — used by callers that need a single
    entry without paginating ``fetch_entries``. Returns the same
    normalized row shape (tz-aware ts, bytes for hashes) as
    ``fetch_entries`` so downstream callers can swap iteration for
    direct lookup without changing comparison semantics.
    """
    stmt = (
        select(ledger)
        .where(ledger.c.entry_id == entry_id)
        .where(ledger.c.company_id == company_id)
        .limit(1)
    )
    row = (await session.execute(stmt)).mappings().first()
    if row is None:
        return None
    return _normalize_row(dict(row))
