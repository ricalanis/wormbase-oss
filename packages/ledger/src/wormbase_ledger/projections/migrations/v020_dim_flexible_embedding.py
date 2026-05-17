"""v020 — dim-flexible projection embedding columns (post-rest #6, 2026-05-24).

The v2.B Phase 3b ship pick was Ollama Cloud's ``nomic-embed-text``
(768 dim), encoded in v018 as ``Vector(768)``. Post-rest #6 ships the
``mxbai-embed-large`` (1024 dim) fallback path: env-knob-driven model
selection in :mod:`wormbase_inference.embedding` plus this migration's
**dim-flexible ALTER** path.

The migration is deliberately conservative:

* **SQLite**: no-op. The mirror stores embeddings as JSON; the dim is
  implicit in the array length, so cross-model swap doesn't require
  schema change.
* **Postgres**: read ``WORMBASE_EMBEDDING_DIM`` (default 768).

  - Columns at the target dim → no-op (idempotent).
  - Columns at a different dim AND containing data →
    :class:`EmbeddingDimMigrationError`. Refuses to ALTER because the
    cast would silently drop the existing vectors. The operator must
    explicitly clear them first (see runbook).
  - Columns at a different dim AND empty → ALTER cleanly to the new
    dim with ``USING NULL`` (matches v018's safe-cast strategy).

The v019 slot was already taken by the HNSW index, so the v020 number
slot is the dim-flexibility migration. Cross-model swaps additionally
require dropping + re-creating the HNSW index — the runbook documents
the full procedure.

Idempotency:

  * unset ``WORMBASE_EMBEDDING_DIM`` AND existing column dim == 768 →
    no-op (default-default case).
  * ``WORMBASE_EMBEDDING_DIM=768`` AND existing dim == 768 → no-op.
  * ``WORMBASE_EMBEDDING_DIM=1024`` AND existing dim == 1024 → no-op.

Forward-only. No ``down`` method (matches the codebase's
``test_no_migration_exposes_a_down_method`` invariant).

See ``docs/superpowers/notes/2026-05-24-cross-model-embedding-migration.md``
for the operator runbook.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Supported embedding dims. Must stay in sync with
# :data:`wormbase_inference.embedding.SUPPORTED_EMBEDDING_MODELS`'s
# values. Keeping the constant local to the migration avoids a
# cross-package import at migration-apply time.
_SUPPORTED_DIMS: frozenset[int] = frozenset({768, 1024})

_DEFAULT_DIM: int = 768

_ENV_DIM: str = "WORMBASE_EMBEDDING_DIM"

_TARGET_TABLES: tuple[str, ...] = (
    "projection_query_outcomes",
    "projection_query_templates",
)


class EmbeddingDimMigrationError(RuntimeError):
    """Raised when v020 would silently destroy non-NULL embedding data.

    The cross-model swap is destructive by nature: a 768-dim vector
    cast to ``vector(1024)`` is a NULL. The migration refuses to make
    that decision implicitly — the operator must either clear the
    column manually or run the embedding backfill at the new dim.
    """


def _resolve_target_dim() -> int:
    """Resolve the target embedding dim from env, with validation.

    Returns :data:`_DEFAULT_DIM` (768) when unset / empty. Raises
    :class:`EmbeddingDimMigrationError` when the env value is
    non-integer or not in :data:`_SUPPORTED_DIMS`. Pulled into a
    helper so tests can exercise it without booting the migration.
    """
    raw = os.environ.get(_ENV_DIM)
    if raw is None or raw == "":
        return _DEFAULT_DIM
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise EmbeddingDimMigrationError(
            f"{_ENV_DIM}={raw!r} is not a valid integer; expected one of "
            f"{sorted(_SUPPORTED_DIMS)} or unset (default {_DEFAULT_DIM}). "
            f"See docs/superpowers/notes/2026-05-24-cross-model-embedding-migration.md."
        ) from exc
    if value not in _SUPPORTED_DIMS:
        raise EmbeddingDimMigrationError(
            f"{_ENV_DIM}={value} is not a supported embedding dim; "
            f"expected one of {sorted(_SUPPORTED_DIMS)}. "
            f"See docs/superpowers/notes/2026-05-24-cross-model-embedding-migration.md."
        )
    return value


class Migration:
    version: int = 20
    description: str = (
        "dim-flexible embedding columns on projection_query_outcomes + "
        "projection_query_templates — ALTER to WORMBASE_EMBEDDING_DIM "
        "(default 768) when current dim differs AND column is empty; "
        "no-op on SQLite (JSON); refuses to drop non-NULL data"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(self._alter)

    def _alter(self, sync_conn: Any) -> None:
        dialect = sync_conn.dialect.name if sync_conn.dialect else None
        if dialect == "postgresql":
            self._alter_postgres(sync_conn)
        else:
            # SQLite (and other dialects): embedding column is JSON.
            # No-op — the JSON shape is dim-agnostic.
            logger.debug(
                "v020 migration: dialect=%s; embedding columns are JSON, "
                "skipping ALTER (no-op)",
                dialect,
            )

    def _alter_postgres(self, sync_conn: Any) -> None:
        """Postgres: dim-flexible ALTER COLUMN per target table.

        Logic per table:

        1. Read the current vector dim from ``pg_attribute.atttypmod``
           (pgvector encodes ``vector(N)`` as ``atttypmod = N``).
        2. If column doesn't exist → silently skip (v018 owns column
           creation; if a deployment somehow lacks the column, v018
           should have failed first).
        3. If current dim == target dim → idempotent no-op.
        4. If current dim != target dim AND the column has non-NULL
           rows → raise :class:`EmbeddingDimMigrationError`.
        5. If current dim != target dim AND the column is empty →
           ``ALTER COLUMN ... TYPE vector(N) USING NULL`` (same safe
           cast as v018).
        """
        target_dim = _resolve_target_dim()

        for tbl in _TARGET_TABLES:
            existing_dim = sync_conn.execute(
                text(
                    """
                    SELECT a.atttypmod
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    WHERE c.relname = :tbl
                      AND a.attname = 'embedding'
                      AND NOT a.attisdropped
                    """
                ),
                {"tbl": tbl},
            ).scalar()

            if existing_dim is None:
                # Column or table absent. v018 / v016+v017 own creation;
                # an unexpected absence here means the migration order
                # was bypassed. Log and skip — surfacing a hard error
                # would block recovery on legitimately fresh installs
                # where the table is created later in the chain.
                logger.debug(
                    "v020 migration: %s.embedding column not found; "
                    "skipping (v018 owns column creation)",
                    tbl,
                )
                continue

            if existing_dim == target_dim:
                logger.debug(
                    "v020 migration: %s.embedding is already %d-dim; skip",
                    tbl, target_dim,
                )
                continue

            # Dim mismatch: refuse to destroy data, but allow ALTER on
            # an empty column. ``embedding IS NOT NULL`` is the safe
            # filter — any rows with stamped vectors block the ALTER.
            non_null = sync_conn.execute(
                text(
                    f"SELECT COUNT(*) FROM {tbl} WHERE embedding IS NOT NULL"
                )
            ).scalar()
            if non_null and non_null > 0:
                raise EmbeddingDimMigrationError(
                    f"v020: {tbl}.embedding is Vector({existing_dim}) with "
                    f"{non_null} row(s) of non-NULL data. Cannot ALTER to "
                    f"Vector({target_dim}) without data loss. Procedure: "
                    f"(1) drop rows where embedding IS NOT NULL, OR "
                    f"(2) NULL the column and run the embedding-backfill "
                    f"admin script at the new dim. See "
                    f"docs/superpowers/notes/2026-05-24-cross-model-embedding-migration.md."
                )

            # Empty column at a different dim → safe cast via USING NULL.
            sync_conn.execute(
                text(
                    f"ALTER TABLE {tbl} "
                    f"ALTER COLUMN embedding "
                    f"TYPE vector({target_dim}) USING NULL"
                )
            )
            logger.info(
                "v020 migration: %s.embedding resized %d → %d dim",
                tbl, existing_dim, target_dim,
            )
