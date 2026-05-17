"""One-shot CLI: backfill embeddings on pre-Phase-3b query_outcome_recorded entries.

v2.B Phase 3b (2026-05-12) wired write-time embedding generation on
``query_outcome_recorded`` entries via the ``EmbeddingService`` Protocol
behind the ``WORMBASE_EMBEDDING_ENABLED=true`` opt-in. v2.B Phase 3c
(also 2026-05-12) added a projection-promoted gather path
(``WORMBASE_GATHER_VIA_PROJECTION=true``) that reads
``projection_query_outcomes.embedding`` and ranks by cosine distance.

Installations that turn on the gather path BEFORE the embedding wire (or
that have outcomes recorded BEFORE Phase 3b shipped) hit the non-vector
fallback for every fire — correct but slow. This script closes that gap:
it computes embeddings for projection rows where ``embedding IS NULL``
and UPDATEs the column directly.

Design — projection-only backfill (Option A)
---------------------------------------------

The ledger is append-only and hash-chained: we cannot mutate a
``query_outcome_recorded`` entry's payload after the fact. Two viable
designs were considered:

* **Option A (chosen)**: UPDATE ``projection_query_outcomes.embedding``
  directly. The ledger entry stays ``embedding=None`` forever; the
  projection table is the source of truth for the embedding column.
  The Phase 3c reader already queries the projection table (not the
  raw ledger), so this is what matters for gather/cluster behavior.

* **Option B (rejected)**: Issue a compensating ledger entry kind
  (``query_outcome_embedding_backfilled``) that points at the original
  entry's seq and carries the computed embedding; the projection-fold
  then prefers the backfill's embedding over the original's None.

Option A wins because:

  1. Backfill is a one-time-per-installation admin operation; it doesn't
     deserve KIND_REGISTRY headroom.
  2. The Phase 3c reader's source of truth is already the projection
     table — no read site goes back to the raw ledger for the embedding
     column.
  3. Replay determinism is preserved: a fresh replay of the ledger
     followed by the backfill script produces the same projection state
     as the original-then-backfilled run (backfill is idempotent on the
     same NL text → same embedding from the same model).

Idempotency contract
--------------------

Re-running the backfill on the same input is safe:

* If ``projection_query_outcomes.embedding IS NOT NULL`` for a given
  row, the row is skipped (already backfilled).
* If ``embedding IS NULL``, the script computes the vector and UPDATEs.
* Per-row UPDATE: partial progress is durable. Network failures during
  ``EmbeddingService.embed()`` are logged and the row is skipped; the
  next run picks up where this one left off.
* Multi-tenant safety: ``--company-id`` is required and filters the
  SQL ``WHERE company_id = :cid`` at the source.

Usage
-----

::

    # Production usage — backfill last 30 days for one tenant, cap 1000.
    wormbase-embedding-backfill \\
        --company-id 12345678-1234-1234-1234-123456789abc \\
        --days 30 \\
        --max-count 1000

    # Dry-run: compute embeddings but write nothing.
    wormbase-embedding-backfill --company-id <UUID> --dry-run

    # Explicit Ollama key override (otherwise reads OLLAMA_API_KEY).
    wormbase-embedding-backfill --company-id <UUID> --ollama-key sk-...

    # Multi-tenant: discover tenants from the projection table and loop.
    wormbase-embedding-backfill --all-tenants --days 30

Multi-tenant mode (``--all-tenants``)
-------------------------------------

``--all-tenants`` and ``--company-id`` are mutually exclusive; exactly one
must be supplied. In multi-tenant mode the script discovers the active
tenant list from ``projection_query_outcomes`` (distinct ``company_id``s,
capped at 1000 for safety) and runs the same per-tenant ``run_backfill``
in sequence. Per-tenant failures (e.g. one tenant's Ollama rate-limit or
a DB hiccup) are logged and the loop continues with the remaining
tenants — one tenant's failure does NOT halt the run.

Exit code in multi-tenant mode reflects aggregate success: ``0`` if at
least one tenant's backfill completed, ``1`` if every tenant failed
catastrophically. (Per-row ``failed`` counts inside a tenant's
``BackfillReport`` are reported but do not flip the exit code — same
as single-tenant mode.)

Env knobs
---------

* ``WORMBASE_LEDGER_DSN`` — SQLAlchemy URL for the projection store.
* ``OLLAMA_API_KEY`` / ``OLLAMA_API_BASE`` /
  ``WORMBASE_EMBEDDING_MODEL`` / ``WORMBASE_EMBEDDING_DIM`` — passed
  through to :class:`OllamaCloudEmbeddingService`.

The CLI accepts ``--dsn`` for an explicit DSN override (mirrors the
``wormbase-worm-core run`` convention).
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID

import click
from sqlalchemy import text as sa_text

logger = logging.getLogger("wormbase_core.scripts.embedding_backfill")


_DEFAULT_DSN: str = "postgresql+asyncpg://wormbase:wormbase@postgres:5432/wormbase"

# Safety cap on multi-tenant fan-out. The discovery SELECT pulls distinct
# ``company_id`` values from ``projection_query_outcomes``; anything past
# this threshold is almost certainly a misconfigured shared DB rather than
# a legitimate tenant fleet, and we'd rather log + truncate than hammer
# Ollama Cloud for thousands of UUIDs. Operators who genuinely need >1000
# tenants in one run can split into multiple invocations with explicit
# ``--company-id`` per batch.
_MAX_TENANTS_PER_RUN: int = 1000


# ---------------------------------------------------------------------------
# Result accounting
# ---------------------------------------------------------------------------


@dataclass
class BackfillReport:
    """Tally of one backfill run, returned by :func:`run_backfill`.

    Fields are public so the CLI surface and tests both read the same
    shape. Counters monotonically increase as the script processes rows.
    """

    found: int = 0
    """Number of rows in scope (matched the SQL WHERE clause)."""

    processed: int = 0
    """Number of rows that received a freshly-computed embedding (and
    were UPDATEd, unless --dry-run)."""

    skipped_already_embedded: int = 0
    """Rows that already had ``embedding IS NOT NULL`` and were left
    untouched. Idempotency surface."""

    failed: int = 0
    """Rows where ``EmbeddingService.embed()`` raised; logged and skipped."""

    re_embedded_cross_model: int = 0
    """Rows whose existing embedding had a different dim than the target
    and were re-embedded as part of a cross-model migration. Always 0
    when ``--target-model`` is not set (existing rows are skipped, not
    re-embedded). Subset of :attr:`processed`."""

    dry_run: bool = False
    """Whether DB writes were suppressed."""

    duration_s: float = 0.0
    """Wall-clock seconds end-to-end (excludes ledger.dispose)."""

    failures: list[tuple[str, str]] = field(default_factory=list)
    """``(row_id, error_message)`` per failed row. Capped at 50 entries
    so a flood of errors doesn't balloon memory."""


