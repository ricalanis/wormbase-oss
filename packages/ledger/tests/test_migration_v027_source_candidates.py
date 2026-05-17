"""v027 migration — projection_source_candidates.

L1 Sub-wave A (2026-06-08). Folded view of lake-side source-candidate
triage proposals from the L1 Compounding axis + promoted/rejected by
admin operators. Schema mirrors the v027 migration; the dialect-aware
DDL pattern follows v014/v016/v021/v022/v023/v024/v025/v026
(SQLite-portable + Postgres-friendly).

The SQLite tests below cover the always-on path. The Postgres path
exercises the same Migration class — it's plain SQLAlchemy Core DDL
with no pgvector dependency, so the SQLite tests cover the
production schema by structural equivalence. A Postgres apply test
is gated on WORMBASE_INTEGRATION_DB=1 + a reachable
WORMBASE_TEST_DB_URL.
"""
from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v027_projection_source_candidates import (
    Migration as V027Migration,
    _TABLE_NAME,
)


_EXPECTED_COLUMNS = {
    "company_id",
    "candidate_id",
    "proposed_kind",
    "proposed_identifier",
    "domain_id_hint",
    "strategy",
    "reasoning",
    "confidence",
    "evidence",
    "downstream_source_proposed_id",
    "state",
    "state_changed_at",
    "state_changed_by",
}


# ---------------------------------------------------------------------------
# SQLite path — always exercised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v027_creates_projection_source_candidates_idempotent() -> None:
    """First apply creates the table; second apply is a no-op (checkfirst)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V027Migration().up(conn)
    async with engine.begin() as conn:
        # Second apply — must not raise; checkfirst short-circuits.
        await V027Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {
                c["name"]
                for c in inspect(sc).get_columns(_TABLE_NAME)
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v027_has_composite_primary_key() -> None:
    """Primary key spans (company_id, candidate_id) per spec §4.5."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V027Migration().up(conn)
    async with engine.connect() as conn:
        pk = await conn.run_sync(
            lambda sc: inspect(sc).get_pk_constraint(_TABLE_NAME)
        )
    # Order doesn't matter for the constraint contract; compare as sets.
    assert set(pk["constrained_columns"]) == {
        "company_id",
        "candidate_id",
    }


@pytest.mark.asyncio
async def test_v027_creates_expected_indexes() -> None:
    """Four secondary indexes: state / strategy / proposed_kind /
    domain_id_hint."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V027Migration().up(conn)
    async with engine.connect() as conn:
        idxs = await conn.run_sync(
            lambda sc: {i["name"] for i in inspect(sc).get_indexes(_TABLE_NAME)}
        )
    assert "ix_projection_source_candidates_state" in idxs
    assert "ix_projection_source_candidates_strategy" in idxs
    assert "ix_projection_source_candidates_proposed_kind" in idxs
    assert "ix_projection_source_candidates_domain_id_hint" in idxs


@pytest.mark.asyncio
async def test_v027_state_check_constraint_rejects_bogus_state() -> None:
    """CHECK on state pins the enum {proposed, promoted, rejected}.

    Note L1 uses ``promoted`` where L3/L7/L4/L5/L6/L8 use ``confirmed``
    — per spec §1, L1 prequels the existing source pipeline so the
    affirmative state name is "promoted" (into the pipeline) rather
    than "confirmed"."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V027Migration().up(conn)
    # Each documented state inserts cleanly.
    async with engine.begin() as conn:
        for i, state in enumerate(("proposed", "promoted", "rejected")):
            await conn.execute(
                text(
                    "INSERT INTO projection_source_candidates "
                    "(company_id, candidate_id, proposed_kind, "
                    " proposed_identifier, strategy, reasoning, "
                    " confidence, evidence, state, state_changed_at) "
                    f"VALUES ('co1', 'c{i}', 'csv_local', 'x', "
                    f"'kpi_gap', 'r', 0.5, '{{}}', '{state}', "
                    f"'2026-06-08T00:00:00Z')"
                )
            )
    # An out-of-enum state (e.g. L3-style "confirmed") is refused.
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_source_candidates "
                    "(company_id, candidate_id, proposed_kind, "
                    " proposed_identifier, strategy, reasoning, "
                    " confidence, evidence, state, state_changed_at) "
                    "VALUES ('co1', 'cx', 'csv_local', 'x', "
                    "'kpi_gap', 'r', 0.5, '{}', "
                    "'confirmed', '2026-06-08T00:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v027_nullable_domain_hint_downstream_and_changed_by() -> None:
    """``domain_id_hint``, ``downstream_source_proposed_id``, and
    ``state_changed_by`` are NULL-able.

    domain_id_hint is NULL when the strategy has no domain signal
    (e.g. channel_mention picks up a vendor mention without context);
    downstream_source_proposed_id is NULL on proposed rows (only
    populated after a promote action threads back the downstream
    entry-id); state_changed_by is NULL for proposed rows (system-
    written by the L1 Compounding axis)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V027Migration().up(conn)
        await conn.execute(
            text(
                "INSERT INTO projection_source_candidates "
                "(company_id, candidate_id, proposed_kind, "
                " proposed_identifier, domain_id_hint, strategy, "
                " reasoning, confidence, evidence, "
                " downstream_source_proposed_id, state, "
                " state_changed_at, state_changed_by) "
                "VALUES ('co1', 'c-null', 'csv_local', 'x', NULL, "
                "'channel_mention', 'r', 0.55, '{}', NULL, "
                "'proposed', '2026-06-08T00:00:00Z', NULL)"
            )
        )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT domain_id_hint, downstream_source_proposed_id, "
                    "state_changed_by FROM projection_source_candidates "
                    "WHERE candidate_id = 'c-null'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] is None  # domain_id_hint
    assert row[1] is None  # downstream_source_proposed_id
    assert row[2] is None  # state_changed_by


@pytest.mark.asyncio
async def test_v027_composite_pk_collapses_same_candidate_id_per_tenant() -> None:
    """Within one tenant, the same candidate_id can only be inserted
    once — the composite PK enforces that the dedup hash from
    ``make_candidate_id`` actually dedups at the projection layer."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V027Migration().up(conn)
        await conn.execute(
            text(
                "INSERT INTO projection_source_candidates "
                "(company_id, candidate_id, proposed_kind, "
                " proposed_identifier, strategy, reasoning, "
                " confidence, evidence, state, state_changed_at) "
                "VALUES ('co1', 'c-shared', 'csv_local', 'x', "
                "'kpi_gap', 'r1', 0.5, '{}', 'proposed', "
                "'2026-06-08T00:00:00Z')"
            )
        )
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_source_candidates "
                    "(company_id, candidate_id, proposed_kind, "
                    " proposed_identifier, strategy, reasoning, "
                    " confidence, evidence, state, state_changed_at) "
                    "VALUES ('co1', 'c-shared', 'csv_local', 'x', "
                    "'kpi_gap', 'r2', 0.6, '{}', 'proposed', "
                    "'2026-06-08T01:00:00Z')"
                )
            )


