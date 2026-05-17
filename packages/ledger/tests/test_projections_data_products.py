"""Data-product + notebook projection replay tests (Block F of the PRD).

Each test drives the canonical write_primitive (`propose → execute → verify
→ resolve`) so the resulting `execute` envelope carries
`payload["tool"] == "emit_<kind>"`, then folds the ledger via
`build_projections` and asserts on the resulting collections.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import build_projections
from wormbase_ledger.write_primitive import write_primitive


def _verify_pass(_r: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [], "passed": True}


def _resolve_keep(_v: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": "keep", "rationale": "ok"}


# ---------------------------------------------------------------------------
# Emit helpers
# ---------------------------------------------------------------------------


async def _emit_dp_proposed(
    engine: Any,
    *,
    company_id: UUID,
    data_product_id: UUID,
    name: str = "Q3 Net Revenue",
    kind: str = "report",
    requested_by_person_id: UUID,
    sources_required: list[UUID] | None = None,
    domain_id: UUID | None = None,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "data_product_proposed",
                "ref_id": str(data_product_id),
                "reason": "kpi question → data product",
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "emit_data_product_proposed",
                "args": {
                    "data_product_id": str(data_product_id),
                    "name": name,
                    "kind": kind,
                    "requested_by_person_id": str(requested_by_person_id),
                    "sources_required": [str(s) for s in (sources_required or [])],
                    "domain_id": str(domain_id) if domain_id else None,
                    "parameters": {},
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_dp_generated(
    engine: Any,
    *,
    company_id: UUID,
    data_product_id: UUID,
    contents_uri: str = "s3://wb/dp/1.html",
    content_hash: str = "deadbeef" * 8,
    kind: str = "report",
    source_hashes: list[str] | None = None,
    duration_ms: int = 1000,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "data_product_generated",
                "ref_id": str(data_product_id),
                "reason": "render artifact",
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "emit_data_product_generated",
                "args": {
                    "data_product_id": str(data_product_id),
                    "contents_uri": contents_uri,
                    "content_hash": content_hash,
                    "kind": kind,
                    "source_hashes": list(source_hashes or []),
                    "generated_by": "worm",
                    "duration_ms": duration_ms,
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_dp_consumed(
    engine: Any,
    *,
    company_id: UUID,
    data_product_id: UUID,
    person_id: UUID,
    surface: str = "dashboard",
    channel: str | None = None,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "data_product_consumed",
                "ref_id": str(data_product_id),
                "reason": "view",
                "proposed_by": str(person_id),
            },
            execute_fn=lambda: {
                "tool": "emit_data_product_consumed",
                "args": {
                    "data_product_id": str(data_product_id),
                    "consumed_by_person_id": str(person_id),
                    "surface": surface,
                    "channel": channel,
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_dp_archived(
    engine: Any,
    *,
    company_id: UUID,
    data_product_id: UUID,
    archived_by: UUID,
    reason: str = "stale",
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "data_product_archived",
                "ref_id": str(data_product_id),
                "reason": reason,
                "proposed_by": str(archived_by),
            },
            execute_fn=lambda: {
                "tool": "emit_data_product_archived",
                "args": {
                    "data_product_id": str(data_product_id),
                    "archived_by": str(archived_by),
                    "reason": reason,
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_nb_proposed(
    engine: Any,
    *,
    company_id: UUID,
    notebook_id: UUID,
    name: str = "CFO autoresearch",
    kernel: str = "python_local",
    proposed_by_person_id: UUID,
    domain_id: UUID | None = None,
    cells: list[dict[str, Any]] | None = None,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "notebook_proposed",
                "ref_id": str(notebook_id),
                "reason": "autoresearch keep → notebook",
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "emit_notebook_proposed",
                "args": {
                    "notebook_id": str(notebook_id),
                    "name": name,
                    "cells": cells or [{"kind": "markdown", "source": "# X"}],
                    "kernel": kernel,
                    "proposed_by_person_id": str(proposed_by_person_id),
                    "domain_id": str(domain_id) if domain_id else None,
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_nb_run(
    engine: Any,
    *,
    company_id: UUID,
    notebook_id: UUID,
    run_id: UUID,
    status: str = "ok",
    duration_ms: int = 100,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "notebook_run",
                "ref_id": str(notebook_id),
                "reason": "run",
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "emit_notebook_run",
                "args": {
                    "notebook_id": str(notebook_id),
                    "run_id": str(run_id),
                    "cell_outputs": [{"value": 1}],
                    "cell_hashes": ["h1"],
                    "duration_ms": duration_ms,
                    "kernel_state_hash": "k" * 64,
                    "status": status,
                    "run_by": "worm",
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_nb_published(
    engine: Any,
    *,
    company_id: UUID,
    notebook_id: UUID,
    run_id: UUID,
    owner_person_id: UUID,
    version: str = "1",
    published_by: UUID,
    domain_id: UUID | None = None,
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "notebook_published",
                "ref_id": str(notebook_id),
                "reason": "publish",
                "proposed_by": str(published_by),
            },
            execute_fn=lambda: {
                "tool": "emit_notebook_published",
                "args": {
                    "notebook_id": str(notebook_id),
                    "run_id": str(run_id),
                    "owner_person_id": str(owner_person_id),
                    "domain_id": str(domain_id) if domain_id else None,
                    "version": version,
                    "published_by": str(published_by),
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


async def _emit_nb_archived(
    engine: Any,
    *,
    company_id: UUID,
    notebook_id: UUID,
    archived_by: UUID,
    reason: str = "deprecated",
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "notebook_archived",
                "ref_id": str(notebook_id),
                "reason": reason,
                "proposed_by": str(archived_by),
            },
            execute_fn=lambda: {
                "tool": "emit_notebook_archived",
                "args": {
                    "notebook_id": str(notebook_id),
                    "archived_by": str(archived_by),
                    "reason": reason,
                },
                "result_ref": "ok",
            },
            verify_fn=_verify_pass,
            resolve_fn=_resolve_keep,
        )


# ---------------------------------------------------------------------------
# Data product lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dp_proposed_creates_row(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    dp_id = uuid4()
    person_id = uuid4()

    await _emit_dp_proposed(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
        requested_by_person_id=person_id,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.data_products) == 1
    dp = proj.data_products[0]
    assert dp["data_product_id"] == dp_id
    assert dp["name"] == "Q3 Net Revenue"
    assert dp["kind"] == "report"
    assert dp["status"] == "proposed"
    assert dp["requested_by_person_id"] == person_id


@pytest.mark.asyncio
async def test_dp_generated_transitions_status_and_appends_run(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    dp_id = uuid4()
    person_id = uuid4()

    await _emit_dp_proposed(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
        requested_by_person_id=person_id,
    )
    await _emit_dp_generated(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
        content_hash="abc123",
        source_hashes=["src1"],
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.data_products) == 1
    assert proj.data_products[0]["status"] == "generated"
    assert proj.data_products[0]["content_hash"] == "abc123"
    assert len(proj.data_product_runs) == 1
    run = proj.data_product_runs[0]
    assert run["data_product_id"] == dp_id
    assert run["source_hashes"] == ["src1"]


@pytest.mark.asyncio
async def test_dp_consumed_appends_consumption_row(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    dp_id = uuid4()
    person_id = uuid4()
    consumer = uuid4()

    await _emit_dp_proposed(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
        requested_by_person_id=person_id,
    )
    await _emit_dp_consumed(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
        person_id=consumer,
        surface="dashboard",
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.data_product_consumption) == 1
    c = proj.data_product_consumption[0]
    assert c["data_product_id"] == dp_id
    assert c["person_id"] == consumer
    assert c["surface"] == "dashboard"


@pytest.mark.asyncio
async def test_dp_archived_flips_status(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    dp_id = uuid4()
    person_id = uuid4()
    admin = uuid4()

    await _emit_dp_proposed(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
        requested_by_person_id=person_id,
    )
    await _emit_dp_archived(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
        archived_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert proj.data_products[0]["status"] == "archived"


# ---------------------------------------------------------------------------
# Notebook lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nb_proposed_creates_row(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    nb_id = uuid4()
    person_id = uuid4()

    await _emit_nb_proposed(
        engine,
        company_id=company_id,
        notebook_id=nb_id,
        proposed_by_person_id=person_id,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.notebooks) == 1
    nb = proj.notebooks[0]
    assert nb["notebook_id"] == nb_id
    assert nb["status"] == "proposed"
    assert nb["kernel"] == "python_local"
    # Cells must NOT leak into the projection row
    assert "_cells" not in nb


@pytest.mark.asyncio
async def test_nb_run_appends_run_row_and_updates_latest(
    test_database_url: str,
) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    nb_id = uuid4()
    run_id = uuid4()
    person_id = uuid4()

    await _emit_nb_proposed(
        engine,
        company_id=company_id,
        notebook_id=nb_id,
        proposed_by_person_id=person_id,
    )
    await _emit_nb_run(
        engine,
        company_id=company_id,
        notebook_id=nb_id,
        run_id=run_id,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.notebook_runs) == 1
    assert proj.notebooks[0]["status"] == "run"
    assert proj.notebooks[0]["latest_run_id"] is not None


@pytest.mark.asyncio
async def test_nb_published_promotes_status(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    nb_id = uuid4()
    run_id = uuid4()
    person_id = uuid4()
    admin = uuid4()

    await _emit_nb_proposed(
        engine,
        company_id=company_id,
        notebook_id=nb_id,
        proposed_by_person_id=person_id,
    )
    await _emit_nb_run(
        engine,
        company_id=company_id,
        notebook_id=nb_id,
        run_id=run_id,
    )
    await _emit_nb_published(
        engine,
        company_id=company_id,
        notebook_id=nb_id,
        run_id=run_id,
        owner_person_id=person_id,
        published_by=admin,
        version="1",
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert proj.notebooks[0]["status"] == "published"
    assert proj.notebooks[0]["version"] == "1"
    assert proj.notebooks[0]["latest_published_run_id"] is not None


@pytest.mark.asyncio
async def test_nb_archived_flips_status(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    nb_id = uuid4()
    person_id = uuid4()
    admin = uuid4()

    await _emit_nb_proposed(
        engine,
        company_id=company_id,
        notebook_id=nb_id,
        proposed_by_person_id=person_id,
    )
    await _emit_nb_archived(
        engine,
        company_id=company_id,
        notebook_id=nb_id,
        archived_by=admin,
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert proj.notebooks[0]["status"] == "archived"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dp_replay_is_deterministic(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    dp_id = uuid4()
    person_id = uuid4()

    await _emit_dp_proposed(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
        requested_by_person_id=person_id,
    )
    await _emit_dp_generated(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
    )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_id)
    async with session_scope(engine) as session:
        proj_b = await build_projections(session, company_id)

    assert proj_a.data_products == proj_b.data_products
    assert proj_a.data_product_runs == proj_b.data_product_runs
    assert (
        proj_a.data_product_runs[0]["run_id"]
        == proj_b.data_product_runs[0]["run_id"]
    )


@pytest.mark.asyncio
async def test_nb_replay_is_deterministic(test_database_url: str) -> None:
    engine = get_engine(test_database_url)
    company_id = uuid4()
    nb_id = uuid4()
    run_id = uuid4()
    person_id = uuid4()

    await _emit_nb_proposed(
        engine,
        company_id=company_id,
        notebook_id=nb_id,
        proposed_by_person_id=person_id,
    )
    await _emit_nb_run(
        engine,
        company_id=company_id,
        notebook_id=nb_id,
        run_id=run_id,
    )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_id)
    async with session_scope(engine) as session:
        proj_b = await build_projections(session, company_id)

    assert proj_a.notebooks == proj_b.notebooks
    assert proj_a.notebook_runs == proj_b.notebook_runs


@pytest.mark.asyncio
async def test_run_consumption_uses_deterministic_id(
    test_database_url: str,
) -> None:
    """Two replays of the same ledger produce identical projection ids."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    dp_id = uuid4()
    person_id = uuid4()

    await _emit_dp_proposed(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
        requested_by_person_id=person_id,
    )
    await _emit_dp_consumed(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
        person_id=person_id,
    )
    await _emit_dp_consumed(
        engine,
        company_id=company_id,
        data_product_id=dp_id,
        person_id=person_id,
        surface="export",
    )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, company_id)
    async with session_scope(engine) as session:
        proj_b = await build_projections(session, company_id)

    assert len(proj_a.data_product_consumption) == 2
    ids_a = sorted(str(c["consumption_id"]) for c in proj_a.data_product_consumption)
    ids_b = sorted(str(c["consumption_id"]) for c in proj_b.data_product_consumption)
    assert ids_a == ids_b
