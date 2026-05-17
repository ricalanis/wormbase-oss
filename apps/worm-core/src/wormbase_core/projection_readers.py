"""Projection-table readers for the v2.B Phase 3c projection-promoted gather.

v2.B Phase 3b populated ``projection_query_outcomes.embedding`` at
write-time when ``WORMBASE_EMBEDDING_ENABLED=true`` lights the
``OllamaCloudEmbeddingService``. Phase 3c (2026-05-12) closes the loop
on the read side: the agent-gateway axes 1 + 3 ``gather_fn`` can now
fetch a TopK pre-filtered candidate set directly from the projection
table (with a pgvector cosine pre-filter on Postgres), instead of
scanning the full ledger for every fire.

This module ships the production reader. It satisfies the
``QueryOutcomeProjectionReader`` Protocol consumed by
``_make_gather_via_projection`` in
``packages/wormbase-agent-gateway/src/wormbase_agent_gateway/reactivities.py``.

Two concrete impls share the same Protocol surface:

- :class:`PostgresQueryOutcomeProjectionReader` — uses the pgvector
  ``<=>`` cosine-distance operator for a SQL-side TopK ORDER BY when
  the triggering entry carries an embedding; falls back to a plain
  date-window SELECT when it does not.
- :class:`SqliteQueryOutcomeProjectionReader` — SQLite has no pgvector;
  the reader SELECTs the day-window rows and ranks by cosine similarity
  in Python (deterministic, replay-safe).

Both impls:

* enforce multi-tenant isolation via a non-optional
  ``WHERE company_id = $1`` clause at the SQL layer (Decision D4);
* honour the ``ts >= now() - days`` day-window pre-filter so the
  gather window matches the Phase 1+2 ledger-scan semantics
  (Decision D3);
* gracefully fall back to a non-vector query when the triggering entry
  has no embedding (Decision D3 fallback branch);
* return rows reshaped to look like entry-dicts (kind / payload.args
  with ``nl_question`` / ``agent_query_id`` / ``embedding`` / etc.) so
  the existing ``cluster_fn`` consumes them unchanged (Decision D1).

The reader is opt-in: the agent-gateway factories default
``projection_reader=None`` and the existing ledger-scan path runs
unchanged. Worm-core's ``agent_gateway_construction`` flips the wire
on when ``WORMBASE_GATHER_VIA_PROJECTION=true`` is set.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, Sequence
from uuid import UUID


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class QueryOutcomeProjectionReader(Protocol):
    """Read recent ``projection_query_outcomes`` rows, optionally TopK-pre-filtered.

    Two call shapes:

    * ``triggering_embedding`` is provided: return up to ``topk_limit``
      rows in the day-window ordered by ascending cosine distance to
      the triggering vector. Postgres uses pgvector ``<=>``; SQLite
      computes cosine in Python.
    * ``triggering_embedding is None``: return all rows in the day
      window (no ordering guarantee beyond the underlying index).
      Phase 1+2 byte-identical fallback when the triggering entry
      has no embedding.

    Multi-tenant: ``company_id`` is non-optional; impls MUST filter
    on it at the SQL layer.
    """

    async def recent_outcomes(
        self,
        *,
        company_id: UUID,
        triggering_embedding: Sequence[float] | None,
        days: int,
        topk_limit: int,
        now: datetime,
    ) -> list[dict[str, Any]]:  # pragma: no cover - Protocol
        ...


# ---------------------------------------------------------------------------
# Reshape helper — Decision D1
# ---------------------------------------------------------------------------


def _reshape_projection_row_to_entry(
    row: dict[str, Any],
) -> dict[str, Any]:
    """Reshape a ``projection_query_outcomes`` row into an entry-shaped
    dict the cluster_fn / quality_filter consumes.

    The downstream cluster_fn reads ``payload.args`` for
    ``nl_question`` / ``final_query_spec`` / ``embedding`` / ``used`` /
    ``useful`` / ``quality_score``. We rebuild that shape so the
    cluster_fn does not need to learn about projection rows.

    Replay-safety: the synthesized entry never lands in the ledger;
    only ``cluster_fn``-internal references survive past one fire.
    """
    embedding = row.get("embedding")
    # The Postgres pgvector column comes back as a list[float]; SQLite
    # may yield a JSON-string. Normalize to list[float] or None.
    if isinstance(embedding, str):
        try:
            embedding = json.loads(embedding)
        except (TypeError, ValueError):
            embedding = None
    if embedding is not None and not isinstance(embedding, (list, tuple)):
        embedding = None

    args: dict[str, Any] = {
        "agent_query_id": row.get("agent_query_id"),
        "nl_question": row.get("nl_question") or "",
        "final_query_spec": row.get("final_query_spec") or {},
        "result_summary": row.get("result_summary") or {},
        "used": bool(row.get("used", False)),
        "useful": bool(row.get("useful", False)),
        "user_correction": row.get("user_correction"),
        "quality_score": str(row.get("quality_score") or "0"),
    }
    if embedding is not None:
        args["embedding"] = list(embedding)

    # Mirror the ledger row shape just enough for cluster_fn / action
    # consumers: ``kind == "execute"``, ``payload.tool ==
    # "emit_query_outcome_recorded"``, ``payload.args`` carries the
    # outcome fields. ``entry_id`` rides through unchanged so the
    # promotion-action's ``promoted_from_outcome_ids`` reproduces the
    # ledger-scan path verbatim.
    entry: dict[str, Any] = {
        "kind": "execute",
        "entry_id": row.get("id") or row.get("entry_id"),
        "seq": row.get("entry_seq", 0),
        "ts": row.get("ts") or row.get("recorded_at"),
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": args,
            "result_ref": str(row.get("agent_query_id") or ""),
        },
    }
    return entry


# ---------------------------------------------------------------------------
# Postgres impl
# ---------------------------------------------------------------------------


@dataclass
class PostgresQueryOutcomeProjectionReader:
    """Production projection-table reader for Postgres + pgvector.

    Construction takes an ``AsyncEngine`` (or anything that satisfies
    the ``async with engine.connect()`` context manager — typically
    ``ledger.engine``). The reader does not own the engine; it merely
    holds a reference and opens read-only connections.

    pgvector path: when ``triggering_embedding`` is supplied, the SQL
    is::

        SELECT ... FROM projection_query_outcomes
         WHERE company_id = :cid
           AND recorded_at >= :cutoff
           AND embedding IS NOT NULL
         ORDER BY embedding <=> CAST(:emb AS vector)
         LIMIT :k

    Fallback: when ``triggering_embedding`` is None, the ORDER BY is
    omitted and a plain windowed SELECT runs. Both paths enforce the
    non-optional ``company_id`` filter at the SQL layer.

    Note: this reader will only succeed against an actual Postgres
    engine with pgvector ≥0.6 installed. SQLite test paths use
    :class:`SqliteQueryOutcomeProjectionReader` instead.
    """

    engine: Any

    async def recent_outcomes(
        self,
        *,
        company_id: UUID,
        triggering_embedding: Sequence[float] | None,
        days: int,
        topk_limit: int,
        now: datetime,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import text as _text

        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        cutoff = now - timedelta(days=days)

        if triggering_embedding is not None:
            # pgvector cosine-distance ordering. The "<=>" operator is
            # pgvector's cosine distance (= 1 - cosine_similarity). We
            # ORDER BY ASC so the closest match comes first; LIMIT
            # bounds the TopK.
            # The embedding is bound as a JSON-array text and cast to
            # ``vector`` via the explicit ``CAST(:emb AS vector)``;
            # pgvector understands the textual ``[v1, v2, ...]`` form.
            emb_literal = "[" + ",".join(
                str(float(v)) for v in triggering_embedding
            ) + "]"
            sql = _text(
                """
                SELECT
                    id,
                    company_id,
                    agent_query_id,
                    nl_question,
                    final_query_spec,
                    result_summary,
                    used,
                    useful,
                    user_correction,
                    quality_score,
                    embedding,
                    recorded_at
                  FROM projection_query_outcomes
                 WHERE company_id = :cid
                   AND recorded_at >= :cutoff
                   AND embedding IS NOT NULL
                 ORDER BY embedding <=> CAST(:emb AS vector)
                 LIMIT :k
                """
            )
            params: dict[str, Any] = {
                "cid": str(company_id),
                "cutoff": cutoff,
                "emb": emb_literal,
                "k": int(topk_limit),
            }
        else:
            # Non-vector fallback. Still cheaper than ledger-scan because
            # the projection table is pre-folded and indexed on
            # company_id.
            sql = _text(
                """
                SELECT
                    id,
                    company_id,
                    agent_query_id,
                    nl_question,
                    final_query_spec,
                    result_summary,
                    used,
                    useful,
                    user_correction,
                    quality_score,
                    embedding,
                    recorded_at
                  FROM projection_query_outcomes
                 WHERE company_id = :cid
                   AND recorded_at >= :cutoff
                 LIMIT :k
                """
            )
            params = {
                "cid": str(company_id),
                "cutoff": cutoff,
                "k": int(topk_limit),
            }

        rows: list[dict[str, Any]] = []
        async with self.engine.connect() as conn:
            result = await conn.execute(sql, params)
            for r in result.mappings():
                row_dict = dict(r)
                # Map the SQL column names into the entry-reshape
                # contract.
                row_dict["ts"] = row_dict.get("recorded_at")
                rows.append(_reshape_projection_row_to_entry(row_dict))
        return rows


# ---------------------------------------------------------------------------
# SQLite impl
# ---------------------------------------------------------------------------


def _cosine_similarity(
    a: Sequence[float], b: Sequence[float],
) -> float:
    """Pure-Python cosine similarity for the SQLite ranking path.

    Mirrors the deterministic implementation in
    ``wormbase_agent_gateway.reactivities._cosine_similarity``. Kept
    local so this module has zero cross-package runtime dependency on
    the agent-gateway.

    Returns 0.0 on zero-magnitude vectors (cosine undefined).
    """
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += float(x) * float(y)
        na += float(x) * float(x)
        nb += float(y) * float(y)
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    from math import sqrt
    return dot / (sqrt(na) * sqrt(nb))


@dataclass
class SqliteQueryOutcomeProjectionReader:
    """SQLite-compatible projection-table reader.

    SQLite does not ship pgvector. The reader still benefits from the
    projection table over a full ledger scan (one row per recorded
    outcome, pre-filtered by ``company_id`` + ``recorded_at``); the
    cosine ranking step happens in Python after the SELECT.

    The Python ranking is deterministic — same inputs, same output —
    so wire-replay reproduces the same gather set across two runs
    (Decision D5).
    """

    engine: Any

    async def recent_outcomes(
        self,
        *,
        company_id: UUID,
        triggering_embedding: Sequence[float] | None,
        days: int,
        topk_limit: int,
        now: datetime,
    ) -> list[dict[str, Any]]:
        from sqlalchemy import text as _text

        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        cutoff = now - timedelta(days=days)

        # SQLite stores recorded_at as a timezone-aware ISO string via
        # SQLAlchemy's DateTime(timezone=True); bind the cutoff as a
        # datetime and let SQLAlchemy adapt it.
        sql = _text(
            """
            SELECT
                id,
                company_id,
                agent_query_id,
                nl_question,
                final_query_spec,
                result_summary,
                used,
                useful,
                user_correction,
                quality_score,
                embedding,
                recorded_at
              FROM projection_query_outcomes
             WHERE company_id = :cid
               AND recorded_at >= :cutoff
            """
        )
        params: dict[str, Any] = {
            "cid": str(company_id),
            "cutoff": cutoff,
        }

        raw_rows: list[dict[str, Any]] = []
        async with self.engine.connect() as conn:
            result = await conn.execute(sql, params)
            for r in result.mappings():
                raw_rows.append(dict(r))

        # When we have a triggering embedding, rank by cosine
        # similarity in Python; keep the top-K. When we don't, return
        # the day-window rows up to topk_limit (the order is
        # insertion-order from the projection table; the cluster_fn
        # does not rely on ordering).
        if triggering_embedding is not None:
            trig = [float(v) for v in triggering_embedding]
            scored: list[tuple[float, dict[str, Any]]] = []
            for r in raw_rows:
                emb = r.get("embedding")
                if isinstance(emb, str):
                    try:
                        emb = json.loads(emb)
                    except (TypeError, ValueError):
                        emb = None
                if not isinstance(emb, (list, tuple)) or not emb:
                    # Row has no embedding — skip from cosine ranking
                    # (matches the Postgres ``embedding IS NOT NULL``
                    # filter in the vector path).
                    continue
                try:
                    emb_vec = [float(v) for v in emb]
                except (TypeError, ValueError):
                    continue
                sim = _cosine_similarity(trig, emb_vec)
                # Higher similarity → smaller cosine-distance; sort
                # ascending-by-distance ⇔ descending-by-similarity.
                scored.append((-sim, r))
            scored.sort(key=lambda t: t[0])
            ranked = [t[1] for t in scored[: int(topk_limit)]]
        else:
            ranked = raw_rows[: int(topk_limit)]

        out: list[dict[str, Any]] = []
        for r in ranked:
            r2 = dict(r)
            r2["ts"] = r2.get("recorded_at")
            out.append(_reshape_projection_row_to_entry(r2))
        return out


# ---------------------------------------------------------------------------
# Convenience: dialect-aware factory
# ---------------------------------------------------------------------------


def make_projection_reader_for_engine(
    engine: Any,
) -> QueryOutcomeProjectionReader:
    """Return the appropriate reader for ``engine``'s dialect.

    Inspects ``engine.dialect.name`` (sqlalchemy convention). Postgres
    deployments get the pgvector-capable reader; SQLite gets the
    Python-cosine reader. Any other dialect falls back to the SQLite
    impl (cosine in Python is universally portable).
    """
    dialect_name = ""
    try:
        dialect_name = str(getattr(engine.dialect, "name", "") or "")
    except Exception:
        dialect_name = ""
    if dialect_name.startswith("postgres"):
        return PostgresQueryOutcomeProjectionReader(engine=engine)
    return SqliteQueryOutcomeProjectionReader(engine=engine)


__all__ = [
    "PostgresQueryOutcomeProjectionReader",
    "QueryOutcomeProjectionReader",
    "SqliteQueryOutcomeProjectionReader",
    "make_projection_reader_for_engine",
]
