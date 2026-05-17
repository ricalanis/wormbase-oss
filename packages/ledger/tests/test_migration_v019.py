"""v019 migration — HNSW index on projection_query_outcomes.embedding.

The SQLite path is a no-op (embedding is JSON-shaped, no vector index
available); the Postgres path issues
``CREATE INDEX … USING hnsw (embedding vector_cosine_ops) WITH
(m = 16, ef_construction = 64)``. The SQLite tests here verify the
no-op behaviour + the migration registration; the Postgres path is
exercised when ``WORMBASE_INTEGRATION_DB=1`` and a reachable pgvector
endpoint is configured via ``WORMBASE_TEST_DB_URL`` — otherwise the
Postgres assertions skip cleanly.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text
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
from wormbase_ledger.projections.migrations.v019_hnsw_index_query_outcomes import (
    HnswParamError,
    Migration as V019Migration,
    _ENV_EF_CONSTRUCTION,
    _ENV_M,
    _EF_CONSTRUCTION_DEFAULT,
    _INDEX_NAME,
    _M_DEFAULT,
    _TABLE_NAME,
    _resolve_hnsw_params,
)


# ---------------------------------------------------------------------------
# SQLite path — always exercised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v019_is_noop_on_sqlite() -> None:
    """SQLite stores embedding as JSON; v019 is a no-op (no index created)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V016Migration().up(conn)
        await V017Migration().up(conn)
        await V018Migration().up(conn)
    # Apply v019 — must not raise on SQLite, must not create any index.
    async with engine.begin() as conn:
        await V019Migration().up(conn)
    # Verify the HNSW index name is absent from SQLite's index list.
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = :tbl"
                ),
                {"tbl": _TABLE_NAME},
            )
        ).fetchall()
    names = {r[0] for r in rows}
    assert _INDEX_NAME not in names, (
        f"v019 unexpectedly created {_INDEX_NAME} on SQLite "
        f"(should be Postgres-only). Found indexes: {names}"
    )


@pytest.mark.asyncio
async def test_v019_idempotent_on_sqlite() -> None:
    """Re-applying v019 on SQLite is safe (still a no-op)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V016Migration().up(conn)
        await V017Migration().up(conn)
        await V018Migration().up(conn)
        await V019Migration().up(conn)
    async with engine.begin() as conn:
        # Second apply — must not raise.
        await V019Migration().up(conn)


# ---------------------------------------------------------------------------
# Registration / monotonicity
# ---------------------------------------------------------------------------


def test_v019_registered_in_canonical_migrations() -> None:
    """V019 follows v018 monotonically with no gaps."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"out of order: {versions}"
    assert 19 in versions, f"expected v19; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"gap detected: {versions}"
    )


def test_v019_description_documents_hnsw_index() -> None:
    """The migration description names the index type and the column op
    family so log scans surface the Phase 3c performance work."""
    m = V019Migration()
    assert "HNSW" in m.description or "hnsw" in m.description
    assert "vector_cosine_ops" in m.description
    assert "projection_query_outcomes" in m.description


def test_v019_index_name_follows_convention() -> None:
    """Index name follows ``ix_<table>_<column>_<index_type>``.

    The convention pins demo-team mental model: prefix by ``ix_``, then
    the projection table, then the indexed column, then the access-
    method. Catches typo-drift if the constant is touched.
    """
    assert _INDEX_NAME == "ix_projection_query_outcomes_embedding_hnsw"


# ---------------------------------------------------------------------------
# Env-knob resolution (dialect-agnostic; runs everywhere)
# ---------------------------------------------------------------------------


def test_v019_params_default_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env vars set → defaults (m=16, ef_construction=64).

    Pins the byte-identical-behaviour invariant: deployments that don't
    set the new env knobs get the historical defaults so v019 produces
    the same index DDL as the pre-tunable build.
    """
    monkeypatch.delenv(_ENV_M, raising=False)
    monkeypatch.delenv(_ENV_EF_CONSTRUCTION, raising=False)
    m, ef = _resolve_hnsw_params()
    assert m == _M_DEFAULT == 16
    assert ef == _EF_CONSTRUCTION_DEFAULT == 64


def test_v019_params_honour_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid env values flow through (m=24, ef_construction=128).

    These are the high-recall-semantic-search values called out in the
    runbook. The pgvector range is [4, 64] for m and [16, 256] for
    ef_construction; 24 and 128 are mid-range and valid.
    """
    monkeypatch.setenv(_ENV_M, "24")
    monkeypatch.setenv(_ENV_EF_CONSTRUCTION, "128")
    m, ef = _resolve_hnsw_params()
    assert m == 24
    assert ef == 128


