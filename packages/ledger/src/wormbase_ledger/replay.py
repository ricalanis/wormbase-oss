"""replay(engine, company_id, until_ts) -> ReplaySnapshot.

Builds projections deterministically from the ledger up to `until_ts`,
then hashes the projection bundle via canonical_json so two snapshots of the
same inputs produce byte-identical hashes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from wormbase_ledger.db import session_scope
from wormbase_ledger.hash_chain import canonical_json
from wormbase_ledger.projections import Projections, build_projections


@dataclass(frozen=True)
class ReplaySnapshot:
    projections: Projections
    hash_of_projections: bytes


def _hash(p: Projections) -> bytes:
    body = {
        "sources": p.sources,
        "memory": p.memory,
        "kpi_nodes": p.kpi_nodes,
        "ramp": p.ramp,
    }
    return hashlib.sha256(canonical_json(body).encode("utf-8")).digest()


async def replay(
    engine: AsyncEngine, company_id: UUID, until_ts: datetime
) -> ReplaySnapshot:
    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id, until_ts=until_ts)
    return ReplaySnapshot(projections=proj, hash_of_projections=_hash(proj))
