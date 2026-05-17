"""Projection-fold tests for ``agent_query`` + ``credential`` PEVR cycles.

Wave 3 Task 3 (the SOC-2-credibility view): the agent-gateway writes a
single-kind 4-phase PEVR cycle per agent_query (propose → execute →
verify → resolve), all four entries sharing one ``audit_trail_id``;
the builder folds them into ONE row in ``projection_agent_queries``
with ``status`` reflecting the latest phase observed. Credential
lifecycle events follow the same PEVR shape (single-kind status field
per Addendum 3) and fold into ``projection_credentials``.

This test pins the contracts the /trace/agent_query/[id] surface and
the future /credentials drawer depend on. It exercises both the in-
memory builder dict shape (``projections.agent_queries`` /
``projections.credentials``) and the SQL persist path so a future
schema change in either layer trips the test before the dashboard
breaks.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.entries import AgentQueryPayload, CredentialPayload
from wormbase_ledger.projections import build_projections
from wormbase_ledger.projections.builder import persist_projections
from wormbase_ledger.schema import (
    projection_agent_queries,
    projection_credentials,
)
from wormbase_ledger.write_primitive import write_primitive


# ---------------------------------------------------------------------------
# Helpers — build the four-phase agent_query payload dicts.
# ---------------------------------------------------------------------------


def _agent_query_payload(
    *,
    audit_trail_id: str,
    agent_id: str,
    mcp_tool: str,
    args: dict,
    route_mode: str,
    phase: str,
    row_count: int | None = None,
    cost_usd: str | None = None,
    latency_ms: int | None = None,
    caused_by: str | None = None,
) -> dict:
    """Build one phase's worth of agent_query payload, matching the
    single-kind-with-phase shape that the agent_query_pevr helper emits."""
    p = AgentQueryPayload(
        agent_id=agent_id,
        mcp_tool=mcp_tool,
        args=args,
        route_mode=route_mode,
        phase=phase,  # type: ignore[arg-type]
        row_count=row_count,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        caused_by=caused_by,
    )
    body = p.model_dump()
    body["audit_trail_id"] = audit_trail_id
    return body


async def _write_agent_query_pevr(
    session,
    *,
    company_id,
    audit_trail_id: str,
    agent_id: str = "agent-uuid-1",
    mcp_tool: str = "lake.semantic.metric",
    args: dict | None = None,
    route_mode: str = "broker",
    row_count: int | None = 2,
    cost_usd: str | None = "0.013",
    latency_ms: int | None = 420,
    caused_by: str | None = None,
) -> None:
    """Write a four-phase agent_query envelope via write_primitive.

    Matches the contract of ``wormbase_agent_gateway.identity.audit.agent_query_pevr``:
    every phase carries the same ``audit_trail_id`` and the typed
    AgentQueryPayload shape (no ``tool`` / ``args`` discriminator wrapper —
    those are reserved for the ``emit_*`` write style).
    """
    args = args or {"name": "revenue_q3", "filter": {"region": "EMEA"}}
    propose = _agent_query_payload(
        audit_trail_id=audit_trail_id,
        agent_id=agent_id,
        mcp_tool=mcp_tool,
        args=args,
        route_mode=route_mode,
        phase="propose",
        caused_by=caused_by,
    )

    def _exec() -> dict:
        return _agent_query_payload(
            audit_trail_id=audit_trail_id,
            agent_id=agent_id,
            mcp_tool=mcp_tool,
            args=args,
            route_mode=route_mode,
            phase="execute",
            row_count=row_count,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            caused_by=caused_by,
        )

    def _verify(_e) -> dict:
        v = _agent_query_payload(
            audit_trail_id=audit_trail_id,
            agent_id=agent_id,
            mcp_tool=mcp_tool,
            args=args,
            route_mode=route_mode,
            phase="verify",
            row_count=row_count,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            caused_by=caused_by,
        )
        v["passed"] = True
        v["checks"] = [{"name": "agent_query_default", "ok": True}]
        return v

    def _resolve(_v) -> dict:
        return _agent_query_payload(
            audit_trail_id=audit_trail_id,
            agent_id=agent_id,
            mcp_tool=mcp_tool,
            args=args,
            route_mode=route_mode,
            phase="resolve",
            row_count=row_count,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            caused_by=caused_by,
        )

    await write_primitive(
        session,
        company_id=company_id,
        propose=propose,
        execute_fn=_exec,
        verify_fn=_verify,
        resolve_fn=_resolve,
    )


async def _write_credential_pevr(
    session,
    *,
    company_id,
    agent_id: str = "agent-uuid-1",
    credential_kind: str = "data",
    target: str = "snowflake://WORMBASE.PUBLIC.REVENUE",
    status: str = "active",
    ttl_expires_at: str = "2026-05-11T18:00:00+00:00",
    issued_by: str = "agent-gateway",
) -> None:
    """Write a four-phase credential lifecycle envelope via write_primitive."""
    payload = CredentialPayload(
        agent_id=agent_id,
        credential_kind=credential_kind,  # type: ignore[arg-type]
        target=target,
        status=status,  # type: ignore[arg-type]
        ttl_expires_at=ttl_expires_at,
        issued_by=issued_by,
    )
    body = payload.model_dump()
    await write_primitive(
        session,
        company_id=company_id,
        propose=dict(body),
        execute_fn=lambda: dict(body),
        verify_fn=lambda _e: {**body, "passed": True, "checks": []},
        resolve_fn=lambda _v: {**body, "outcome": "keep"},
    )


# ---------------------------------------------------------------------------
# agent_query fold tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_query_pevr_folds_to_one_row(test_database_url: str) -> None:
    """All four PEVR phases collapse onto a single ``projection_agent_queries`` row."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    audit_id = str(uuid4())

    async with session_scope(engine) as session:
        await _write_agent_query_pevr(
            session,
            company_id=company_id,
            audit_trail_id=audit_id,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.agent_queries) == 1
    row = proj.agent_queries[0]
    # id == audit_trail_id; same across all four PEVR phases.
    assert row["id"] == audit_id
    assert row["company_id"] == str(company_id)
    assert row["agent_id"] == "agent-uuid-1"
    assert row["mcp_tool"] == "lake.semantic.metric"
    assert row["route_mode"] == "broker"
    # Latest phase wins on status (resolve, since verify passed).
    assert row["status"] == "resolve"
    # Measurements promote from the verify/resolve phases.
    assert row["row_count"] == 2
    assert row["cost_usd"] == "0.013"
    assert row["latency_ms"] == 420
    assert row["caused_by"] is None


