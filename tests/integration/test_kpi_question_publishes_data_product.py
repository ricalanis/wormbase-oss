"""F7 — KPI question → autonomous data product.

When the worm answers a `@WormBase what is …` question, it additionally
writes ``emit_data_product_proposed`` + ``emit_data_product_generated``
so the answer becomes addressable at ``/data-products/{id}``.

This test exercises ``service.publish_kpi_answer_data_product`` directly
(the production hook the future Q&A path will call). Container-free —
uses InMemoryLedger + LocalFsBackend.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from wormbase_core.service import publish_kpi_answer_data_product
from wormbase_core.storage import LocalFsBackend
from wormbase_ledger import InMemoryLedger

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_kpi_question_publishes_data_product(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("WORMBASE_OBJECT_STORE_URI", f"file://{tmp_path}")
    ledger = InMemoryLedger()
    company_id = uuid4()
    person_id = uuid4()

    dp_id, info = await publish_kpi_answer_data_product(
        ledger,
        company_id,
        question="what is our Q3 net revenue?",
        answer_html="<html>Q3 Net Revenue: $1.234M</html>",
        requested_by_person_id=person_id,
        citation_source_ids=[uuid4()],
        citation_source_hashes=["src-hash-q3-rev"],
    )

    assert dp_id is not None
    assert len(info["propose_entry_ids"]) == 4
    assert len(info["generate_entry_ids"]) == 4

    rows = await ledger.fetch(company_id)
    tools = [
        r["payload"].get("tool")
        for r in rows
        if r["kind"] == "execute"
    ]
    assert "emit_data_product_proposed" in tools
    assert "emit_data_product_generated" in tools

    # The generated entry's source_hashes must echo the citations the worm used.
    gen_args = next(
        r["payload"]["args"]
        for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_data_product_generated"
    )
    assert gen_args["source_hashes"] == ["src-hash-q3-rev"]
    # content_hash must be sha256 hex (64 chars).
    assert len(gen_args["content_hash"]) == 64


@pytest.mark.asyncio
async def test_kpi_data_product_is_replay_stable(
    tmp_path: Path, monkeypatch,
) -> None:
    """Two publishes of the same answer over distinct dp_ids both succeed."""
    monkeypatch.setenv("WORMBASE_OBJECT_STORE_URI", f"file://{tmp_path}")
    ledger = InMemoryLedger()
    company_id = uuid4()
    person_id = uuid4()

    answer = "<html>same answer</html>"
    dp1, info1 = await publish_kpi_answer_data_product(
        ledger,
        company_id,
        question="same?",
        answer_html=answer,
        requested_by_person_id=person_id,
    )
    dp2, info2 = await publish_kpi_answer_data_product(
        ledger,
        company_id,
        question="same?",
        answer_html=answer,
        requested_by_person_id=person_id,
    )
    assert dp1 != dp2
    # Same bytes → same content_hash.
    assert info1["content_hash"] == info2["content_hash"]
