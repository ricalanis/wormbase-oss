"""Versioned migrations for the reactivities tables.

Same Protocol shape as ``wormbase_ledger.projections.migrations``: each
migration class exposes ``version: int``, ``description: str``, and
``async up(conn)``. The list ``MIGRATIONS`` is exported so worm-core's
boot sequence can merge it into the ledger migrator's invocation list.

Wiring at boot: see ``apps/worm-core/src/wormbase_core/cli.py`` —
``run_migrations(ledger, migrations=ledger_migrations + reactivities_migrations)``.
The migrator preserves order across the merged list as long as
versions don't collide; reactivities migrations sit in the ``2_xxx``
namespace (offset chosen below) to avoid clashing with ledger's v001/v002.

The reactivities namespace starts at 1001 to leave room for ledger to
grow into v003+ without us shifting. Migrators tolerate gaps.
"""

from __future__ import annotations

from wormbase_reactivities.migrations.v001_initial import (
    Migration as V001ReactivitiesMigration,
)

# The canonical reactivities migrations list. Append-only.
MIGRATIONS = [V001ReactivitiesMigration()]


__all__ = ["MIGRATIONS"]
