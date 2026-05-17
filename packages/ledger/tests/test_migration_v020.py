"""v020 migration — dim-flexible embedding columns.

The SQLite path is a no-op (embedding is JSON-shaped, dim-agnostic);
the Postgres path reads ``WORMBASE_EMBEDDING_DIM`` and conditionally
ALTERs ``projection_query_outcomes.embedding`` +
``projection_query_templates.embedding`` to the target dim. The SQLite
tests here verify the no-op + idempotency + migration registration;
the env-knob resolution helper is exercised dialect-agnostically.

The Postgres ALTER path itself is gated on
``WORMBASE_INTEGRATION_DB=1`` (matching v019's convention) so the
SQLite-only suite stays runnable without integration deps.
"""
from __future__ import annotations

import os

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
from wormbase_ledger.projections.migrations.v019_hnsw_index_query_outcomes import (
    Migration as V019Migration,
)
from wormbase_ledger.projections.migrations.v020_dim_flexible_embedding import (
    EmbeddingDimMigrationError,
    Migration as V020Migration,
    _DEFAULT_DIM,
    _ENV_DIM,
    _SUPPORTED_DIMS,
    _resolve_target_dim,
)


# ---------------------------------------------------------------------------
# SQLite path — always exercised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v020_is_noop_on_sqlite() -> None:
    """SQLite stores embedding as JSON; v020 is a no-op (no schema change)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V016Migration().up(conn)
        await V017Migration().up(conn)
        await V018Migration().up(conn)
        await V019Migration().up(conn)
    # Apply v020 — must not raise on SQLite.
    async with engine.begin() as conn:
        await V020Migration().up(conn)
    # Tables still exist with the same shape.
    async with engine.connect() as conn:
        cols_outcomes = await conn.run_sync(
            lambda sc: {
                c["name"]
                for c in inspect(sc).get_columns("projection_query_outcomes")
            }
        )
        cols_templates = await conn.run_sync(
            lambda sc: {
                c["name"]
                for c in inspect(sc).get_columns("projection_query_templates")
            }
        )
    assert "embedding" in cols_outcomes
    assert "embedding" in cols_templates


@pytest.mark.asyncio
async def test_v020_idempotent_on_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-applying v020 on SQLite is safe at default dim AND at mxbai dim.

    The JSON-backed mirror is dim-agnostic, so even flipping the env to
    1024 between applies must stay a no-op on SQLite — the cross-model
    swap only requires a schema change on Postgres.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V016Migration().up(conn)
        await V017Migration().up(conn)
        await V018Migration().up(conn)
        await V019Migration().up(conn)
        await V020Migration().up(conn)
    # Re-apply at the default dim.
    async with engine.begin() as conn:
        await V020Migration().up(conn)
    # Flip env to mxbai-embed-large's 1024 dim and re-apply — still a
    # no-op on SQLite (JSON column, no schema change).
    monkeypatch.setenv(_ENV_DIM, "1024")
    async with engine.begin() as conn:
        await V020Migration().up(conn)


@pytest.mark.asyncio
async def test_v020_preserves_json_embedding_at_1024_on_sqlite() -> None:
    """After v020 with mxbai dim, SQLite round-trips a 1024-length list.

    The JSON-backed mirror has no schema enforcement on length; this
    test pins that v020 doesn't accidentally truncate or reject a
    longer vector. Mirrors the v018 round-trip test for the new dim.
    """
    import json as _json
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await V016Migration().up(conn)
        await V017Migration().up(conn)
        await V018Migration().up(conn)
        await V019Migration().up(conn)
        await V020Migration().up(conn)
    vec_1024 = [0.001 * i for i in range(1024)]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO projection_query_outcomes "
                "(id, company_id, agent_query_id, nl_question, "
                " final_query_spec, result_summary, used, useful, "
                " quality_score, embedding, recorded_at) "
                "VALUES ('o1', 'co1', 'q1', 'q?', "
                "'{}', '{}', 1, 1, "
                "0.9500, :emb, '2026-05-24T00:00:00Z')"
            ),
            {"emb": _json.dumps(vec_1024)},
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
    assert len(_json.loads(row[0])) == 1024


# ---------------------------------------------------------------------------
# Env-knob resolution (dialect-agnostic; runs everywhere)
# ---------------------------------------------------------------------------


def test_v020_dim_default_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env var set → defaults to 768 (matches Phase 3b ship pick).

    Pins the byte-identical-behaviour invariant: existing deployments
    without the env knob set get the same target dim as v018's hard-
    coded 768.
    """
    monkeypatch.delenv(_ENV_DIM, raising=False)
    assert _resolve_target_dim() == _DEFAULT_DIM == 768


def test_v020_dim_honours_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """``WORMBASE_EMBEDDING_DIM=1024`` (mxbai-embed-large) is accepted."""
    monkeypatch.setenv(_ENV_DIM, "1024")
    assert _resolve_target_dim() == 1024
    assert 1024 in _SUPPORTED_DIMS