@pytest.mark.asyncio
async def test_v027_same_candidate_id_isolated_across_tenants() -> None:
    """Different tenants can hold the same candidate_id (tenant
    isolation via the composite PK leg)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V027Migration().up(conn)
        for company_id in ("co-a", "co-b"):
            await conn.execute(
                text(
                    "INSERT INTO projection_source_candidates "
                    "(company_id, candidate_id, proposed_kind, "
                    " proposed_identifier, strategy, reasoning, "
                    " confidence, evidence, state, state_changed_at) "
                    f"VALUES ('{company_id}', 'c-shared', "
                    f"'csv_local', 'x', 'kpi_gap', 'r', 0.5, '{{}}', "
                    f"'proposed', '2026-06-08T00:00:00Z')"
                )
            )
    async with engine.connect() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM projection_source_candidates "
                    "WHERE candidate_id = 'c-shared'"
                )
            )
        ).scalar()
    assert count == 2


# ---------------------------------------------------------------------------
# Registration / monotonicity
# ---------------------------------------------------------------------------


def test_v027_registered_in_canonical_migrations() -> None:
    """v027 lives in MIGRATIONS, monotonic and gap-free after v026."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"out of order: {versions}"
    assert 27 in versions, f"expected v27 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )


def test_v027_description_documents_projection_source_candidates() -> None:
    """Migration description names the table + key invariants for log scan."""
    m = V027Migration()
    assert "projection_source_candidates" in m.description
    assert "L1" in m.description or "candidate" in m.description


def test_v027_forward_only_no_down_method() -> None:
    """Forward-only doctrine — no ``down`` method on Migration."""
    assert not hasattr(V027Migration(), "down")


# ---------------------------------------------------------------------------
# Postgres path — env-gated (mirrors v019..v026)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v027_applies_cleanly_on_postgres() -> None:
    """v027 applies on Postgres when WORMBASE_INTEGRATION_DB=1.

    Skip cleanly when the integration env is unset OR when the test
    URL points at a non-Postgres backend (SQLite default). The
    migration is plain Core DDL with no pgvector dependency, so the
    SQLite path covers the production shape by structural equivalence;
    this test is belt-and-suspenders.
    """
    if not os.environ.get("WORMBASE_INTEGRATION_DB"):
        pytest.skip("WORMBASE_INTEGRATION_DB not set")
    url = os.environ.get("WORMBASE_TEST_DB_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip(f"WORMBASE_TEST_DB_URL is not Postgres: {url!r}")

    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await V027Migration().up(conn)
        async with engine.connect() as conn:
            cols = await conn.run_sync(
                lambda sc: {
                    c["name"]
                    for c in inspect(sc).get_columns(_TABLE_NAME)
                }
            )
        assert cols == _EXPECTED_COLUMNS
    finally:
        # Clean up so re-runs are idempotent at the schema level.
        async with engine.begin() as conn:
            await conn.execute(sa.text(f"DROP TABLE IF EXISTS {_TABLE_NAME}"))
        await engine.dispose()
