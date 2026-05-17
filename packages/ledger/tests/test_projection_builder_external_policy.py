"""Projection-fold tests for catalog-mirror policy + metric entries (Wave 3 Task 6).

Pins the projection-builder contract for two more catalog-mirror tools:

* ``emit_external_policy_imported`` → ``projection_external_policy``
* ``emit_external_metric_imported`` → ``projection_external_metric``

These tables are read by the ``/lake/governance`` dashboard page; this test
guards the fold so the dashboard's read-side never goes stale relative to
the ledger source-of-truth.

S2 spike contract (per Wave 1 Task 4): ``ExternalPolicy.body`` may be
``None`` when the catalog credential lacks APPLY privilege for the
policy body. The fold MUST preserve ``None`` verbatim — the dashboard
side then surfaces a "Body unavailable" placeholder. Migration v010
makes ``body`` NULLABLE on disk; this test exercises both NULL and
non-NULL paths to pin the contract.

Metric idempotency: re-emit of the same (source_id, name) tuple
upserts in place — the builder's deterministic ``id`` keying matches
the v011 SQL ``UNIQUE`` index on ``(source_id, name)``.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from wormbase_ledger.db import get_engine, session_scope
from wormbase_ledger.projections import build_projections
from wormbase_ledger.write_primitive import write_primitive


def _policy_args(
    *,
    source_id: UUID,
    policy_fqn: str = "ACME.RAW.REVENUE_MASK",
    policy_kind: str = "masking",
    body: str | None = "CASE WHEN current_role() = 'ADMIN' THEN val ELSE NULL END",
    applied_to: tuple[str, ...] = ("ACME.RAW.REVENUE.amount",),
) -> dict[str, object]:
    """Build canonical execute-payload args for emit_external_policy_imported."""
    return {
        "source_id": str(source_id),
        "policy_fqn": policy_fqn,
        "policy_kind": policy_kind,
        "body": body,
        # Pydantic serializes tuples as lists across the JSON boundary;
        # mirror that on the wire so the fold sees disk-shaped input.
        "applied_to": list(applied_to),
    }


def _metric_args(
    *,
    source_id: UUID,
    name: str = "revenue_by_region",
    expression: str | None = "sum(orders.amount)",
    time_grain: str | None = "day",
    dimensions: tuple[str, ...] = ("region", "product_category"),
    description: str | None = "Daily revenue rolled up by region.",
) -> dict[str, object]:
    """Build canonical execute-payload args for emit_external_metric_imported."""
    return {
        "source_id": str(source_id),
        "name": name,
        "expression": expression,
        "time_grain": time_grain,
        "dimensions": list(dimensions),
        "description": description,
    }


async def _write_policy_pevr(
    engine,
    *,
    company_id: UUID,
    args: dict[str, object],
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "external_policy_imported",
                "ref_id": str(args["source_id"]),
                "reason": "catalog-mirror: external_policy_imported",
                "proposed_by": "catalog_mirror",
            },
            execute_fn=lambda: {
                "tool": "emit_external_policy_imported",
                "args": args,
                "result_ref": str(args["source_id"]),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "policy_recorded", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "external_policy_imported observed",
            },
            quadrant="active_deterministic",
        )


async def _write_metric_pevr(
    engine,
    *,
    company_id: UUID,
    args: dict[str, object],
) -> None:
    async with session_scope(engine) as session:
        await write_primitive(
            session,
            company_id=company_id,
            propose={
                "target_kind": "external_metric_imported",
                "ref_id": str(args["source_id"]),
                "reason": "catalog-mirror: external_metric_imported",
                "proposed_by": "catalog_mirror",
            },
            execute_fn=lambda: {
                "tool": "emit_external_metric_imported",
                "args": args,
                "result_ref": str(args["source_id"]),
            },
            verify_fn=lambda _r: {
                "checks": [{"name": "metric_recorded", "ok": True}],
                "passed": True,
            },
            resolve_fn=lambda _v: {
                "outcome": "keep",
                "rationale": "external_metric_imported observed",
            },
            quadrant="active_deterministic",
        )


@pytest.mark.asyncio
async def test_external_policy_imported_creates_projection_row(
    test_database_url: str,
) -> None:
    """One PEVR cycle → one ``projection_external_policy`` row with the right shape."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()

    await _write_policy_pevr(
        engine,
        company_id=company_id,
        args=_policy_args(
            source_id=source_id,
            policy_fqn="ACME.RAW.REVENUE_MASK",
            policy_kind="masking",
            body="CASE WHEN current_role() = 'ADMIN' THEN val ELSE NULL END",
            applied_to=("ACME.RAW.REVENUE.amount", "ACME.RAW.REVENUE.tax"),
        ),
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.external_policy) == 1
    row = proj.external_policy[0]
    assert row["company_id"] == company_id
    assert row["source_id"] == source_id
    assert row["policy_fqn"] == "ACME.RAW.REVENUE_MASK"
    assert row["policy_kind"] == "masking"
    assert (
        row["body"]
        == "CASE WHEN current_role() = 'ADMIN' THEN val ELSE NULL END"
    )
    assert row["applied_to"] == [
        "ACME.RAW.REVENUE.amount",
        "ACME.RAW.REVENUE.tax",
    ]
    # imported_at is the entry ts; assert it's tz-aware.
    assert row["imported_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_external_policy_body_null_preserved(
    test_database_url: str,
) -> None:
    """Body=NULL (S2 spike: read-only role lacks APPLY) folds through verbatim.

    This is the load-bearing test for the catalog-mirror Reactivity
    operating on a read-only Snowflake catalog credential — the policy
    SQL is unreachable, but the policy's existence + applied_to surface
    still need to ride into the projection so drift detection works.
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()

    await _write_policy_pevr(
        engine,
        company_id=company_id,
        args=_policy_args(
            source_id=source_id,
            policy_fqn="ACME.RAW.PII_ROW_ACCESS",
            policy_kind="row_access",
            body=None,
            applied_to=("ACME.RAW.CUSTOMERS",),
        ),
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.external_policy) == 1
    row = proj.external_policy[0]
    assert row["body"] is None
    assert row["policy_kind"] == "row_access"
    assert row["policy_fqn"] == "ACME.RAW.PII_ROW_ACCESS"
    assert row["applied_to"] == ["ACME.RAW.CUSTOMERS"]


@pytest.mark.asyncio
async def test_external_policy_applied_to_json_roundtrip(
    test_database_url: str,
) -> None:
    """applied_to lists round-trip losslessly through the JSON projection column."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()
    applied = (
        "ACME.RAW.REVENUE.amount",
        "ACME.RAW.REVENUE.tax",
        "ACME.RAW.REVENUE.discount",
    )

    await _write_policy_pevr(
        engine,
        company_id=company_id,
        args=_policy_args(
            source_id=source_id,
            policy_fqn="ACME.MULTI_COL_MASK",
            applied_to=applied,
        ),
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.external_policy) == 1
    row = proj.external_policy[0]
    # Order preserved (list, not set).
    assert row["applied_to"] == list(applied)


