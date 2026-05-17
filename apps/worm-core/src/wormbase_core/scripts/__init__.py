"""Admin / one-shot CLI scripts that ship with worm-core.

These are operator-facing utilities, not runtime entrypoints. They live
alongside the long-running CLI (``wormbase-worm-core``) so they can
share the package's resolved dependency closure (ledger, inference-
router, projections) without spinning up a separate distribution.

Current scripts:

* :mod:`embedding_backfill` — backfills 768-dim nomic-embed-text vectors
  onto ``projection_query_outcomes`` rows recorded BEFORE the v2.B
  Phase 3b embedding wire was lit. Idempotent, multi-tenant-safe,
  ``--dry-run``-supporting. See module docstring for the design rationale
  on why this is a projection-only write (Option A, not a compensating
  ledger entry).
"""