def test_v019_params_reject_m_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """m=128 is above the documented pgvector max (64) — must raise."""
    monkeypatch.setenv(_ENV_M, "128")
    monkeypatch.delenv(_ENV_EF_CONSTRUCTION, raising=False)
    with pytest.raises(HnswParamError) as excinfo:
        _resolve_hnsw_params()
    assert "WORMBASE_HNSW_M" in str(excinfo.value)
    assert "128" in str(excinfo.value)


def test_v019_params_reject_m_below_min(monkeypatch: pytest.MonkeyPatch) -> None:
    """m=2 is below the documented pgvector min (4) — must raise."""
    monkeypatch.setenv(_ENV_M, "2")
    monkeypatch.delenv(_ENV_EF_CONSTRUCTION, raising=False)
    with pytest.raises(HnswParamError):
        _resolve_hnsw_params()


def test_v019_params_reject_ef_construction_non_integer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ef_construction='abc' is non-integer — must raise loudly, not fallback.

    Pins the "validation is loud" invariant: a typo in the env var must
    not silently degrade to defaults. A misconfigured production index
    is worse than a loud boot failure.
    """
    monkeypatch.delenv(_ENV_M, raising=False)
    monkeypatch.setenv(_ENV_EF_CONSTRUCTION, "abc")
    with pytest.raises(HnswParamError) as excinfo:
        _resolve_hnsw_params()
    assert "WORMBASE_HNSW_EF_CONSTRUCTION" in str(excinfo.value)
    assert "abc" in str(excinfo.value)


def test_v019_params_reject_ef_construction_out_of_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ef_construction=1024 is above the documented pgvector max (256)."""
    monkeypatch.delenv(_ENV_M, raising=False)
    monkeypatch.setenv(_ENV_EF_CONSTRUCTION, "1024")
    with pytest.raises(HnswParamError):
        _resolve_hnsw_params()