@pytest.mark.asyncio
async def test_agent_query_caused_by_chains_to_parent_audit_trail(
    test_database_url: str,
) -> None:
    """``caused_by`` rides the row through the projection so the
    chain accessor can walk parent → child."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    parent_audit_id = str(uuid4())
    child_audit_id = str(uuid4())

    async with session_scope(engine) as session:
        await _write_agent_query_pevr(
            session,
            company_id=company_id,
            audit_trail_id=parent_audit_id,
        )
        await _write_agent_query_pevr(
            session,
            company_id=company_id,
            audit_trail_id=child_audit_id,
            caused_by=parent_audit_id,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    by_id = {r["id"]: r for r in proj.agent_queries}
    assert by_id[parent_audit_id]["caused_by"] is None
    assert by_id[child_audit_id]["caused_by"] == parent_audit_id


@pytest.mark.asyncio
async def test_agent_query_is_tenant_scoped(test_database_url: str) -> None:
    """An agent_query written to tenant A is invisible from tenant B's fold."""
    engine = get_engine(test_database_url)
    tenant_a = uuid4()
    tenant_b = uuid4()
    audit_id_a = str(uuid4())

    async with session_scope(engine) as session:
        await _write_agent_query_pevr(
            session,
            company_id=tenant_a,
            audit_trail_id=audit_id_a,
        )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, tenant_a)
        proj_b = await build_projections(session, tenant_b)

    assert len(proj_a.agent_queries) == 1
    assert proj_a.agent_queries[0]["id"] == audit_id_a
    assert proj_b.agent_queries == []