@pytest.mark.asyncio
async def test_external_policy_replay_collapses_same_fqn(
    test_database_url: str,
) -> None:
    """Same (source_id, policy_fqn) re-imports onto the same row id.

    Re-import of the same policy fqn upserts in place; the
    deterministic ``id`` keying on (company, source, fqn) means the
    builder's tenant-scoped delete+insert persist pattern doesn't
    grow the row count over time.
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()
    base_args = _policy_args(
        source_id=source_id,
        policy_fqn="ACME.STABLE_POLICY",
        body="SELECT 1",
    )

    # First import.
    await _write_policy_pevr(engine, company_id=company_id, args=base_args)
    # Second import (no-op refresh) — same fqn, same source.
    await _write_policy_pevr(engine, company_id=company_id, args=base_args)

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.external_policy) == 1


@pytest.mark.asyncio
async def test_external_metric_imported_creates_projection_row(
    test_database_url: str,
) -> None:
    """One PEVR cycle → one ``projection_external_metric`` row with the right shape."""
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()

    await _write_metric_pevr(
        engine,
        company_id=company_id,
        args=_metric_args(
            source_id=source_id,
            name="net_revenue",
            expression="sum(orders.amount) - sum(orders.refunds)",
            time_grain="day",
            dimensions=("region", "product_category"),
            description="Net revenue excluding refunds.",
        ),
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.external_metric) == 1
    row = proj.external_metric[0]
    assert row["company_id"] == company_id
    assert row["source_id"] == source_id
    assert row["name"] == "net_revenue"
    assert row["expression"] == "sum(orders.amount) - sum(orders.refunds)"
    assert row["time_grain"] == "day"
    assert row["dimensions"] == ["region", "product_category"]
    assert row["description"] == "Net revenue excluding refunds."
    assert row["imported_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_external_metric_nullable_fields_preserved(
    test_database_url: str,
) -> None:
    """Nullable expression / time_grain / description preserved as None.

    Upstream catalogs differ on which fields they expose. The
    projection must not drop a metric because one optional field is
    missing — partial metric definitions are real-world.
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()

    await _write_metric_pevr(
        engine,
        company_id=company_id,
        args=_metric_args(
            source_id=source_id,
            name="partial_metric",
            expression=None,
            time_grain=None,
            dimensions=(),
            description=None,
        ),
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    assert len(proj.external_metric) == 1
    row = proj.external_metric[0]
    assert row["name"] == "partial_metric"
    assert row["expression"] is None
    assert row["time_grain"] is None
    assert row["description"] is None
    assert row["dimensions"] == []


@pytest.mark.asyncio
async def test_external_metric_upsert_on_duplicate_name(
    test_database_url: str,
) -> None:
    """Same (source_id, name) re-imports onto the same row, latest-wins on expression.

    This is the metric-side analog of the policy upsert test:
    deterministic per-(source, name) row id means a re-emit with a
    revised expression replaces the prior row in place rather than
    creating a duplicate. The v011 SQL ``UNIQUE`` index on
    ``(source_id, name)`` enforces this on disk too.
    """
    engine = get_engine(test_database_url)
    company_id = uuid4()
    source_id = uuid4()

    # First import — initial expression.
    await _write_metric_pevr(
        engine,
        company_id=company_id,
        args=_metric_args(
            source_id=source_id,
            name="weekly_active_users",
            expression="count(distinct user_id)",
            time_grain="week",
            dimensions=("region",),
            description="WAU v1",
        ),
    )

    # Second import — same name, revised expression.
    await _write_metric_pevr(
        engine,
        company_id=company_id,
        args=_metric_args(
            source_id=source_id,
            name="weekly_active_users",
            expression="count(distinct user_id) filter (where active)",
            time_grain="week",
            dimensions=("region", "plan"),
            description="WAU v2 — restricted to active",
        ),
    )

    async with session_scope(engine) as session:
        proj = await build_projections(session, company_id)

    # Single row, latest expression wins.
    assert len(proj.external_metric) == 1
    row = proj.external_metric[0]
    assert row["expression"] == "count(distinct user_id) filter (where active)"
    assert row["dimensions"] == ["region", "plan"]
    assert row["description"] == "WAU v2 — restricted to active"


@pytest.mark.asyncio
async def test_external_policy_and_metric_projections_are_tenant_scoped(
    test_database_url: str,
) -> None:
    """Policy + metric entries in tenant A are not visible from tenant B's fold."""
    engine = get_engine(test_database_url)
    tenant_a = uuid4()
    tenant_b = uuid4()
    source_id = uuid4()

    await _write_policy_pevr(
        engine,
        company_id=tenant_a,
        args=_policy_args(source_id=source_id, policy_fqn="A.MASK"),
    )
    await _write_metric_pevr(
        engine,
        company_id=tenant_a,
        args=_metric_args(source_id=source_id, name="a_metric"),
    )

    async with session_scope(engine) as session:
        proj_a = await build_projections(session, tenant_a)
        proj_b = await build_projections(session, tenant_b)

    assert len(proj_a.external_policy) == 1
    assert len(proj_a.external_metric) == 1
    assert len(proj_b.external_policy) == 0
    assert len(proj_b.external_metric) == 0