# ---------------------------------------------------------------------------
# Core: find candidate rows
# ---------------------------------------------------------------------------


async def _find_candidate_rows(
    engine: Any,
    *,
    company_id: UUID,
    days: int | None,
    max_count: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """Return projection rows in scope, ordered by ``recorded_at`` ASC.

    Scope:

    * ``company_id`` (required) — multi-tenant filter at SQL.
    * ``days`` (optional) — when provided, restricts to rows with
      ``recorded_at >= now - days``. ``None`` means "all history".
    * ``max_count`` — caps the returned set; the script processes at
      most this many rows.

    Returns BOTH already-embedded and not-yet-embedded rows in scope.
    The skip decision happens row-by-row in :func:`run_backfill` so the
    report can distinguish "skipped because already embedded" from "not
    in scope".
    """
    where_clauses = ["company_id = :cid"]
    params: dict[str, Any] = {"cid": str(company_id), "lim": int(max_count)}

    if days is not None:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        params["cutoff"] = now - timedelta(days=int(days))
        where_clauses.append("recorded_at >= :cutoff")

    where_sql = " AND ".join(where_clauses)
    sql = sa_text(
        f"""
        SELECT id, company_id, nl_question, embedding, recorded_at
          FROM projection_query_outcomes
         WHERE {where_sql}
         ORDER BY recorded_at ASC
         LIMIT :lim
        """
    )

    out: list[dict[str, Any]] = []
    async with engine.connect() as conn:
        result = await conn.execute(sql, params)
        for r in result.mappings():
            out.append(dict(r))
    return out


# ---------------------------------------------------------------------------
# Core: detect existing embedding (dialect-tolerant)
# ---------------------------------------------------------------------------


def _row_has_embedding(row: dict[str, Any]) -> bool:
    """True iff this projection row already carries an embedding.

    SQLite stores the embedding as a JSON string (could be ``"null"`` or
    a list literal); Postgres + pgvector returns a list. Treat any
    non-empty list as "already embedded".
    """
    return _row_embedding_dim(row) > 0


def _row_embedding_dim(row: dict[str, Any]) -> int:
    """Return the dim of this row's persisted embedding, or 0 if absent.

    SQLite stores the embedding as a JSON string; Postgres + pgvector
    returns a list. A return of 0 means "no embedding" (NULL, empty
    list, or unparseable JSON). Used by cross-model migration mode
    (``--target-model``) to detect rows whose existing vector was
    produced by a different model and needs re-embedding.
    """
    import json as _json

    emb = row.get("embedding")
    if emb is None:
        return 0
    if isinstance(emb, str):
        try:
            emb = _json.loads(emb)
        except (TypeError, ValueError):
            return 0
    if isinstance(emb, (list, tuple)):
        return len(emb)
    return 0


# ---------------------------------------------------------------------------
# Core: write embedding
# ---------------------------------------------------------------------------


async def _update_embedding(
    engine: Any,
    *,
    row_id: str,
    company_id: UUID,
    embedding: Sequence[float],
) -> None:
    """UPDATE projection_query_outcomes.embedding for a single row.

    Dialect-aware bind:

    * SQLite: serialize the vector to a JSON-array string (the column
      is ``JSON`` on SQLite per v016).
    * Postgres + pgvector: bind a textual ``[v1,v2,...]`` literal and
      cast via ``CAST(:emb AS vector)``. Matches the pattern used by
      :class:`PostgresQueryOutcomeProjectionReader`.

    The ``WHERE company_id = :cid`` clause re-asserts multi-tenant
    isolation at the SQL layer (defense-in-depth — the caller already
    filtered by company in the SELECT).
    """
    import json as _json

    dialect_name = ""
    try:
        dialect_name = str(getattr(engine.dialect, "name", "") or "")
    except Exception:
        dialect_name = ""

    if dialect_name.startswith("postgres"):
        emb_literal = "[" + ",".join(str(float(v)) for v in embedding) + "]"
        sql = sa_text(
            """
            UPDATE projection_query_outcomes
               SET embedding = CAST(:emb AS vector)
             WHERE id = :rid
               AND company_id = :cid
            """
        )
        params: dict[str, Any] = {
            "rid": row_id,
            "cid": str(company_id),
            "emb": emb_literal,
        }
    else:
        # SQLite (and any other dialect — JSON is universally supported).
        sql = sa_text(
            """
            UPDATE projection_query_outcomes
               SET embedding = :emb
             WHERE id = :rid
               AND company_id = :cid
            """
        )
        params = {
            "rid": row_id,
            "cid": str(company_id),
            "emb": _json.dumps([float(v) for v in embedding]),
        }

    async with engine.begin() as conn:
        await conn.execute(sql, params)


# ---------------------------------------------------------------------------
# Core: orchestration
# ---------------------------------------------------------------------------


async def run_backfill(
    *,
    engine: Any,
    embedding_service: Any,
    company_id: UUID,
    days: int | None,
    max_count: int,
    dry_run: bool,
    now: datetime | None = None,
    target_dim: int | None = None,
) -> BackfillReport:
    """Backfill embeddings for one tenant, returning a report.

    Pure orchestration — both the CLI entrypoint and the test suite call
    this with a constructed ``engine`` (any AsyncEngine) and
    ``embedding_service`` (anything satisfying the
    :class:`wormbase_inference.EmbeddingService` Protocol, including
    test fakes).

    The script does NOT manage engine lifecycle; the caller is responsible
    for ``await engine.dispose()`` after the report comes back. This lets
    tests reuse one engine across multiple runs (idempotency checks).

    ``target_dim`` is the cross-model migration knob:

    * ``None`` (default — preserves pre-existing behavior): rows with
      ANY non-NULL embedding are skipped; only ``embedding IS NULL`` rows
      are re-embedded.
    * ``int`` (cross-model mode): rows whose persisted embedding dim
      differs from ``target_dim`` are re-embedded (in addition to the
      ``embedding IS NULL`` rows). Rows already at the target dim are
      counted as ``skipped_already_embedded``. The
      :attr:`BackfillReport.re_embedded_cross_model` counter tracks the
      cross-model subset of :attr:`BackfillReport.processed`.
    """
    import time as _time

    if now is None:
        now = datetime.now(timezone.utc)

    report = BackfillReport(dry_run=dry_run)
    started = _time.monotonic()

    candidates = await _find_candidate_rows(
        engine,
        company_id=company_id,
        days=days,
        max_count=max_count,
        now=now,
    )
    report.found = len(candidates)
    logger.info(
        "embedding-backfill: company_id=%s scope=%s candidates=%d dry_run=%s target_dim=%s",
        company_id,
        f"last {days}d" if days is not None else "all",
        report.found,
        dry_run,
        target_dim if target_dim is not None else "<unset>",
    )

    for row in candidates:
        row_id = str(row.get("id"))
        nl_question = row.get("nl_question") or ""

        existing_dim = _row_embedding_dim(row)
        if existing_dim > 0:
            if target_dim is None:
                # Default behavior: any embedding skips re-embed.
                report.skipped_already_embedded += 1
                continue
            if existing_dim == target_dim:
                # Cross-model mode: same dim → already migrated.
                report.skipped_already_embedded += 1
                continue
            # Cross-model mode + dim mismatch → fall through to re-embed.
            cross_model_reembed = True
        else:
            cross_model_reembed = False

        if not nl_question.strip():
            # Empty NL question — the EmbeddingService would raise on
            # this. Treat as a soft failure so the report surfaces it
            # but the run continues.
            report.failed += 1
            if len(report.failures) < 50:
                report.failures.append((row_id, "empty nl_question"))
            logger.warning(
                "embedding-backfill: row_id=%s has empty nl_question; skipping",
                row_id,
            )
            continue

        try:
            result = await embedding_service.embed(nl_question)
        except Exception as exc:  # noqa: BLE001
            report.failed += 1
            if len(report.failures) < 50:
                report.failures.append((row_id, str(exc)))
            logger.warning(
                "embedding-backfill: embed() failed for row_id=%s: %s",
                row_id,
                exc,
            )
            continue

        # The EmbeddingResult.vector is a tuple[float, ...]; coerce to
        # a list for the UPDATE binders. None / empty vectors are
        # rejected by the service before this point (EmbeddingError),
        # but guard defensively.
        vec = getattr(result, "vector", None)
        if not vec:
            report.failed += 1
            if len(report.failures) < 50:
                report.failures.append((row_id, "embed() returned empty vector"))
            continue

        if not dry_run:
            try:
                await _update_embedding(
                    engine,
                    row_id=row_id,
                    company_id=company_id,
                    embedding=vec,
                )
            except Exception as exc:  # noqa: BLE001
                report.failed += 1
                if len(report.failures) < 50:
                    report.failures.append((row_id, f"UPDATE failed: {exc}"))
                logger.warning(
                    "embedding-backfill: UPDATE failed for row_id=%s: %s",
                    row_id,
                    exc,
                )
                continue

        report.processed += 1
        if cross_model_reembed:
            report.re_embedded_cross_model += 1

    report.duration_s = _time.monotonic() - started
    return report


# ---------------------------------------------------------------------------
# Cross-model migration: projection-column dim pre-flight
# ---------------------------------------------------------------------------


class ProjectionColumnDimMismatchError(RuntimeError):
    """Raised when the projection embedding column dim doesn't match the
    operator-supplied ``--target-dim``.

    Cross-model migration requires the v020 dim-flexible migration to
    have ALTERed the column to the target dim BEFORE the backfill runs.
    Without that ordering, the UPDATE either fails (Postgres rejects the
    dim-mismatched vector cast) or silently rounds — neither is
    acceptable. The pre-flight returns operator-actionable text pointing
    at the v020 runbook.
    """


async def check_projection_column_dim(
    engine: Any,
    *,
    target_dim: int,
) -> None:
    """Validate ``projection_query_outcomes.embedding`` matches ``target_dim``.

    Postgres-only (SQLite stores embeddings as JSON, so dim is implicit
    in the array length and the check is a no-op). On Postgres, the
    function reads ``pg_attribute.atttypmod`` (pgvector encodes
    ``vector(N)`` as ``atttypmod = N``) and raises
    :class:`ProjectionColumnDimMismatchError` if the column dim differs
    from ``target_dim``.

    The error text matches the runbook in
    ``docs/superpowers/notes/2026-05-24-cross-model-embedding-migration.md`` —
    "run v020 migration with WORMBASE_EMBEDDING_DIM=... set first".
    """
    dialect_name = ""
    try:
        dialect_name = str(getattr(engine.dialect, "name", "") or "")
    except Exception:
        dialect_name = ""

    if not dialect_name.startswith("postgres"):
        # SQLite (and other dialects) — JSON columns; dim is implicit.
        return

    sql = sa_text(
        """
        SELECT a.atttypmod
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
         WHERE c.relname = 'projection_query_outcomes'
           AND a.attname = 'embedding'
           AND NOT a.attisdropped
        """
    )

    async with engine.connect() as conn:
        result = await conn.execute(sql)
        atttypmod = result.scalar()

    if atttypmod is None:
        # Column missing — v018/v020 never ran on this database. Surface
        # as a mismatch so the operator knows to apply migrations first.
        raise ProjectionColumnDimMismatchError(
            "projection_query_outcomes.embedding column not found. "
            "Run the v016 → v020 migration chain first; see "
            "docs/superpowers/notes/2026-05-24-cross-model-embedding-migration.md."
        )

    if int(atttypmod) != int(target_dim):
        raise ProjectionColumnDimMismatchError(
            f"projection_query_outcomes.embedding is Vector({int(atttypmod)}); "
            f"expected Vector({int(target_dim)}). "
            f"Run v020 migration with `WORMBASE_EMBEDDING_DIM={int(target_dim)}` "
            f"set first. See "
            f"docs/superpowers/notes/2026-05-24-cross-model-embedding-migration.md."
        )


# ---------------------------------------------------------------------------
# Multi-tenant: discover active tenants from the projection table
# ---------------------------------------------------------------------------


async def discover_active_tenants(engine: Any) -> list[UUID]:
    """Return distinct ``company_id`` values from ``projection_query_outcomes``.

    Source of truth for "is this tenant active for embedding purposes" is
    the projection table the gather path reads from — if a tenant has no
    rows there, there is nothing to backfill, so we exclude it. The list
    is capped at :data:`_MAX_TENANTS_PER_RUN` (1000); operators who hit
    the cap should split into batches with explicit ``--company-id``.

    Returns a list of :class:`UUID` values, sorted by their string form so
    the iteration order is deterministic across runs.
    """
    sql = sa_text(
        f"""
        SELECT DISTINCT company_id
          FROM projection_query_outcomes
         ORDER BY company_id ASC
         LIMIT {int(_MAX_TENANTS_PER_RUN) + 1}
        """
    )

    out: list[UUID] = []
    async with engine.connect() as conn:
        result = await conn.execute(sql)
        for row in result:
            raw = row[0]
            if raw is None:
                continue
            try:
                out.append(raw if isinstance(raw, UUID) else UUID(str(raw)))
            except (TypeError, ValueError):
                logger.warning(
                    "embedding-backfill: skipping unparseable company_id=%r",
                    raw,
                )
                continue

    if len(out) > _MAX_TENANTS_PER_RUN:
        logger.warning(
            "embedding-backfill: tenant discovery exceeded cap "
            "(found=%d cap=%d); truncating. Re-run with explicit "
            "--company-id values for tenants beyond the cap.",
            len(out),
            _MAX_TENANTS_PER_RUN,
        )
        out = out[:_MAX_TENANTS_PER_RUN]

    return out


# ---------------------------------------------------------------------------
# Multi-tenant: aggregate report
# ---------------------------------------------------------------------------


@dataclass
class AggregateBackfillReport:
    """Roll-up of per-tenant :class:`BackfillReport`s from an
    ``--all-tenants`` run.

    Per-tenant catastrophic failures (engine error, discovery wedge, etc.)
    are captured in :attr:`tenant_failures` so the CLI can render them and
    so the exit code can reflect "every tenant failed" vs "some succeeded".
    Per-row ``failed`` counts inside a tenant's report are aggregated into
    :attr:`total_failed` for the footer but do not count as a "tenant
    failure" — a tenant whose backfill ran but recorded N row failures is
    a successful tenant run with N row errors.
    """

    tenants_discovered: int = 0
    tenants_succeeded: int = 0
    tenant_reports: list[tuple[UUID, BackfillReport]] = field(default_factory=list)
    tenant_failures: list[tuple[UUID, str]] = field(default_factory=list)
    total_duration_s: float = 0.0

    @property
    def total_processed(self) -> int:
        return sum(r.processed for _cid, r in self.tenant_reports)

    @property
    def total_found(self) -> int:
        return sum(r.found for _cid, r in self.tenant_reports)

    @property
    def total_skipped(self) -> int:
        return sum(r.skipped_already_embedded for _cid, r in self.tenant_reports)

    @property
    def total_failed(self) -> int:
        return sum(r.failed for _cid, r in self.tenant_reports)

    @property
    def total_re_embedded_cross_model(self) -> int:
        return sum(
            r.re_embedded_cross_model for _cid, r in self.tenant_reports
        )


async def run_backfill_all_tenants(
    *,
    engine: Any,
    embedding_service: Any,
    days: int | None,
    max_count: int,
    dry_run: bool,
    now: datetime | None = None,
    on_tenant_report: Any = None,
    target_dim: int | None = None,
) -> AggregateBackfillReport:
    """Discover active tenants and run :func:`run_backfill` per tenant.

    Per-tenant failure isolation: if one tenant's ``run_backfill`` raises
    (engine error, SQL hiccup, EmbeddingService unrecoverable), the
    exception is logged + recorded in :attr:`tenant_failures` and the
    loop continues with the next tenant. Row-level ``embed()`` failures
    are already caught inside :func:`run_backfill` and surface via
    :attr:`BackfillReport.failed`, NOT as a tenant-level failure.

    The optional ``on_tenant_report`` callback (sync or async) is invoked
    after every per-tenant completion with ``(company_id, report)``. The
    CLI uses it to stream the per-tenant header + summary to stdout
    incrementally, which matters for long fleet runs where holding the
    aggregate to the end would mean silent multi-minute pauses.
    """
    import inspect as _inspect
    import time as _time

    if now is None:
        now = datetime.now(timezone.utc)

    started = _time.monotonic()
    aggregate = AggregateBackfillReport()

    company_ids = await discover_active_tenants(engine)
    aggregate.tenants_discovered = len(company_ids)
    logger.info(
        "embedding-backfill: --all-tenants discovered %d tenants (cap=%d)",
        len(company_ids),
        _MAX_TENANTS_PER_RUN,
    )

    for cid in company_ids:
        try:
            report = await run_backfill(
                engine=engine,
                embedding_service=embedding_service,
                company_id=cid,
                days=days,
                max_count=max_count,
                dry_run=dry_run,
                now=now,
                target_dim=target_dim,
            )
        except Exception as exc:  # noqa: BLE001
            aggregate.tenant_failures.append((cid, str(exc)))
            logger.warning(
                "embedding-backfill: tenant=%s failed catastrophically: %s",
                cid,
                exc,
            )
            if on_tenant_report is not None:
                try:
                    out = on_tenant_report(cid, None)
                    if _inspect.isawaitable(out):
                        await out
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "embedding-backfill: on_tenant_report callback raised "
                        "for tenant=%s (continuing)",
                        cid,
                    )
            continue

        aggregate.tenant_reports.append((cid, report))
        aggregate.tenants_succeeded += 1
        if on_tenant_report is not None:
            try:
                out = on_tenant_report(cid, report)
                if _inspect.isawaitable(out):
                    await out
            except Exception:  # noqa: BLE001
                logger.warning(
                    "embedding-backfill: on_tenant_report callback raised "
                    "for tenant=%s (continuing)",
                    cid,
                )

    aggregate.total_duration_s = _time.monotonic() - started
    return aggregate


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


