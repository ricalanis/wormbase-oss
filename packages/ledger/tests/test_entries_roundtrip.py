"""DB round-trip: every payload kind survives insert + select unchanged."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.hash_chain import GENESIS_PREV_HASH, compute_entry_hash
from wormbase_ledger.repo import fetch_entries, insert_entry

from .test_entries_payloads import CASES


@pytest.mark.asyncio
@pytest.mark.parametrize("model,data", CASES)
async def test_every_kind_roundtrips_in_db(
    test_database_url: str, model: type, data: dict[str, Any]
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    payload_obj = model(**data)
    serialized = payload_obj.model_dump(mode="json")
    entry = {
        "entry_id": uuid4(),
        "company_id": company_id,
        "seq": 1,
        "ts": datetime(2026, 4, 22, 12, 0, tzinfo=UTC),
        "kind": model.kind,
        "quadrant": "active_deterministic",
        "payload": serialized,
        "prev_hash": GENESIS_PREV_HASH,
    }
    entry["hash"] = compute_entry_hash(entry)

    async with session_scope(engine) as session:
        await insert_entry(session, entry)

    async with session_scope(engine) as session:
        rows = await fetch_entries(session, company_id)

    assert len(rows) == 1
    assert rows[0]["kind"] == model.kind
    assert rows[0]["quadrant"] == "active_deterministic"
    assert rows[0]["payload"] == serialized
    assert rows[0]["hash"] == entry["hash"]
