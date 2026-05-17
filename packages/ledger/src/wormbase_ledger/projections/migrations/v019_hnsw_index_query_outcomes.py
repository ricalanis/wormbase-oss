"""v019 — HNSW index on projection_query_outcomes.embedding (Postgres only).

Phase 3c's projection-promoted gather (ledger-scan → ORDER BY embedding <=>
$vec LIMIT N) becomes scale-ready when the cosine column has an HNSW index.

pgvector ≥0.6 supports HNSW with ``vector_cosine_ops``. Without an index,
PostgreSQL falls back to seq scan + sort which is acceptable at <10K rows
per tenant but degrades sharply beyond. The semantic-layer projection-
promoted reader at
``apps/worm-core/src/wormbase_core/projection_readers.py`` uses ``<=>``
cosine distance ORDER BY, which HNSW with ``vector_cosine_ops`` accelerates.

The migration:

* Postgres: ``CREATE INDEX IF NOT EXISTS ... USING hnsw
  (embedding vector_cosine_ops)`` with sane defaults
  (``m = 16``, ``ef_construction = 64`` — pgvector's documented baseline
  trade-off between build cost and recall).
* SQLite: no-op (JSON column type; no vector index available).

Idempotent: re-running is safe (IF NOT EXISTS).

Replay-safe: the index is structural, derived from the data; replays
produce the same index automatically because they re-apply migrations
in order.

This is a follow-up to v018 (which resized 1536 → 768); the index applies
to the post-v018 column shape. Production deployments must verify pgvector
is installed AND at version ≥0.6 — HNSW support landed in 0.5.0 but the
``vector_cosine_ops`` operator family has been stable since 0.6.

Index naming follows the project convention
``ix_<table>_<column>_<index_type>``.

Tunable build params (post-rest #5, 2026-05-23):

The HNSW ``m`` and ``ef_construction`` parameters are read at migration-
apply time from environment variables. Defaults preserve the pgvector
documented baseline so existing deployments are byte-identical:

* ``WORMBASE_HNSW_M`` — max connections per layer (default 16; valid 4-64).
  Higher = better recall, slower build, more memory.
* ``WORMBASE_HNSW_EF_CONSTRUCTION`` — build-time search depth (default 64;
  valid 16-256). Higher = better quality, much slower build.

See ``docs/superpowers/notes/2026-05-23-hnsw-tuning-runbook.md`` for the
operator guidance: when to tune, how to re-tune (DROP INDEX + restart, as
``IF NOT EXISTS`` short-circuits on re-apply), and how to validate.

Invalid env values (non-integer, or out of range) raise a migration error
loudly — they do not silently fall back to defaults. This is intentional:
a misconfigured index in production would silently degrade recall, which
is far worse than a loud failure at boot.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import sqlalchemy as sa

logger = logging.getLogger(__name__)


_INDEX_NAME: str = "ix_projection_query_outcomes_embedding_hnsw"
_TABLE_NAME: str = "projection_query_outcomes"

# Documented pgvector ranges. See pgvector README / HNSW build-params section.
# These are not hard pgvector limits — they are the empirically-sane ranges
# pgvector's documentation recommends, and our gate enforces.
_M_DEFAULT: int = 16
_M_MIN: int = 4
_M_MAX: int = 64

_EF_CONSTRUCTION_DEFAULT: int = 64
_EF_CONSTRUCTION_MIN: int = 16
_EF_CONSTRUCTION_MAX: int = 256

_ENV_M: str = "WORMBASE_HNSW_M"
_ENV_EF_CONSTRUCTION: str = "WORMBASE_HNSW_EF_CONSTRUCTION"


class HnswParamError(ValueError):
    """Raised when an HNSW env knob is non-integer or out of documented range.

    The migration runner surfaces this loudly at apply-time. The intent is
    to refuse to build a misconfigured index rather than silently fall
    back to defaults — a wrong ``m`` or ``ef_construction`` value would
    quietly degrade recall in production.
    """


def _read_int_env(name: str, default: int, lo: int, hi: int) -> int:
    """Read an integer env var with range validation.

    Returns ``default`` when the env var is unset or empty. Raises
    ``HnswParamError`` with an operator-actionable message when the env
    value is non-integer or out of [lo, hi].
    """
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise HnswParamError(
            f"{name}={raw!r} is not a valid integer; expected an int in "
            f"[{lo}, {hi}] or unset (default {default}). See "
            f"docs/superpowers/notes/2026-05-23-hnsw-tuning-runbook.md."
        ) from exc
    if value < lo or value > hi:
        raise HnswParamError(
            f"{name}={value} is out of documented pgvector range "
            f"[{lo}, {hi}]; refusing to build a misconfigured HNSW index. "
            f"Default is {default}. See "
            f"docs/superpowers/notes/2026-05-23-hnsw-tuning-runbook.md."
        )
    return value


def _resolve_hnsw_params() -> tuple[int, int]:
    """Resolve (m, ef_construction) from env, with validation.

    Pulled into a helper so tests can exercise it without booting the
    migration. Called from ``_create`` at migration-apply time so each
    fresh boot picks up the current env values.
    """
    m = _read_int_env(_ENV_M, _M_DEFAULT, _M_MIN, _M_MAX)
    ef_construction = _read_int_env(
        _ENV_EF_CONSTRUCTION,
        _EF_CONSTRUCTION_DEFAULT,
        _EF_CONSTRUCTION_MIN,
        _EF_CONSTRUCTION_MAX,
    )
    return m, ef_construction


class Migration:
    version: int = 19
    description: str = (
        "create HNSW index on projection_query_outcomes.embedding "
        "(vector_cosine_ops, m=16, ef_construction=64 default; "
        "tunable via WORMBASE_HNSW_M / WORMBASE_HNSW_EF_CONSTRUCTION) — "
        "Postgres only; no-op on SQLite"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(self._create)

    def _create(self, sync_conn: Any) -> None:
        dialect = sync_conn.dialect.name if sync_conn.dialect else None
        if dialect != "postgresql":
            # SQLite (and other dialects): embedding column is JSON.
            # No vector index path exists; the projection-promoted
            # gather falls back to whatever sequential scan the
            # JSON-backed mirror supports. Tests for this path
            # exercise SQLite explicitly.
            logger.debug(
                "v019 migration: dialect=%s; no HNSW index path "
                "(SQLite stores embedding as JSON), skipping",
                dialect,
            )
            return

        # Resolve tunable params from env (with range validation). Any
        # invalid env value raises HnswParamError here — the migration
        # runner surfaces it as a startup failure, which is the loud
        # behaviour we want over silent fallback to defaults.
        m, ef_construction = _resolve_hnsw_params()

        # Postgres: build the HNSW index over vector_cosine_ops.
        # IF NOT EXISTS makes the migration idempotent so re-applies
        # (and migration-runner retries) are safe. NOTE: IF NOT EXISTS
        # short-circuits on index NAME — re-applying with different
        # env values is STILL a no-op. Operators must DROP INDEX
        # manually to re-tune. See the runbook for the procedure.
        sync_conn.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} "
                f"ON {_TABLE_NAME} "
                f"USING hnsw (embedding vector_cosine_ops) "
                f"WITH (m = {m}, ef_construction = {ef_construction})"
            )
        )
        logger.info(
            "v019 migration: created HNSW index %s on %s.embedding "
            "(vector_cosine_ops, m=%d, ef_construction=%d)",
            _INDEX_NAME,
            _TABLE_NAME,
            m,
            ef_construction,
        )
