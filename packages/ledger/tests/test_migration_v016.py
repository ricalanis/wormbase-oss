"""v016 migration — projection_query_outcomes.

Semantic Layer Wave 2 Task 3 (2026-05-11). §4.5 compounding-layer
outcome ledger folded from ``query_outcome_recorded`` entries. The
embedding column is dialect-aware: ``Vector(1536)`` on Postgres
(pgvector ≥0.6), ``JSON`` on SQLite (tests). These tests exercise
the SQLite fallback path; the Postgres path is covered by the
integration suite on a live Postgres instance.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v016_projection_query_outcomes import (
    Migration,
    _embedding_column,
)


_EXPECTED_COLUMNS = {
    "id",
    "company_id",
    "agent_query_id",
    "nl_question",
    "final_query_spec",
    "result_summary",
    "used",
    "useful",
    "user_correction",
    "quality_score",
    "embedding",
    "recorded_at",
}


@pytest.mark.asyncio
async def test_v016_creates_projection_query_outcomes_idempotent() -> None:
    """First apply creates the table; second apply is a no-op."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {
                c["name"]
                for c in inspect(sc).get_columns("projection_query_outcomes")
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v016_sqlite_embedding_is_json_not_vector() -> None:
    """On SQLite the embedding column falls back to JSON shape.

    Production (Postgres) uses ``pgvector.sqlalchemy.Vector(1536)``;
    tests must round-trip the column without requiring the binary
    extension. This test exercises the fallback by inserting a JSON
    list, reading it back, and verifying the value survives.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    embedding_payload = [0.1, 0.2, 0.3, 0.4]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO projection_query_outcomes "
                "(id, company_id, agent_query_id, nl_question, "
                " final_query_spec, result_summary, used, useful, "
                " quality_score, embedding, recorded_at) "
                "VALUES ('o1', 'co1', 'q1', 'q?', "
                "'{}', '{}', 1, 1, "
                "0.9500, :emb, '2026-05-11T00:00:00Z')"
            ),
            {"emb": '[0.1, 0.2, 0.3, 0.4]'},
        )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT embedding FROM projection_query_outcomes "
                    "WHERE id = 'o1'"
                )
            )
        ).first()
    assert row is not None
    # JSON-backed column round-trips the list shape.
    import json as _json

    assert _json.loads(row[0]) == embedding_payload


def test_v016_embedding_column_is_json_on_sqlite_dialect() -> None:
    """Static guard: ``_embedding_column("sqlite")`` returns a JSON
    column, not pgvector. Catches drift if the fallback is removed."""
    col = _embedding_column("sqlite")
    assert col.name == "embedding"
    assert isinstance(col.type, sa.JSON)


def test_v016_embedding_column_default_dialect_is_json() -> None:
    """When dialect_name is None (e.g. metadata.create_all on raw
    MetaData), fall back to JSON — the safe default."""
    col = _embedding_column(None)
    assert isinstance(col.type, sa.JSON)


def test_v016_registered_in_canonical_migrations() -> None:
    """V016 lives in MIGRATIONS, monotonic and gap-free after v015."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 16 in versions, f"expected v16 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
