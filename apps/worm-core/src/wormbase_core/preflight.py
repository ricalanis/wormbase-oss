"""Boot-time pre-flight checks for worm-core.

Item #8 of the 2026-05-12 final wave: assert pgvector >=0.6 at boot when
the projection-promoted gather (Phase 3c) or write-time embedding wire
(Phase 3b) is enabled on a Postgres deployment.

Today, the v019 HNSW migration relies on pgvector >=0.6 for the
``vector_cosine_ops`` operator class. If pgvector is missing or too old,
the migration crashes at apply-time with a fairly opaque ``UndefinedObject``
error from asyncpg. This module surfaces the failure earlier (during CLI
boot, before the projection runner / reactivity runner / MCP server fire)
with a clear actionable hint.

Design notes:

* SQLite ledger engines short-circuit to ``OK`` — pgvector is not
  applicable and the projection schema stores embeddings as JSON columns.
* The check is gated on env knobs first, so a Postgres install with
  ``WORMBASE_GATHER_VIA_PROJECTION`` and ``WORMBASE_EMBEDDING_ENABLED``
  both off pays no cost and never hits the DB.
* Errors surface with documented exit codes (see :data:`EXIT_*`
  constants) so operators have stable signals for monitoring.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# Exit codes — stable signals an init system or monitor can pick up.
EXIT_PGVECTOR_MISSING = 21
EXIT_PGVECTOR_TOO_OLD = 22
EXIT_PGVECTOR_QUERY_FAILED = 23


# Minimum pgvector version required for HNSW + ``vector_cosine_ops``.
# pgvector landed HNSW in 0.5.0; ``vector_cosine_ops`` is stable since
# 0.6.0, which is what the v019 migration expects.
MIN_PGVECTOR_MAJOR = 0
MIN_PGVECTOR_MINOR = 6


# Truthy env values (mirrors ``agent_gateway_construction`` conventions).
_TRUTHY = frozenset({"1", "true", "yes"})


def _truthy_env(key: str) -> bool:
    return os.environ.get(key, "0").strip().lower() in _TRUTHY


def _ledger_dialect_name(ledger: Any) -> str | None:
    """Return the SQLAlchemy dialect name for a ledger, or None.

    InMemoryLedger and any ledger that lacks an ``engine.dialect`` shape
    returns ``None`` — the pre-flight short-circuits to OK in that case.
    """
    engine = getattr(ledger, "engine", None)
    if engine is None:
        return None
    dialect = getattr(engine, "dialect", None)
    if dialect is None:
        return None
    name = getattr(dialect, "name", None)
    if isinstance(name, str) and name:
        return name
    return None


def is_pgvector_required(ledger: Any) -> bool:
    """Return True iff a Postgres-backed deploy needs pgvector at boot.

    Required iff the ledger's dialect is ``postgresql`` AND any of the
    Phase 3 wires that depend on pgvector are enabled:

    * ``WORMBASE_GATHER_VIA_PROJECTION=true`` — Phase 3c projection gather
      (uses the pgvector ``<=>`` cosine operator on
      ``projection_query_outcomes``).
    * ``WORMBASE_EMBEDDING_ENABLED=true`` — Phase 3b write-time embedding
      wire (writes ``Vector(768)`` rows into ``projection_query_outcomes``
      / ``projection_query_templates``).

    SQLite ledgers return False unconditionally — the projection schema
    on SQLite falls back to JSON columns and never references pgvector.
    """
    dialect = _ledger_dialect_name(ledger)
    if dialect != "postgresql":
        return False
    if _truthy_env("WORMBASE_GATHER_VIA_PROJECTION"):
        return True
    if _truthy_env("WORMBASE_EMBEDDING_ENABLED"):
        return True
    return False


# ---------------------------------------------------------------------------
# Version parsing
# ---------------------------------------------------------------------------


_VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass(frozen=True)
class PgVectorVersion:
    """Parsed pgvector extension version.

    Captures the major / minor / patch components and the raw string the
    DB returned. ``compare`` uses the (major, minor, patch) tuple — any
    pre-release / build suffix (``-dev``, ``+release``, ``rc1``) is
    discarded after the leading numeric segment.
    """

    raw: str
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw: str) -> PgVectorVersion:
        match = _VERSION_RE.match(raw)
        if match is None:
            raise ValueError(
                f"unrecognised pgvector version string: {raw!r}",
            )
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3)) if match.group(3) else 0
        return cls(raw=raw, major=major, minor=minor, patch=patch)

    def satisfies_minimum(
        self,
        *,
        major: int = MIN_PGVECTOR_MAJOR,
        minor: int = MIN_PGVECTOR_MINOR,
    ) -> bool:
        if self.major > major:
            return True
        if self.major < major:
            return False
        return self.minor >= minor


# ---------------------------------------------------------------------------
# Pre-flight errors + check
# ---------------------------------------------------------------------------


class PgVectorPreflightError(RuntimeError):
    """Raised when the pgvector pre-flight fails.

    ``exit_code`` is one of the EXIT_PGVECTOR_* constants in this module.
    The CLI translates the exception into a non-zero process exit so init
    systems / monitors see a stable failure signal.
    """

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


async def _query_pgvector_version(ledger: Any) -> str | None:
    """Run ``SELECT extversion FROM pg_extension WHERE extname='vector'``.

    Returns the version string when pgvector is installed, ``None`` when
    the extension is missing. Surfacing connection / permission errors
    is the caller's job — this helper only catches the "no row" case.
    """
    # Local imports — keep the import surface light when pre-flight is
    # a no-op (SQLite tests, embedding-off Postgres deploys).
    from sqlalchemy import text as sa_text

    engine = ledger.engine
    async with engine.connect() as conn:
        result = await conn.execute(
            sa_text(
                "SELECT extversion FROM pg_extension "
                "WHERE extname = 'vector'",
            ),
        )
        row = result.first()
        if row is None:
            return None
        return str(row[0])


async def check_pgvector(ledger: Any) -> PgVectorVersion | None:
    """Run the pgvector boot-time pre-flight.

    Returns:

    * ``None`` when the pre-flight is not required (SQLite ledger, or
      Postgres ledger with neither Phase 3b nor Phase 3c enabled).
    * A :class:`PgVectorVersion` when pgvector is installed and meets
      the minimum.

    Raises:

    * :class:`PgVectorPreflightError` when pgvector is required but
      missing, too old, or the version query fails. The exception
      carries an ``exit_code`` for the CLI to translate.
    """
    if not is_pgvector_required(ledger):
        logger.debug(
            "pgvector pre-flight skipped: dialect=%s env knobs off",
            _ledger_dialect_name(ledger),
        )
        return None

    try:
        raw_version = await _query_pgvector_version(ledger)
    except Exception as exc:  # noqa: BLE001
        # Surface the underlying error — don't swallow into a misleading
        # "pgvector missing" message. Most operators want the asyncpg /
        # connection error verbatim so they can diagnose.
        raise PgVectorPreflightError(
            "pgvector pre-flight failed: could not query pg_extension "
            f"({exc.__class__.__name__}: {exc}). "
            "Verify the database is reachable and the connecting role "
            "has SELECT on pg_extension. To bypass the pre-flight in a "
            "dev environment, unset WORMBASE_GATHER_VIA_PROJECTION and "
            "WORMBASE_EMBEDDING_ENABLED.",
            exit_code=EXIT_PGVECTOR_QUERY_FAILED,
        ) from exc

    if raw_version is None:
        raise PgVectorPreflightError(
            "pgvector extension missing on the configured Postgres "
            "database. The projection-promoted gather (Phase 3c) and "
            "write-time embedding wire (Phase 3b) both require "
            f"pgvector >= {MIN_PGVECTOR_MAJOR}.{MIN_PGVECTOR_MINOR}. "
            "Install with `CREATE EXTENSION vector` (Postgres superuser "
            "or the role with CREATE privilege on the target database) "
            "and restart, or set WORMBASE_GATHER_VIA_PROJECTION=false / "
            "WORMBASE_EMBEDDING_ENABLED=false to bypass.",
            exit_code=EXIT_PGVECTOR_MISSING,
        )

    try:
        parsed = PgVectorVersion.parse(raw_version)
    except ValueError as exc:
        # Unparseable version strings are an operator-facing problem —
        # surface verbatim. We don't try to "best-guess" past a malformed
        # release because that hides upstream packaging mistakes.
        raise PgVectorPreflightError(
            f"pgvector pre-flight failed: {exc}. "
            "If this is a custom build, ensure the version string "
            "follows semver (e.g. '0.6.0', '0.6.0-dev', '0.7.4+release').",
            exit_code=EXIT_PGVECTOR_QUERY_FAILED,
        ) from exc

    if not parsed.satisfies_minimum():
        raise PgVectorPreflightError(
            f"pgvector {parsed.raw} detected; "
            f">= {MIN_PGVECTOR_MAJOR}.{MIN_PGVECTOR_MINOR} required for "
            "HNSW + vector_cosine_ops support (v019 migration). "
            "Run `ALTER EXTENSION vector UPDATE` (Postgres superuser or "
            "the role with CREATE privilege on the target database) and "
            "restart, or set WORMBASE_GATHER_VIA_PROJECTION=false / "
            "WORMBASE_EMBEDDING_ENABLED=false to bypass.",
            exit_code=EXIT_PGVECTOR_TOO_OLD,
        )

    logger.info(
        "pgvector pre-flight OK: version=%s "
        "(WORMBASE_GATHER_VIA_PROJECTION=%s, "
        "WORMBASE_EMBEDDING_ENABLED=%s)",
        parsed.raw,
        _truthy_env("WORMBASE_GATHER_VIA_PROJECTION"),
        _truthy_env("WORMBASE_EMBEDDING_ENABLED"),
    )
    return parsed


__all__ = [
    "EXIT_PGVECTOR_MISSING",
    "EXIT_PGVECTOR_QUERY_FAILED",
    "EXIT_PGVECTOR_TOO_OLD",
    "MIN_PGVECTOR_MAJOR",
    "MIN_PGVECTOR_MINOR",
    "PgVectorPreflightError",
    "PgVectorVersion",
    "check_pgvector",
    "is_pgvector_required",
]