@click.command(name="wormbase-embedding-backfill")
@click.option(
    "--company-id",
    type=click.UUID,
    default=None,
    help=(
        "Tenant UUID to backfill. Mutually exclusive with --all-tenants; "
        "exactly one of the two must be supplied."
    ),
)
@click.option(
    "--all-tenants",
    "all_tenants",
    is_flag=True,
    default=False,
    help=(
        "Discover active tenants from projection_query_outcomes and "
        "backfill each in sequence. Per-tenant failures are logged and "
        "the loop continues; exit code is 0 if any tenant succeeded, "
        "1 only if every tenant failed catastrophically. Capped at "
        "1000 distinct tenants per run."
    ),
)
@click.option(
    "--days",
    type=int,
    default=None,
    help="Restrict to rows recorded in the last N days. Default: all history.",
)
@click.option(
    "--max-count",
    type=int,
    default=1000,
    show_default=True,
    help="Cap rows processed in one run.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Compute embeddings but skip DB writes.",
)
@click.option(
    "--dsn",
    envvar="WORMBASE_LEDGER_DSN",
    default=_DEFAULT_DSN,
    show_default=True,
    help="SQLAlchemy URL for the projection store.",
)
@click.option(
    "--ollama-key",
    envvar="OLLAMA_API_KEY",
    default=None,
    help="Ollama Cloud bearer token. Reads OLLAMA_API_KEY env when omitted.",
)
@click.option(
    "--target-model",
    type=str,
    default=None,
    help=(
        "Cross-model migration: re-embed rows whose persisted embedding "
        "dim does not match --target-dim, using this model (overrides "
        "WORMBASE_EMBEDDING_MODEL). Must be one of the supported models "
        "(nomic-embed-text, mxbai-embed-large). Requires --target-dim. "
        "When unset, the CLI only re-embeds rows with NULL embeddings "
        "(default behavior preserved byte-identical)."
    ),
)
@click.option(
    "--target-dim",
    type=int,
    default=None,
    help=(
        "Cross-model migration: the expected output dim of --target-model. "
        "Must match the model's native dim (768 for nomic-embed-text, "
        "1024 for mxbai-embed-large). The CLI pre-flights the projection "
        "column dim against this value and aborts with a runbook pointer "
        "if they disagree. Required when --target-model is set."
    ),
)
def main(
    company_id: UUID | None,
    all_tenants: bool,
    days: int | None,
    max_count: int,
    dry_run: bool,
    dsn: str,
    ollama_key: str | None,
    target_model: str | None,
    target_dim: int | None,
) -> None:
    """Backfill embeddings on pre-Phase-3b query_outcome_recorded entries.

    Writes go directly to ``projection_query_outcomes.embedding`` (Option
    A — projection-only). The ledger is not mutated; downstream gather
    behavior is driven by the projection table.

    Exactly one of ``--company-id`` and ``--all-tenants`` must be supplied.
    In ``--all-tenants`` mode the script discovers the tenant list from
    ``projection_query_outcomes`` and loops; per-tenant failures are
    isolated and do not halt the run.
    """
    # Mutual-exclusion gate — argparse would handle this declaratively but
    # click leaves the policy to us. Run BEFORE any logging.basicConfig
    # call so the error surfaces cleanly to the operator.
    if all_tenants and company_id is not None:
        raise click.UsageError(
            "--all-tenants and --company-id are mutually exclusive; "
            "supply exactly one."
        )
    if not all_tenants and company_id is None:
        raise click.UsageError(
            "either --company-id or --all-tenants is required."
        )

    # Cross-model migration gates. Both flags travel together; either
    # both are set or neither. Validation matches OllamaCloudEmbeddingService's
    # constructor-time policy (model in SUPPORTED_EMBEDDING_MODELS,
    # native dim == target_dim) so the surface is consistent whether
    # the misconfiguration is caught at parse time (here) or at service
    # construction (env-vars-only path).
    if (target_model is None) != (target_dim is None):
        raise click.UsageError(
            "--target-model and --target-dim must be supplied together "
            "(or neither). When both are set, the CLI re-embeds rows "
            "whose persisted embedding dim does not match --target-dim."
        )

    if target_model is not None:
        # Lazy-import to keep --help cheap; SUPPORTED_EMBEDDING_MODELS
        # is small and stable, safe to import even on parse.
        from wormbase_inference.embedding import SUPPORTED_EMBEDDING_MODELS

        if target_model not in SUPPORTED_EMBEDDING_MODELS:
            supported = ", ".join(sorted(SUPPORTED_EMBEDDING_MODELS))
            raise click.UsageError(
                f"--target-model={target_model!r} is not supported; "
                f"supported models: [{supported}]."
            )
        native_dim = SUPPORTED_EMBEDDING_MODELS[target_model]
        if int(target_dim) != native_dim:  # type: ignore[arg-type]
            raise click.UsageError(
                f"--target-model={target_model!r} produces {native_dim}-dim "
                f"vectors; got --target-dim={target_dim}. Either set "
                f"--target-dim={native_dim} or pick a model whose native "
                f"dim matches."
            )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Lazy imports — keep ``--help`` cheap and avoid pulling in the
    # ledger / inference-router unless we're actually running.
    from wormbase_inference.embedding import OllamaCloudEmbeddingService
    from wormbase_ledger import Ledger

    def _print_tenant_report(cid: UUID, report: BackfillReport | None) -> None:
        """Render a per-tenant block to stdout. ``report=None`` means
        the tenant failed catastrophically (see tenant_failures)."""
        click.echo(f"\n=== Tenant {cid} ===")
        if report is None:
            click.echo("(catastrophic failure — see tenant_failures footer)")
            return
        scope_desc = f"last {days} days" if days is not None else "all history"
        click.echo(
            f"Backfilling embeddings ({scope_desc}, max {max_count} entries)"
        )
        click.echo(f"Found {report.found} rows in scope")
        click.echo(
            f"Processed: {report.processed}  "
            f"Skipped: {report.skipped_already_embedded}  "
            f"Failed: {report.failed}  "
            f"Duration: {report.duration_s:.1f}s"
        )

    async def _run() -> int:
        ledger = Ledger(dsn)
        engine = ledger.engine

        # When --target-model is set, override the env-driven model/dim
        # at the service constructor; OllamaCloudEmbeddingService's
        # __post_init__ wires constructor kwargs ahead of env-vars.
        if target_model is not None and target_dim is not None:
            embedding_service = OllamaCloudEmbeddingService(
                api_key=ollama_key,
                model=target_model,
                dim=int(target_dim),
            )
        else:
            embedding_service = OllamaCloudEmbeddingService(api_key=ollama_key)
        scope_desc = f"last {days} days" if days is not None else "all history"

        # Pre-flight: when target_dim is set, refuse to backfill if the
        # projection column dim doesn't match (Postgres only — SQLite
        # JSON columns are dim-implicit). The error text points at the
        # v020 runbook so the operator can fix forward without re-reading
        # source.
        if target_dim is not None:
            try:
                await check_projection_column_dim(
                    engine, target_dim=int(target_dim)
                )
            except ProjectionColumnDimMismatchError as exc:
                await embedding_service.aclose()
                await ledger.dispose()
                click.echo(f"ERROR: {exc}", err=True)
                return 2

        if all_tenants:
            click.echo("Backfilling embeddings across all tenants")
            click.echo(f"Scope: {scope_desc}, max {max_count} entries per tenant")
            if dry_run:
                click.echo("Mode: DRY RUN (no DB writes)")
            if target_model is not None:
                click.echo(
                    f"Mode: CROSS-MODEL MIGRATION "
                    f"(target_model={target_model}, target_dim={target_dim})"
                )

            try:
                aggregate = await run_backfill_all_tenants(
                    engine=engine,
                    embedding_service=embedding_service,
                    days=days,
                    max_count=max_count,
                    dry_run=dry_run,
                    on_tenant_report=_print_tenant_report,
                    target_dim=int(target_dim) if target_dim is not None else None,
                )
            finally:
                await embedding_service.aclose()
                await ledger.dispose()

            click.echo("\n=== Aggregate ===")
            click.echo(
                f"Tenants discovered: {aggregate.tenants_discovered}"
            )
            click.echo(
                f"Tenants succeeded: {aggregate.tenants_succeeded}"
            )
            click.echo(
                f"Tenants failed (catastrophic): {len(aggregate.tenant_failures)}"
            )
            click.echo(f"Total found: {aggregate.total_found}")
            click.echo(f"Total processed: {aggregate.total_processed}")
            if target_model is not None:
                click.echo(
                    f"Total re-embedded (cross-model): "
                    f"{aggregate.total_re_embedded_cross_model}"
                )
            click.echo(f"Total skipped: {aggregate.total_skipped}")
            click.echo(f"Total failed (row-level): {aggregate.total_failed}")
            click.echo(
                f"Total duration: {aggregate.total_duration_s:.1f}s"
            )
            click.echo("Cost: ~$0 (Ollama Cloud nomic-embed-text is free)")
            if aggregate.tenant_failures:
                click.echo("\nCatastrophic tenant failures:")
                for cid, err in aggregate.tenant_failures:
                    click.echo(f"  {cid}  {err}")
            done_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            click.echo(f"\nDone. Run completed at {done_ts}.")

            # Exit code: 0 if at least one tenant succeeded OR no tenants
            # were discovered (vacuous truth — there is nothing to fail
            # on). 1 only when every discovered tenant failed
            # catastrophically.
            if aggregate.tenants_discovered == 0:
                return 0
            if aggregate.tenants_succeeded == 0:
                return 1
            return 0

        # Single-tenant path — preserves the pre-existing CLI shape.
        assert company_id is not None  # narrowed by the gate above
        click.echo(f"Backfilling embeddings for company {company_id}")
        click.echo(f"Scope: {scope_desc}, max {max_count} entries")
        if dry_run:
            click.echo("Mode: DRY RUN (no DB writes)")
        if target_model is not None:
            click.echo(
                f"Mode: CROSS-MODEL MIGRATION "
                f"(target_model={target_model}, target_dim={target_dim})"
            )

        try:
            report = await run_backfill(
                engine=engine,
                embedding_service=embedding_service,
                company_id=company_id,
                days=days,
                max_count=max_count,
                dry_run=dry_run,
                target_dim=int(target_dim) if target_dim is not None else None,
            )
        finally:
            await embedding_service.aclose()
            await ledger.dispose()

        click.echo(f"Found {report.found} rows in scope")
        click.echo(f"Processed: {report.processed}")
        if target_model is not None:
            click.echo(
                f"Re-embedded (cross-model): {report.re_embedded_cross_model}"
            )
        click.echo(f"Skipped (already embedded): {report.skipped_already_embedded}")
        click.echo(f"Failed (logged): {report.failed}")
        click.echo(f"Duration: {report.duration_s:.1f}s")
        click.echo("Cost: ~$0 (Ollama Cloud nomic-embed-text is free)")
        if report.failures:
            click.echo("\nFailures (first 50):")
            for row_id, err in report.failures[:50]:
                click.echo(f"  {row_id}  {err}")
        done_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        click.echo(f"\nDone. Run completed at {done_ts}.")

        # Exit code: 0 always (failures are reported, not exception-raising).
        # An operator who wants strict failure detection can pipe through
        # ``grep "Failed: 0"``; non-zero exit codes are reserved for
        # catastrophic startup issues (DSN unreachable, etc.) which the
        # raised exception path already produces.
        return 0

    rc = asyncio.run(_run())
    sys.exit(rc)


__all__ = [
    "AggregateBackfillReport",
    "BackfillReport",
    "ProjectionColumnDimMismatchError",
    "check_projection_column_dim",
    "discover_active_tenants",
    "main",
    "run_backfill",
    "run_backfill_all_tenants",
]
