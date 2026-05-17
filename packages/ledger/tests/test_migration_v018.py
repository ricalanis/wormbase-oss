"""v018 migration — resize embedding columns 1536 → 768.

v2.B Phase 3b (2026-05-12). The SQLite path is a no-op (embedding is
JSON-shaped, dim-agnostic); the Postgres path issues
``ALTER COLUMN … TYPE vector(768) USING NULL``. The SQLite tests here
verify the no-op behaviour + the migration registration; the Postgres
path is covered by the integration suite on a live Postgres instance.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from wormbase_ledger.projections.migrations import MIGRATIONS
from wormbase_ledger.projections.migrations.v016_projection_query_outcomes import (
    Migration as V016Migration,
)
from wormbase_ledger.projections.migrations.v017_projection_query_templates import (
    Migration as V017Migration,
)
from wormbase_ledger.projections.migrations.v018_resize_embeddings_to_768 import (
    Migration as V018Migration,
)


@pytest.mark.asyncio
async def test_v018_is_noop_on_sqlite() -> None:
    """SQLite stores embedding as JSON; v018 is a no-op (no schema change)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V016Migration().up(conn)
        await V017Migration().up(conn)
    # Apply v018 — should not raise.
    async with engine.begin() as conn:
        await V018Migration().up(conn)
    # Tables still exist with the same shape.
    async with engine.connect() as conn:
        cols = await conn.run_sync(
            lambda sc: {
                c["name"]
                for c in inspect(sc).get_columns("projection_query_outcomes")
            }
        )
    assert "embedding" in cols


@pytest.mark.asyncio
async def test_v018_idempotent_on_sqlite() -> None:
    """Re-applying v018 is safe."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V016Migration().up(conn)
        await V017Migration().up(conn)
        await V018Migration().up(conn)
    async with engine.begin() as conn:
        await V018Migration().up(conn)


@pytest.mark.asyncio
async def test_v018_preserves_json_embedding_round_trip_on_sqlite() -> None:
    """After v018, SQLite still round-trips a 768-length embedding list
    (the only durable invariant for the JSON-backed mirror)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V016Migration().up(conn)
        await V017Migration().up(conn)
        await V018Migration().up(conn)
    vec_768 = [0.001 * i for i in range(768)]
    import json as _json
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO projection_query_outcomes "
                "(id, company_id, agent_query_id, nl_question, "
                " final_query_spec, result_summary, used, useful, "
                " quality_score, embedding, recorded_at) "
                "VALUES ('o1', 'co1', 'q1', 'q?', "
                "'{}', '{}', 1, 1, "
                "0.9500, :emb, '2026-05-12T00:00:00Z')"
            ),
            {"emb": _json.dumps(vec_768)},
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
    assert len(_json.loads(row[0])) == 768


def test_v018_registered_in_canonical_migrations() -> None:
    """V018 follows v017 monotonically with no gaps."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"out of order: {versions}"
    assert 18 in versions, f"expected v18; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"gap detected: {versions}"
    )


def test_v018_description_documents_resize() -> None:
    """The migration description names the size change so log scans
    surface the v2.B Phase 3b transition."""
    m = V018Migration()
    assert "1536" in m.description
    assert "768" in m.description
