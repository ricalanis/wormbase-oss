"""The single atomic write primitive used by every quadrant.

`write_primitive(propose, execute, verify, resolve)` appends exactly four
hash-chained ledger entries inside a single DB transaction. If `verify`
returns ``passed=False``, the entire transaction is rolled back via the
session_scope contextmanager (the function raises VerifyFailed; the
surrounding ``async with session_scope(...)`` rolls back).

Concurrency: writers serialize per company by issuing a SELECT … FOR UPDATE
on the company's tail row (when the backend supports row-level locks).
SQLite is single-writer by default so the lock is a no-op; Postgres uses real
row locks.

Optional kwargs (resolutions of Wave-2 review):
    timestamp : datetime | None
        Default now(UTC). Sim-clock controller (P5) passes explicit past
        timestamps for replay-friendly backdating.
    quadrant : Quadrant
        Default "active_deterministic". Worm classifier / channel adapter
        sets the quadrant at write time so projections can filter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wormbase_ledger.entries import Quadrant
from wormbase_ledger.errors import VerifyFailed
from wormbase_ledger.hash_chain import GENESIS_PREV_HASH, compute_entry_hash
from wormbase_ledger.schema import ledger


@dataclass(frozen=True)
class WriteResult:
    entry_ids: tuple[UUID, UUID, UUID, UUID]
    hashes: tuple[bytes, bytes, bytes, bytes]


async def _tail(session: AsyncSession, company_id: UUID) -> tuple[int, bytes]:
    """Return the (seq, hash) of the company's most recent entry, locking
    the row for update so concurrent writers serialize. On SQLite the lock
    clause is silently ignored; on Postgres it issues SELECT … FOR UPDATE."""
    bind = session.get_bind()
    dialect_name = getattr(bind, "dialect", None)
    dialect_name = dialect_name.name if dialect_name else ""

    stmt = (
        select(ledger.c.seq, ledger.c.hash)
        .where(ledger.c.company_id == company_id)
        .order_by(ledger.c.seq.desc())
        .limit(1)
    )
    if dialect_name == "postgresql":
        stmt = stmt.with_for_update()

    row = (await session.execute(stmt)).first()
    if row is None:
        return 0, GENESIS_PREV_HASH
    return int(row.seq), bytes(row.hash)


async def _append(
    session: AsyncSession,
    company_id: UUID,
    seq: int,
    prev_hash: bytes,
    kind: str,
    quadrant: str,
    payload: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "entry_id": uuid4(),
        "company_id": company_id,
        "seq": seq,
        "ts": now,
        "kind": kind,
        "quadrant": quadrant,
        "payload": payload,
        "prev_hash": prev_hash,
    }
    entry["hash"] = compute_entry_hash(entry)
    await session.execute(ledger.insert().values(**entry))
    return entry


async def write_primitive(
    session: AsyncSession,
    *,
    company_id: UUID,
    propose: dict[str, Any],
    execute_fn: Callable[[], dict[str, Any]],
    verify_fn: Callable[[dict[str, Any]], dict[str, Any]],
    resolve_fn: Callable[[dict[str, Any]], dict[str, Any]],
    timestamp: datetime | None = None,
    quadrant: Quadrant = "active_deterministic",
) -> WriteResult:
    """Atomically append a propose/execute/verify/resolve sequence."""
    now = timestamp if timestamp is not None else datetime.now(UTC)
    seq, prev_hash = await _tail(session, company_id)

    p = await _append(session, company_id, seq + 1, prev_hash, "propose", quadrant, propose, now)
    exec_payload = {"propose_entry_id": str(p["entry_id"]), **execute_fn()}
    e = await _append(
        session, company_id, seq + 2, p["hash"], "execute", quadrant, exec_payload, now
    )
    v_body = verify_fn(exec_payload)
    verify_payload = {"execute_entry_id": str(e["entry_id"]), **v_body}
    v = await _append(
        session, company_id, seq + 3, e["hash"], "verify", quadrant, verify_payload, now
    )
    if not verify_payload.get("passed"):
        raise VerifyFailed("verify step failed; rolling back")

    resolve_payload = {"verify_entry_id": str(v["entry_id"]), **resolve_fn(verify_payload)}
    r = await _append(
        session, company_id, seq + 4, v["hash"], "resolve", quadrant, resolve_payload, now
    )

    return WriteResult(
        entry_ids=(p["entry_id"], e["entry_id"], v["entry_id"], r["entry_id"]),
        hashes=(p["hash"], e["hash"], v["hash"], r["hash"]),
    )
