"""Full-chain verifier for a company's ledger.

Reads every entry for `company_id` in seq order, then defers to
`hash_chain.verify_chain` for the actual prev_hash + recomputed-hash walk.
Returns a structured report (ok, entries_checked, broken_at) so the CLI
and the downstream `make verify` target can render concise summaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from wormbase_ledger.db import session_scope
from wormbase_ledger.hash_chain import verify_chain
from wormbase_ledger.repo import fetch_entries


@dataclass(frozen=True)
class VerifyReport:
    ok: bool
    entries_checked: int
    broken_at: int | None


async def verify_company_chain(engine: AsyncEngine, company_id: UUID) -> VerifyReport:
    async with session_scope(engine) as session:
        rows = await fetch_entries(session, company_id)
    ok, broken_at = verify_chain(rows)
    return VerifyReport(ok=ok, entries_checked=len(rows), broken_at=broken_at)