def test_v020_dim_rejects_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Random dim → :class:`EmbeddingDimMigrationError`.

    The allowlist is intentional — :data:`_SUPPORTED_DIMS` mirrors
    ``SUPPORTED_EMBEDDING_MODELS``. An arbitrary dim could land
    half-configured (a 768-dim model + a 1536-dim column) and
    silently scramble cosine search.
    """
    monkeypatch.setenv(_ENV_DIM, "1536")
    with pytest.raises(EmbeddingDimMigrationError) as excinfo:
        _resolve_target_dim()
    msg = str(excinfo.value)
    assert "1536" in msg
    assert "768" in msg  # supported alternatives listed
    assert "1024" in msg


def test_v020_dim_rejects_non_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    """``WORMBASE_EMBEDDING_DIM=abc`` → loud raise."""
    monkeypatch.setenv(_ENV_DIM, "abc")
    with pytest.raises(EmbeddingDimMigrationError) as excinfo:
        _resolve_target_dim()
    assert "WORMBASE_EMBEDDING_DIM" in str(excinfo.value)
    assert "abc" in str(excinfo.value)


def test_v020_dim_empty_env_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty string → default 768 (matches v019's empty-as-unset rule).

    Some container orchestrators export unset envs as empty strings;
    we treat empty as unset rather than non-integer so deployments
    don't boot-fail on a vacuous env declaration.
    """
    monkeypatch.setenv(_ENV_DIM, "")
    assert _resolve_target_dim() == _DEFAULT_DIM


# ---------------------------------------------------------------------------
# Registration / monotonicity
# ---------------------------------------------------------------------------


def test_v020_registered_in_canonical_migrations() -> None:
    """V020 follows v019 monotonically with no gaps."""
    versions = [m.version for m in MIGRATIONS]
    assert versions == sorted(versions), f"out of order: {versions}"
    assert 20 in versions, f"expected v20; got {versions}"
    assert versions == list(range(1, max(versions) + 1)), (
        f"gap detected: {versions}"
    )


def test_v020_description_documents_dim_flexibility() -> None:
    """The migration description names the dim-flexible behaviour and
    both target tables so log scans surface the cross-model swap path."""
    m = V020Migration()
    assert "dim-flexible" in m.description or "dim flexible" in m.description
    assert "projection_query_outcomes" in m.description
    assert "projection_query_templates" in m.description


def test_v020_is_forward_only() -> None:
    """Invariant M4 (from test_migrations_edge): no down() method.

    Pinned per-migration so a regression here is caught without having
    to run the full edge suite.
    """
    m = V020Migration()
    assert getattr(m, "down", None) is None


# ---------------------------------------------------------------------------
# Postgres path — env-gated; skip cleanly when pgvector isn't reachable
# ---------------------------------------------------------------------------


def _postgres_url_or_skip() -> str:
    """Return a Postgres test URL or skip the test.

    Mirrors v019's gating: honours ``WORMBASE_INTEGRATION_DB=1`` +
    ``WORMBASE_TEST_DB_URL``. Skips cleanly when no Postgres /
    pgvector endpoint is available so the SQLite-only suite stays
    runnable without integration deps.
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
async def test_v020_idempotent_at_default_dim_on_postgres() -> None:
    """Postgres: v020 at default dim (768) on a fresh v018 column → no-op.

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
            # First apply.
            await V020Migration().up(conn)
            # Second apply — must not raise.
            await V020Migration().up(conn)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_v020_refuses_to_drop_non_null_data_on_postgres() -> None:
    """Postgres: column has data + env requests different dim → raises.

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
            await V020Migration().up(conn)
        # Stamp a row with a non-NULL embedding at the current 768 dim.
        vec_768 = "[" + ",".join(str(0.001 * i) for i in range(768)) + "]"
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO projection_query_outcomes "
                    "(id, company_id, agent_query_id, nl_question, "
                    " final_query_spec, result_summary, used, useful, "
                    " quality_score, embedding, recorded_at) "
                    "VALUES ('o1', 'co1', 'q1', 'q?', "
                    "'{}', '{}', 1, 1, "
                    f"0.9500, '{vec_768}'::vector, "
                    "'2026-05-24T00:00:00Z')"
                )
            )
        # Now ask for the 1024-dim swap — must refuse.
        os.environ[_ENV_DIM] = "1024"
        try:
            async with engine.begin() as conn:
                with pytest.raises(EmbeddingDimMigrationError) as excinfo:
                    await V020Migration().up(conn)
            assert "non-NULL data" in str(excinfo.value)
            assert "1024" in str(excinfo.value)
        finally:
            del os.environ[_ENV_DIM]
    finally:
        # Clean up the inserted row so re-runs against a long-lived
        # Postgres don't accumulate state.
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM projection_query_outcomes WHERE id = 'o1'")
            )
        await engine.dispose()
