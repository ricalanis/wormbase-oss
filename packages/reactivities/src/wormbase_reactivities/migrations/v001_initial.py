"""v001 — initial reactivities schema.

Three tables back the registry:

* ``reactivity_state`` — one row per registered reactivity. Tracks the
  proposed/active/disabled lifecycle, audit fields, and the last fire
  timestamp. Source-of-truth on a worm-core restart.

* ``reactivity_budget`` — rolling-day counters keyed on (reactivity_id,
  axis, key, day). ``axis`` ∈ {owner, domain, tenant}. The
  ``DailyBudget`` condition reads these; the registry's ``_on_fire``
  hook increments them.

* ``reactivity_fires`` — fire log keyed on (reactivity_id, source_seq).
  Carries the novelty_key + fired_at so ``NotRecentlyFired`` can answer
  "did this (reactivity, key) fire within H hours". /trace queries this
  table to render reactivity provenance against ledger entries.

Idempotent: ``metadata.create_all`` only creates tables that don't
exist. Backend-portable across Postgres + SQLite via SQLAlchemy generic
types.

Versioning: numbered 1001 to leave room for ledger's projection
migrations (v001/v002 currently). The migrator runs everything in
version order, so 1001 lands AFTER all ledger migrations regardless of
list order.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)

# Local metadata; mirrors the ledger migration pattern. Never imported
# from a "live" schema module — this file IS the v001 surface.
_metadata = MetaData()


# reactivity_state — one row per registered reactivity.
Table(
    "reactivity_state",
    _metadata,
    Column("reactivity_id", String(64), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("description", String, nullable=False),
    Column("scope", String(16), nullable=False),
    Column("state", String(16), nullable=False),
    Column("proposed_by", String(64), nullable=True),
    Column("confirmed_by", Uuid(as_uuid=True), nullable=True),
    Column("disabled_by", Uuid(as_uuid=True), nullable=True),
    Column("disable_reason", String, nullable=True),
    Column("last_fired_at", DateTime(timezone=True), nullable=True),
    Column("last_updated_seq", BigInteger, nullable=True),
)


# reactivity_budget — rolling-day counters per (reactivity, axis, key, day).
# ``day`` is an ISO date string ("2026-04-28") — string-typed for backend
# portability. Composite primary key prevents duplicate rows; the registry's
# increment path uses INSERT ... ON CONFLICT semantics in the DB-backed mode.
Table(
    "reactivity_budget",
    _metadata,
    Column("reactivity_id", String(64), primary_key=True),
    Column("axis", String(16), primary_key=True),
    Column("key", String(255), primary_key=True),
    Column("day", String(10), primary_key=True),
    Column("count", Integer, nullable=False, default=0),
    Index("ix_reactivity_budget_reactivity_day", "reactivity_id", "day"),
)


# reactivity_fires — fire log. ``source_seq`` is the ledger seq of the
# entry that triggered the fire; combined with reactivity_id it's unique.
# ``novelty_key`` may be empty (some reactivities don't use novelty); the
# index includes it so NotRecentlyFired lookups are fast.
Table(
    "reactivity_fires",
    _metadata,
    Column("reactivity_id", String(64), primary_key=True),
    Column("source_seq", BigInteger, primary_key=True),
    Column("novelty_key", String(255), nullable=False, default=""),
    Column("fired_at", DateTime(timezone=True), nullable=False),
    Column("action_seqs", String, nullable=False, default=""),  # JSON-encoded list
    Index(
        "ix_reactivity_fires_lookup",
        "reactivity_id",
        "novelty_key",
        "fired_at",
    ),
    UniqueConstraint(
        "reactivity_id",
        "source_seq",
        name="uq_reactivity_fires_reactivity_source",
    ),
)


class Migration:
    """Reactivities v001 — create the three reactivity_* tables.

    Idempotent via ``metadata.create_all``. Version 1001 to leave room
    for ledger's projection migrations (v001/v002 today).
    """

    version: int = 1001
    description: str = "initial reactivities schema (state + budget + fires)"

    async def up(self, conn) -> None:  # type: ignore[no-untyped-def]
        await conn.run_sync(_metadata.create_all)