def test_v019_params_empty_env_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty string env values fall through to defaults (not raise).

    Some container orchestrators export unset envs as empty strings; we
    treat empty as unset rather than non-integer so deployments don't
    boot-fail on a vacuous env declaration.
    """
    monkeypatch.setenv(_ENV_M, "")
    monkeypatch.setenv(_ENV_EF_CONSTRUCTION, "")
    m, ef = _resolve_hnsw_params()
    assert m == _M_DEFAULT
    assert ef == _EF_CONSTRUCTION_DEFAULT


# ---------------------------------------------------------------------------
# Postgres path — env-gated; skip cleanly when pgvector isn't reachable
# ---------------------------------------------------------------------------


def _postgres_url_or_skip() -> str:
    """Return a Postgres test URL or skip the test.

    Honours ``WORMBASE_INTEGRATION_DB=1`` + ``WORMBASE_TEST_DB_URL``
    (matching the convention in ``test_migrations_edge.py``). Skips
    cleanly when no Postgres / pgvector endpoint is available so the
    SQLite-only suite stays runnable without integration deps.
    """
    if os.environ.get("WORMBASE_INTEGRATION_DB") != "1":
        pytest.skip("WORMBASE_INTEGRATION_DB=1 not set; Postgres path skipped")
    url = os.environ.get("WORMBASE_TEST_DB_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip(
            "WORMBASE_TEST_DB_URL not pointed at a Postgres instance; "
            "Postgres path skipped"
        )
    return url


@pytest.mark.asyncio
async def test_v019_creates_hnsw_index_on_postgres() -> None:
    """Postgres + pgvector path: index is created with the right shape.

    Asserts:
      * the index name exists in ``pg_indexes``
      * the access method is ``hnsw``
      * the index targets the ``embedding`` column on
        ``projection_query_outcomes``

    Skips cleanly when pgvector isn't reachable.
    """
    url = _postgres_url_or_skip()
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await V016Migration().up(conn)
            await V017Migration().up(conn)
            await V018Migration().up(conn)
            await V019Migration().up(conn)
        async with engine.connect() as conn:
            # pg_indexes carries the indexdef; we assert the access
            # method + the column appear in the definition. This is
            # more robust than parsing pg_class / pg_am directly across
            # pgvector versions.
            row = (
                await conn.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes "
                        "WHERE indexname = :name AND tablename = :tbl"
                    ),
                    {"name": _INDEX_NAME, "tbl": _TABLE_NAME},
                )
            ).first()
        assert row is not None, (
            f"v019 did not create index {_INDEX_NAME} on {_TABLE_NAME}"
        )
        indexname, indexdef = row[0], row[1]
        assert indexname == _INDEX_NAME
        # The CREATE INDEX statement reconstructed in pg_indexes.indexdef
        # mentions ``hnsw`` as the access method and ``embedding`` as
        # the indexed column.
        assert "hnsw" in indexdef.lower(), (
            f"expected hnsw access method in indexdef; got: {indexdef}"
        )
        assert "embedding" in indexdef.lower(), (
            f"expected ``embedding`` in indexdef; got: {indexdef}"
        )
    finally:
        # Best-effort cleanup so re-runs against a long-lived Postgres
        # don't accumulate the index across test invocations.
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_v019_idempotent_on_postgres() -> None:
    """Re-applying v019 on Postgres is safe (IF NOT EXISTS).

    Skips cleanly when pgvector isn't reachable.
    """
    url = _postgres_url_or_skip()
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await V016Migration().up(conn)
            await V017Migration().up(conn)
            await V018Migration().up(conn)
            await V019Migration().up(conn)
            # Second apply — must not raise.
            await V019Migration().up(conn)
        async with engine.connect() as conn:
            count = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM pg_indexes "
                        "WHERE indexname = :name AND tablename = :tbl"
                    ),
                    {"name": _INDEX_NAME, "tbl": _TABLE_NAME},
                )
            ).scalar()
        assert count == 1, (
            f"expected exactly one HNSW index after double-apply; got {count}"
        )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_v019_honours_env_params_on_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Custom env values land in the index's reloptions on Postgres.

    Sets WORMBASE_HNSW_M=24, WORMBASE_HNSW_EF_CONSTRUCTION=128 and asserts
    those values appear in the reconstructed ``pg_indexes.indexdef``.

    Skips cleanly when pgvector isn't reachable.
    """
    url = _postgres_url_or_skip()
    monkeypatch.setenv(_ENV_M, "24")
    monkeypatch.setenv(_ENV_EF_CONSTRUCTION, "128")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await V016Migration().up(conn)
            await V017Migration().up(conn)
            await V018Migration().up(conn)
            await V019Migration().up(conn)
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname = :name AND tablename = :tbl"
                    ),
                    {"name": _INDEX_NAME, "tbl": _TABLE_NAME},
                )
            ).first()
        assert row is not None, "v019 did not create index with env params"
        indexdef = row[0].lower()
        # Postgres reconstructs the reloptions in the indexdef string.
        # Format is typically ``WITH (m='24', ef_construction='128')``
        # or ``WITH (m=24, ef_construction=128)`` depending on version;
        # assert both numbers appear alongside their option names.
        assert "m=" in indexdef.replace(" ", "") or "m =" in indexdef, indexdef
        assert "ef_construction" in indexdef, indexdef
        assert "24" in indexdef, f"expected m=24 in {indexdef}"
        assert "128" in indexdef, f"expected ef_construction=128 in {indexdef}"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_v019_changed_env_is_noop_due_to_if_not_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing env vars + re-applying is STILL a no-op (IF NOT EXISTS).

    This pins the runbook's central operator-facing claim: to actually
    re-tune, you must ``DROP INDEX`` first. We assert that re-applying
    v019 after changing the env does NOT rebuild the index with new
    params.

    Skips cleanly when pgvector isn't reachable.
    """
    url = _postgres_url_or_skip()
    monkeypatch.setenv(_ENV_M, "16")
    monkeypatch.setenv(_ENV_EF_CONSTRUCTION, "64")
    engine = create_async_engine(url)
    try:
        # First apply with defaults (m=16, ef_construction=64).
        async with engine.begin() as conn:
            await V016Migration().up(conn)
            await V017Migration().up(conn)
            await V018Migration().up(conn)
            await V019Migration().up(conn)
        # Capture the original DDL.
        async with engine.connect() as conn:
            before = (
                await conn.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname = :name AND tablename = :tbl"
                    ),
                    {"name": _INDEX_NAME, "tbl": _TABLE_NAME},
                )
            ).scalar()
        # Change env vars to non-defaults and re-apply.
        monkeypatch.setenv(_ENV_M, "32")
        monkeypatch.setenv(_ENV_EF_CONSTRUCTION, "200")
        async with engine.begin() as conn:
            await V019Migration().up(conn)
        async with engine.connect() as conn:
            after = (
                await conn.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE indexname = :name AND tablename = :tbl"
                    ),
                    {"name": _INDEX_NAME, "tbl": _TABLE_NAME},
                )
            ).scalar()
        # IF NOT EXISTS short-circuits — DDL is unchanged. This is the
        # invariant the operator runbook documents.
        assert before == after, (
            "expected IF NOT EXISTS to short-circuit; DDL changed: "
            f"before={before!r} after={after!r}"
        )
        # Sanity: the index still carries m=16 / ef_construction=64, NOT
        # the new env values.
        assert "32" not in (after or "") or "16" in (after or ""), (
            f"index appears to have been rebuilt with new env values: {after}"
        )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))
        await engine.dispose()
