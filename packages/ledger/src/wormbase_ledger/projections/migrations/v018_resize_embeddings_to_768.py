"""v018 — resize ``embedding`` columns 1536 → 768 to match nomic-embed-text.

v2.B Phase 3b (2026-05-12). The v016 + v017 migrations pinned the
``embedding`` column to ``Vector(1536)`` (matching OpenAI's
``text-embedding-3-small`` output), but the Phase 3b ship pick is
Ollama Cloud's ``nomic-embed-text`` (768 dim, free, well-supported).

Safe migration because the column has been ALWAYS NULL since v016
landed — no embedding writer existed before Phase 3b. We can drop and
re-create the column at 768 dim with zero data loss.

Postgres path: ALTER TABLE … ALTER COLUMN … TYPE vector(768) USING NULL.
The USING NULL cast is the cheap path for the all-NULL case (Postgres
does NOT auto-cast vector(N) → vector(M) for N != M, but a NULL→NULL
cast is free).

SQLite path: no-op. The SQLite mirror stores the embedding as ``JSON``
list; the dim is implicit in the array length, so there's nothing to
alter. The fold-side persist will produce 768-length lists on Phase
3b writes.

Rationale (vs migrating in-place to 1024 for mxbai-embed-large):
nomic-embed-text is the default ship pick — free, fast, well-documented.
mxbai-embed-large (1024 dim) is the documented fallback; switching to
it would land as a follow-up v019.

Self-hosted Gemma is the long-term answer per the project's "own
inference" architecture (CLAUDE.md §3 "Remote inference vs own
inference"); Phase 3b uses Ollama Cloud as the pragmatic ship path
since the existing Ollama Cloud key already grants embed access.

Idempotency: detects the current column dim before altering; re-running
on an already-768 column is a no-op.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_TARGET_DIM: int = 768

_TARGET_TABLES: tuple[str, ...] = (
    "projection_query_outcomes",
    "projection_query_templates",
)


class Migration:
    version: int = 18
    description: str = (
        "resize projection_query_outcomes + projection_query_templates "
        "embedding columns 1536 → 768 to match nomic-embed-text "
        "(v2.B Phase 3b)"
    )

    async def up(self, conn: Any) -> None:
        await conn.run_sync(self._alter)

    def _alter(self, sync_conn: Any) -> None:
        dialect = sync_conn.dialect.name if sync_conn.dialect else None
        if dialect == "postgresql":
            self._alter_postgres(sync_conn)
        else:
            # SQLite (and other dialects): embedding column is JSON.
            # No-op — the JSON shape is dim-agnostic. Folded data starts
            # producing 768-length arrays once Phase 3b writes land.
            logger.debug(
                "v018 migration: dialect=%s; embedding columns are JSON, "
                "skipping ALTER (no-op)",
                dialect,
            )

    def _alter_postgres(self, sync_conn: Any) -> None:
        """Postgres: ALTER COLUMN … TYPE vector(768) USING NULL.

        The ``USING NULL`` cast is critical — Postgres does not provide
        a default cast between ``vector(1536)`` and ``vector(768)``,
        but since the column has been ALWAYS NULL since v016, we can
        unconditionally NULL it during the type change. If a deployment
        somehow has non-NULL 1536-dim data, this migration is unsafe
        and will be detected by the pre-flight check below.
        """
        from sqlalchemy import text  # local import — used only on Postgres

        # Pre-flight: refuse to drop non-NULL embeddings. The v016/v017
        # columns have been always-NULL since they landed; if a
        # deployment surprised us with real 1536-dim vectors we'd
        # rather defer the migration than silently destroy them.
        for tbl in _TARGET_TABLES:
            row = sync_conn.execute(
                text(
                    f"SELECT COUNT(*) FROM {tbl} WHERE embedding IS NOT NULL"
                )
            ).scalar()
            if row and row > 0:
                raise RuntimeError(
                    f"v018: {tbl}.embedding has {row} non-NULL row(s); "
                    "refusing to resize 1536→768 (would lose data). "
                    "Re-embed the existing rows at 768 first OR delete "
                    "them, then re-run."
                )

        for tbl in _TARGET_TABLES:
            # Idempotency: check current dim. atttypmod for vector(N)
            # encodes N as ``atttypmod`` (no +4 offset like varchar).
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
            if existing_dim == _TARGET_DIM:
                logger.debug(
                    "v018 migration: %s.embedding is already %d-dim; skip",
                    tbl, _TARGET_DIM,
                )
                continue
            # Cast via USING NULL — see docstring.
            sync_conn.execute(
                text(
                    f"ALTER TABLE {tbl} "
                    f"ALTER COLUMN embedding "
                    f"TYPE vector({_TARGET_DIM}) USING NULL"
                )
            )
            logger.info(
                "v018 migration: %s.embedding resized to %d dim",
                tbl, _TARGET_DIM,
            )