@pytest.mark.asyncio
async def test_agent_query_persists_to_sql_projection_table(
    test_database_url: str,
) -> None:
    """Persist round-trip: SQL projection_agent_queries holds the folded row."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    audit_id = str(uuid4())

    async with session_scope(engine) as session:
        await _write_agent_query_pevr(
            session,
            company_id=company_id,
            audit_trail_id=audit_id,
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # Persist via the same engine — persist_projections expects a raw
    # AsyncConnection, so spin up one here.
    async with engine.begin() as conn:
        await persist_projections(conn, company_id, proj)

    async with engine.begin() as conn:
        rows = (
            await conn.execute(
                select(projection_agent_queries).where(
                    projection_agent_queries.c.company_id == str(company_id)
                )
            )
        ).fetchall()
    assert len(rows) == 1
    row = rows[0]._mapping
    assert row["id"] == audit_id
    assert row["agent_id"] == "agent-uuid-1"
    assert row["status"] == "resolve"
    assert row["route_mode"] == "broker"


# ---------------------------------------------------------------------------
# credential fold tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credential_active_then_revoked_produces_two_rows(
    test_database_url: str,
) -> None:
    """Issue + revoke are separate lifecycle events; each lands a projection row."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        await _write_credential_pevr(
            session,
            company_id=company_id,
            status="active",
        )
        await _write_credential_pevr(
            session,
            company_id=company_id,
            status="revoked",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.credentials) == 2
    statuses = sorted(r["status"] for r in proj.credentials)
    assert statuses == ["active", "revoked"]
    for row in proj.credentials:
        assert row["company_id"] == str(company_id)
        assert row["agent_id"] == "agent-uuid-1"
        assert row["credential_kind"] == "data"


@pytest.mark.asyncio
async def test_credential_kind_data_vs_model_both_fold(
    test_database_url: str,
) -> None:
    """Both ``data`` and ``model`` credential kinds appear in the projection."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        await _write_credential_pevr(
            session,
            company_id=company_id,
            credential_kind="data",
            target="snowflake://X.Y.Z",
        )
        await _write_credential_pevr(
            session,
            company_id=company_id,
            credential_kind="model",
            target="kimi",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    kinds = sorted(r["credential_kind"] for r in proj.credentials)
    assert kinds == ["data", "model"]


@pytest.mark.asyncio
async def test_credential_persists_to_sql_projection_table(
    test_database_url: str,
) -> None:
    """SQL projection_credentials sees the folded credential lifecycle row."""
    engine = get_engine(test_database_url)
    company_id = uuid4()

    async with session_scope(engine) as session:
        await _write_credential_pevr(
            session,
            company_id=company_id,
            credential_kind="model",
            target="kimi",
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)
    async with engine.begin() as conn:
        await persist_projections(conn, company_id, proj)

    async with engine.begin() as conn:
        rows = (
            await conn.execute(
                select(projection_credentials).where(
                    projection_credentials.c.company_id == str(company_id)
                )
            )
        ).fetchall()
    assert len(rows) == 1
    row = rows[0]._mapping
    assert row["credential_kind"] == "model"
    assert row["target"] == "kimi"
    assert row["status"] == "active"
    assert row["issued_by"] == "agent-gateway"


# ---------------------------------------------------------------------------
# Shape-guard: ``_apply_pevr_envelope`` must not swallow regular emit_* writes.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pevr_envelope_fold_ignores_emit_tool_writes(
    test_database_url: str,
) -> None:
    """An ``emit_source_proposed`` execute payload must NOT land in
    ``agent_queries`` or ``credentials`` — the shape checks exclude it."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()

    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "source_proposed",
                "ref_id": str(source_id),
                "reason": "test",
                "proposed_by": "worm",
            },
            execute_fn=lambda: {
                "tool": "emit_source_proposed",
                "args": {
                    "source_id": str(source_id),
                    "source_kind": "file",
                    "uri": "s3://b/x.csv",
                    "added_via_flow": "drop_and_profile",
                    "suggested_classification": "internal",
                },
                "result_ref": "ok",
            },
            verify_fn=lambda _r: {"checks": [], "passed": True},
            resolve_fn=lambda _v: {"outcome": "keep", "rationale": "ok"},
        )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # The source landed in projection_sources, NOT in agent_queries or
    # credentials. The shape guard in _apply_pevr_envelope is the only
    # thing protecting against fold leakage.
    assert len(proj.sources) == 1
    assert proj.agent_queries == []
    assert proj.credentials == []
