"""Public Ledger / InMemoryLedger classes for downstream consumers.

`Ledger` wraps the async DB-backed primitives so worm-core / channel-adapter
have a single object to inject. `InMemoryLedger` is a pytest fixture that
records writes in process memory — useful for unit-testing higher layers
without spinning up a DB.

Both expose the same async surface::

    await ledger.write(...)            # propose/execute/verify/resolve
    await ledger.fetch(company_id)     # list entries
    await ledger.verify(company_id)    # VerifyReport
    await ledger.replay(company_id, until_ts)  # ReplaySnapshot
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.entries import Quadrant
from wormbase_ledger.errors import VerifyFailed
from wormbase_ledger.hash_chain import (
    GENESIS_PREV_HASH,
    canonical_json,
    compute_entry_hash,
    verify_chain,
)
from wormbase_ledger.projections import Projections, build_projections
from wormbase_ledger.replay import ReplaySnapshot, replay
from wormbase_ledger.repo import fetch_entries, get_entry_by_id
from wormbase_ledger.verify import VerifyReport, verify_company_chain
from wormbase_ledger.write_primitive import WriteResult, write_primitive

# ---------------------------------------------------------------------------
# Async DB-backed Ledger
# ---------------------------------------------------------------------------


class Ledger:
    """DB-backed async ledger client.

    Construct with either a SQLAlchemy URL string or a pre-built
    AsyncEngine. The engine is cached so multiple Ledger instances against
    the same URL share a connection pool.
    """

    def __init__(self, url_or_engine: str | AsyncEngine) -> None:
        self._engine: AsyncEngine = (
            url_or_engine
            if isinstance(url_or_engine, AsyncEngine)
            else get_engine(url_or_engine)
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def write(
        self,
        *,
        company_id: UUID,
        propose: dict[str, Any],
        execute_fn: Callable[[], dict[str, Any]],
        verify_fn: Callable[[dict[str, Any]], dict[str, Any]],
        resolve_fn: Callable[[dict[str, Any]], dict[str, Any]],
        timestamp: datetime | None = None,
        quadrant: Quadrant = "active_deterministic",
    ) -> WriteResult:
        async with session_scope(self._engine) as session:
            return await write_primitive(
                session,
                company_id=company_id,
                propose=propose,
                execute_fn=execute_fn,
                verify_fn=verify_fn,
                resolve_fn=resolve_fn,
                timestamp=timestamp,
                quadrant=quadrant,
            )

    async def fetch(
        self, company_id: UUID, until_ts: datetime | None = None
    ) -> list[dict[str, Any]]:
        async with session_scope(self._engine) as session:
            return await fetch_entries(session, company_id, until_ts=until_ts)

    async def get_entry(
        self, company_id: UUID, entry_id: UUID
    ) -> dict[str, Any] | None:
        """Direct O(1) lookup of a single ledger entry by id (tenant-scoped).

        Returns the same normalized row shape as ``fetch`` (a list of one)
        or None when the entry does not exist for ``company_id``. Callers
        that previously iterated ``fetch(company_id)`` for entry-id
        resolution should prefer this method — production-Postgres runs
        an indexed primary-key lookup instead of full-tenant scan.
        """
        async with session_scope(self._engine) as session:
            return await get_entry_by_id(session, company_id, entry_id)

    async def verify(self, company_id: UUID) -> VerifyReport:
        return await verify_company_chain(self._engine, company_id)

    async def replay(self, company_id: UUID, until_ts: datetime) -> ReplaySnapshot:
        return await replay(self._engine, company_id, until_ts)

    async def projections(
        self, company_id: UUID, until_ts: datetime | None = None
    ) -> Projections:
        async with session_scope(self._engine) as session:
            return await build_projections(session, company_id, until_ts=until_ts)

    async def dispose(self) -> None:
        await self._engine.dispose()


# ---------------------------------------------------------------------------
# In-process InMemoryLedger
# ---------------------------------------------------------------------------


@dataclass
class InMemoryLedger:
    """In-process ledger with the same surface as Ledger.

    Designed for unit tests of higher layers (worm-core, channel-adapter)
    that want to assert "the worm wrote this entry" without spinning up
    a database. Hash semantics match the real ledger byte-for-byte.
    """

    _entries: dict[UUID, list[dict[str, Any]]] = field(default_factory=dict)

    async def write(
        self,
        *,
        company_id: UUID,
        propose: dict[str, Any],
        execute_fn: Callable[[], dict[str, Any]],
        verify_fn: Callable[[dict[str, Any]], dict[str, Any]],
        resolve_fn: Callable[[dict[str, Any]], dict[str, Any]],
        timestamp: datetime | None = None,
        quadrant: Quadrant = "active_deterministic",
    ) -> WriteResult:
        now = timestamp if timestamp is not None else datetime.now(UTC)
        rows = self._entries.setdefault(company_id, [])
        seq = rows[-1]["seq"] if rows else 0
        prev_hash = rows[-1]["hash"] if rows else GENESIS_PREV_HASH

        def _append(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
            nonlocal seq, prev_hash
            seq += 1
            entry = {
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
            rows.append(entry)
            prev_hash = entry["hash"]
            return entry

        p = _append("propose", propose)
        exec_payload = {"propose_entry_id": str(p["entry_id"]), **execute_fn()}
        e = _append("execute", exec_payload)
        v_body = verify_fn(exec_payload)
        verify_payload = {"execute_entry_id": str(e["entry_id"]), **v_body}
        v = _append("verify", verify_payload)
        if not verify_payload.get("passed"):
            # Roll back: drop the 3 entries we just appended.
            del rows[-3:]
            raise VerifyFailed("verify step failed; rolling back")
        resolve_payload = {"verify_entry_id": str(v["entry_id"]), **resolve_fn(verify_payload)}
        r = _append("resolve", resolve_payload)
        return WriteResult(
            entry_ids=(p["entry_id"], e["entry_id"], v["entry_id"], r["entry_id"]),
            hashes=(p["hash"], e["hash"], v["hash"], r["hash"]),
        )

    async def fetch(
        self, company_id: UUID, until_ts: datetime | None = None
    ) -> list[dict[str, Any]]:
        rows = list(self._entries.get(company_id, []))
        if until_ts is not None:
            rows = [r for r in rows if r["ts"] <= until_ts]
        return rows

    async def get_entry(
        self, company_id: UUID, entry_id: UUID
    ) -> dict[str, Any] | None:
        """Mirrors the DB-backed ``Ledger.get_entry`` surface.

        Linear scan over the in-memory company list — acceptable for
        unit-test fixtures where the row count is bounded. Production
        callers use the DB-backed path which runs an indexed primary
        key lookup.
        """
        target = str(entry_id)
        for entry in self._entries.get(company_id, []):
            eid = entry.get("entry_id")
            if eid is not None and str(eid) == target:
                return entry
        return None

    async def verify(self, company_id: UUID) -> VerifyReport:
        rows = await self.fetch(company_id)
        ok, broken_at = verify_chain(rows)
        return VerifyReport(ok=ok, entries_checked=len(rows), broken_at=broken_at)

    async def replay(self, company_id: UUID, until_ts: datetime) -> ReplaySnapshot:
        # Build projections by hand using the same builder semantics as the
        # DB-backed path. The seed-state and final assembly are extracted to
        # `_initial_projection_state` and `_state_to_projections` so the two
        # paths cannot drift (O-A1).
        from wormbase_ledger.projections.builder import (
            _apply_execute,
            _apply_pevr_envelope,
            _initial_projection_state,
            _state_to_projections,
        )

        rows = await self.fetch(company_id, until_ts=until_ts)
        state: dict[str, Any] = _initial_projection_state()
        for e in rows:
            k = e["kind"]
            # Wave 3 Task 3 — agent_query + credential PEVR cycles fold
            # at every envelope phase via shape detection. Mirrors
            # build_projections.
            if k in ("propose", "execute", "verify", "resolve"):
                _apply_pevr_envelope(e, state)
            if k == "execute":
                _apply_execute(e, state)
            elif k in ("chat_received", "chat_sent"):
                state["chat_count"] += 1
            elif k in (
                "chat_reply_proposed",
                "chat_reply_executed",
                "chat_reply_verified",
                "chat_reply_resolved",
            ):
                # v1: chat_reply_* entries are audit-only; no projection table fold.
                # Mirrors build_projections @ packages/ledger/src/wormbase_ledger/
                # projections/builder.py (kept in sync by O-A1).
                pass
            elif k == "resolve":
                state["resolve_count"] += 1
        proj = _state_to_projections(state)
        # Hash body is intentionally the original four-field shape so
        # existing snapshot hashes remain stable. Folding additional
        # projection tables into the hash is a separate doctrine call.
        body = {
            "sources": proj.sources,
            "memory": proj.memory,
            "kpi_nodes": proj.kpi_nodes,
            "ramp": proj.ramp,
        }
        return ReplaySnapshot(
            projections=proj,
            hash_of_projections=hashlib.sha256(
                canonical_json(body).encode("utf-8")
            ).digest(),
        )


__all__ = ["InMemoryLedger", "Ledger"]
