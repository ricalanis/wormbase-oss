"""Tests for the data-product / notebook write orchestrators (F2)."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from wormbase_core.data_product_actions import (
    ReplayMismatchError,
    archive_data_product,
    archive_notebook,
    consume_data_product,
    generate_data_product,
    propose_data_product,
    propose_notebook,
    publish_notebook,
    replay_data_product,
    run_notebook,
    sign_notebook,
)
from wormbase_ledger import InMemoryLedger


@pytest.mark.asyncio
async def test_propose_data_product_lands_full_pevr() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    person_id = uuid4()

    dp_id, result = await propose_data_product(
        ledger,
        company_id,
        name="Q3 Net Revenue",
        kind="report",
        requested_by_person_id=person_id,
        sources_required=[],
    )

    rows = await ledger.fetch(company_id)
    assert len(rows) == 4  # propose / execute / verify / resolve
    kinds = [r["kind"] for r in rows]
    assert kinds == ["propose", "execute", "verify", "resolve"]
    assert rows[1]["payload"]["tool"] == "emit_data_product_proposed"
    assert rows[1]["payload"]["args"]["kind"] == "report"
    assert rows[1]["payload"]["args"]["data_product_id"] == str(dp_id)
    assert len(result.entry_ids) == 4


@pytest.mark.asyncio
async def test_propose_then_generate_chains() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    person_id = uuid4()

    dp_id, _ = await propose_data_product(
        ledger,
        company_id,
        name="Q3",
        kind="report",
        requested_by_person_id=person_id,
        sources_required=[],
    )
    gen_result = await generate_data_product(
        ledger,
        company_id,
        data_product_id=dp_id,
        contents_uri="file:///tmp/q3.html",
        content_hash="deadbeef" * 8,
        kind="report",
        source_hashes=["src1", "src2"],
        duration_ms=120,
    )

    rows = await ledger.fetch(company_id)
    # 8 rows total: 4 propose, 4 generate
    assert len(rows) == 8
    tools = [
        r["payload"].get("tool")
        for r in rows
        if r["kind"] == "execute"
    ]
    assert "emit_data_product_proposed" in tools
    assert "emit_data_product_generated" in tools
    assert len(gen_result.entry_ids) == 4


@pytest.mark.asyncio
async def test_consume_data_product_writes_consume_entry() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    dp_id = uuid4()
    person_id = uuid4()

    await consume_data_product(
        ledger,
        company_id,
        data_product_id=dp_id,
        consumed_by_person_id=person_id,
        surface="dashboard",
    )

    rows = await ledger.fetch(company_id)
    assert any(
        r["payload"].get("tool") == "emit_data_product_consumed"
        for r in rows
        if r["kind"] == "execute"
    )


@pytest.mark.asyncio
async def test_archive_data_product_writes_archive_entry() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    dp_id = uuid4()
    admin = uuid4()

    await archive_data_product(
        ledger,
        company_id,
        data_product_id=dp_id,
        archived_by=admin,
        reason="stale",
    )

    rows = await ledger.fetch(company_id)
    assert any(
        r["payload"].get("tool") == "emit_data_product_archived"
        for r in rows
        if r["kind"] == "execute"
    )


@pytest.mark.asyncio
async def test_propose_notebook_lands_full_pevr() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    person_id = uuid4()

    nb_id, result = await propose_notebook(
        ledger,
        company_id,
        name="CFO autoresearch",
        cells=[
            {"kind": "markdown", "source": "# Hypothesis"},
            {"kind": "code", "source": "x = 1"},
        ],
        kernel="python_local",
        proposed_by_person_id=person_id,
    )

    rows = await ledger.fetch(company_id)
    exec_rows = [r for r in rows if r["kind"] == "execute"]
    assert len(exec_rows) == 1
    assert exec_rows[0]["payload"]["tool"] == "emit_notebook_proposed"
    assert exec_rows[0]["payload"]["args"]["notebook_id"] == str(nb_id)
    assert len(result.entry_ids) == 4


@pytest.mark.asyncio
async def test_run_then_publish_notebook() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    nb_id = uuid4()
    person_id = uuid4()
    admin = uuid4()

    run_id, _ = await run_notebook(
        ledger,
        company_id,
        notebook_id=nb_id,
        cell_outputs=[{"value": 1}],
        cell_hashes=["h"],
        duration_ms=10,
        kernel_state_hash="k" * 64,
        status="ok",
    )
    await publish_notebook(
        ledger,
        company_id,
        notebook_id=nb_id,
        run_id=run_id,
        owner_person_id=person_id,
        version="1",
        published_by=admin,
    )

    rows = await ledger.fetch(company_id)
    tools = [
        r["payload"].get("tool")
        for r in rows
        if r["kind"] == "execute"
    ]
    assert "emit_notebook_run" in tools
    assert "emit_notebook_published" in tools


@pytest.mark.asyncio
async def test_archive_notebook_writes_archive_entry() -> None:
    ledger = InMemoryLedger()
    company_id = uuid4()
    nb_id = uuid4()
    admin = uuid4()

    await archive_notebook(
        ledger,
        company_id,
        notebook_id=nb_id,
        archived_by=admin,
        reason="deprecated",
    )

    rows = await ledger.fetch(company_id)
    assert any(
        r["payload"].get("tool") == "emit_notebook_archived"
        for r in rows
        if r["kind"] == "execute"
    )


# ---------------------------------------------------------------------------
# W2.A8 — Replay + Sign orchestrators
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_data_product_strict_match_writes_generate_cycle() -> None:
    """Strict replay with matching bytes must land a fresh generate cycle."""
    ledger = InMemoryLedger()
    company_id = uuid4()
    dp_id = uuid4()
    contents = b"<html>Q3 Net Revenue: $1.2M</html>"
    expected_hash = hashlib.sha256(contents).hexdigest()

    result = await replay_data_product(
        ledger,
        company_id,
        data_product_id=dp_id,
        original_content_hash=expected_hash,
        original_kind="report",
        source_hashes=["src1", "src2"],
        contents_bytes=contents,
        new_contents_uri="file:///tmp/replay.html",
    )

    assert result.matches_original is True
    assert result.content_hash == expected_hash
    assert len(result.entry_ids) == 4

    rows = await ledger.fetch(company_id)
    exec_rows = [r for r in rows if r["kind"] == "execute"]
    assert len(exec_rows) == 1
    assert exec_rows[0]["payload"]["tool"] == "emit_data_product_generated"
    assert exec_rows[0]["payload"]["args"]["content_hash"] == expected_hash
    assert exec_rows[0]["payload"]["args"]["generated_by"] == "replay"


@pytest.mark.asyncio
async def test_replay_data_product_strict_mismatch_raises_no_write() -> None:
    """Strict replay with drifted bytes must raise and write nothing."""
    ledger = InMemoryLedger()
    company_id = uuid4()
    dp_id = uuid4()
    contents = b"<html>drifted</html>"
    bogus_expected = "0" * 64

    with pytest.raises(ReplayMismatchError) as exc_info:
        await replay_data_product(
            ledger,
            company_id,
            data_product_id=dp_id,
            original_content_hash=bogus_expected,
            original_kind="report",
            source_hashes=[],
            contents_bytes=contents,
            new_contents_uri="file:///tmp/replay.html",
        )

    assert exc_info.value.expected == bogus_expected
    assert exc_info.value.actual == hashlib.sha256(contents).hexdigest()
    # No ledger entry: the strict assertion happens before the write.
    rows = await ledger.fetch(company_id)
    assert rows == []


@pytest.mark.asyncio
async def test_sign_notebook_emits_published_with_deterministic_receipt() -> None:
    """sign_notebook lands an emit_notebook_published + a deterministic
    signature receipt."""
    ledger = InMemoryLedger()
    company_id = uuid4()
    nb_id = uuid4()
    run_id = uuid4()
    owner = uuid4()
    admin = uuid4()

    write_result, receipt = await sign_notebook(
        ledger,
        company_id,
        notebook_id=nb_id,
        run_id=run_id,
        owner_person_id=owner,
        version="1",
        signed_by=admin,
    )

    assert len(write_result.entry_ids) == 4
    assert receipt["notebook_id"] == str(nb_id)
    assert receipt["signed_by"] == str(admin)
    assert receipt["signature_hash"] == hashlib.sha256(
        f"{nb_id}|{run_id}|{owner}|1|{admin}".encode("utf-8"),
    ).hexdigest()

    rows = await ledger.fetch(company_id)
    assert any(
        r["payload"].get("tool") == "emit_notebook_published"
        for r in rows
        if r["kind"] == "execute"
    )

    # Determinism: same inputs → same receipt hash.
    _, receipt2 = await sign_notebook(
        ledger,
        company_id,
        notebook_id=nb_id,
        run_id=run_id,
        owner_person_id=owner,
        version="1",
        signed_by=admin,
    )
    assert receipt2["signature_hash"] == receipt["signature_hash"]
