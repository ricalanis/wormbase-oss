"""v017 migration — projection_query_templates.

Semantic Layer Wave 2 Task 3 (2026-05-11). §4.5 compounding-layer
template registry folded from ``query_template_promoted`` entries.
Same dialect-aware embedding pattern as v016 — ``Vector(1536)`` on
Postgres, ``JSON`` on SQLite.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v017_projection_query_templates import (
    Migration,
    _embedding_column,
)


_EXPECTED_COLUMNS = {
    "id",
    "company_id",
    "domain_id",
    "nl_intent",
    "query_spec",
    "promoted_from_outcome_ids",
    "quality_score",
    "hit_count",
    "embedding",
    "promoted_at",
}


@pytest.mark.asyncio
async def test_v017_creates_projection_query_templates_idempotent() -> None:
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
                for c in inspect(sc).get_columns("projection_query_templates")
            }
        )
    assert cols == _EXPECTED_COLUMNS, (
        f"unexpected schema: missing={_EXPECTED_COLUMNS - cols} "
        f"extra={cols - _EXPECTED_COLUMNS}"
    )


@pytest.mark.asyncio
async def test_v017_hit_count_defaults_to_zero() -> None:
    """``hit_count`` carries a server-side default of 0 so newly
    promoted templates start at no recorded reuse. The query-path
    increments it on cache hit."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO projection_query_templates "
                "(id, company_id, domain_id, nl_intent, query_spec, "
                " promoted_from_outcome_ids, quality_score, "
                " promoted_at) "
                "VALUES ('t1', 'co1', 'd1', 'q intent', '{}', "
                "'[\"o1\"]', 0.9000, '2026-05-11T00:00:00Z')"
            )
        )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT hit_count FROM projection_query_templates "
                    "WHERE id = 't1'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] == 0


@pytest.mark.asyncio
async def test_v017_sqlite_embedding_is_json_not_vector() -> None:
    """On SQLite the embedding column falls back to JSON shape.

    The Postgres path uses ``pgvector.sqlalchemy.Vector(1536)``;
    tests round-trip a JSON list to confirm the SQLite fallback is
    structurally present and lossless."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await Migration().up(conn)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO projection_query_templates "
                "(id, company_id, domain_id, nl_intent, query_spec, "
                " promoted_from_outcome_ids, quality_score, embedding, "
                " promoted_at) "
                "VALUES ('t1', 'co1', 'd1', 'q intent', '{}', "
                "'[\"o1\"]', 0.9200, :emb, '2026-05-11T00:00:00Z')"
            ),
            {"emb": '[0.1, 0.2, 0.3]'},
        )
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT embedding FROM projection_query_templates "
                    "WHERE id = 't1'"
                )
            )
        ).first()
    assert row is not None
    import json as _json

    assert _json.loads(row[0]) == [0.1, 0.2, 0.3]


def test_v017_embedding_column_is_json_on_sqlite_dialect() -> None:
    """Static guard: ``_embedding_column("sqlite")`` returns JSON, not
    pgvector. Mirror of v016's drift-catch test."""
    col = _embedding_column("sqlite")
    assert col.name == "embedding"
    assert isinstance(col.type, sa.JSON)


def test_v017_registered_in_canonical_migrations() -> None:
    """V017 lives in MIGRATIONS, monotonic and gap-free after v016."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"versions out of order: {versions}"
    assert 17 in versions, f"expected v17 present; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"version gap detected: {versions}"
    )
