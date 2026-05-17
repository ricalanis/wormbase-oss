"""Parallel-replay validator for engine-per-tenant migrations.

Engine-per-tenant Phase 2 — paired with the
``tenant_engine_registered`` ledger kind. Replays the ledger entries
for a tenant from BOTH the shared engine AND the (proposed or
actually-migrated) isolated engine over a given time window, then
computes a diff so an operator can certify hash-chain equivalence
before completing a Shape A → Shape B migration.

Per the engine-per-tenant routing design spec at
``docs/superpowers/specs/2026-05-22-engine-per-tenant-routing-
design.md`` §8 (Rollout sequence), Phase 1+2 ships the validator
contract + reference implementation. Phase 3 will wire the validator
into the admin migration tool; Phase 4 will swap the static engine
registry for a ledger-fold over ``tenant_engine_registered`` entries.

The validator is intentionally read-only — it never writes back to
either engine. The diff returned by :func:`validate_parallel_replay`
is the input to the operator's go/no-go gate.

Replay determinism: the comparison is a fold over
:func:`wormbase_ledger.repo.fetch_entries` on each engine, restricted
to the same ``(company_id, window_start, window_end)`` envelope.
Empty windows are vacuously consistent (no rows on either side ⇒
``is_consistent=True``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from wormbase_ledger.db import session_scope
from wormbase_ledger.repo import fetch_entries


@dataclass(frozen=True)
class ParallelReplayDiff:
    """Result of a parallel-replay comparison across two engines.

    Field semantics:
      * ``tenant_slug`` — the tenant being compared. Carried for
        telemetry / log-line attribution.
      * ``window_start`` / ``window_end`` — the comparison envelope.
        Inclusive on both ends.
      * ``shared_entry_count`` — entries on the shared engine in
        ``[window_start, window_end]``.
      * ``isolated_entry_count`` — entries on the isolated engine.
      * ``shared_terminal_hash`` / ``isolated_terminal_hash`` — the
        ``hash`` of the LAST entry in the window on each side, or
        ``None`` if the engine has no entries in the window.
        ``terminal`` (not ``last``) is the spec-canonical name from
        the design doc §8.
      * ``kind_counts_shared`` / ``kind_counts_isolated`` — per-kind
        entry counts per side. Lets the operator spot kind-by-kind
        drift even if totals match.
      * ``is_consistent`` — True iff:
          - entry counts match exactly, AND
          - terminal hashes match exactly, AND
          - per-kind counts match exactly.
        Empty windows on BOTH sides are vacuously True. An empty
        window on only one side is inconsistent (one engine has
        unflushed entries).
      * ``inconsistency_reasons`` — human-readable diagnostic strings
        when ``is_consistent`` is False. Empty when consistent.

    The diff is the operator's go/no-go input — replay equivalence is
    the migration's safety gate per design spec §8.
    """

    tenant_slug: str
    window_start: datetime
    window_end: datetime
    shared_entry_count: int
    isolated_entry_count: int
    shared_terminal_hash: bytes | None
    isolated_terminal_hash: bytes | None
    kind_counts_shared: dict[str, int]
    kind_counts_isolated: dict[str, int]
    is_consistent: bool
    inconsistency_reasons: tuple[str, ...] = field(default_factory=tuple)


async def _fetch_window(
    engine: AsyncEngine,
    company_id: UUID,
    *,
    window_start: datetime,
    window_end: datetime,
) -> list[dict[str, Any]]:
    """Fetch ledger entries for ``company_id`` in the closed window."""
    async with session_scope(engine) as session:
        # fetch_entries returns rows ordered by seq.asc(), filtered to
        # ts <= window_end. We further filter by ts >= window_start
        # in Python to keep the call signature stable.
        rows = await fetch_entries(session, company_id, until_ts=window_end)
    return [r for r in rows if r["ts"] >= window_start]


def _summarize_rows(
    rows: list[dict[str, Any]],
) -> tuple[int, bytes | None, dict[str, int]]:
    """Reduce rows to (count, terminal_hash, kind_counts)."""
    count = len(rows)
    terminal_hash = rows[-1]["hash"] if rows else None
    kind_counts: dict[str, int] = {}
    for r in rows:
        kind = r["kind"]
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    return count, terminal_hash, kind_counts


async def validate_parallel_replay(
    tenant_slug: str,
    shared_engine: AsyncEngine,
    isolated_engine: AsyncEngine,
    *,
    company_id: UUID,
    window_start: datetime,
    window_end: datetime,
) -> ParallelReplayDiff:
    """Compare a tenant's ledger entries across two engines.

    Returns :class:`ParallelReplayDiff` with ``is_consistent=True``
    when entry counts + terminal hashes + per-kind counts agree
    across both engines for the closed window
    ``[window_start, window_end]``.

    Empty window on both sides ⇒ vacuously consistent (no work,
    no drift). Empty on one side only ⇒ inconsistent (one engine
    has rows the other lacks).

    The validator is read-only — it never writes to either engine.
    The Phase 3 admin tool wires this into the operator go/no-go
    gate before promoting an isolated engine to Shape B canonical.

    Window timestamps MUST be tz-aware (same invariant as
    ``LedgerEntry.ts``). When ``window_end < window_start``, the
    window is vacuously empty on both sides → consistent.
    """
    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError(
            "validate_parallel_replay: window_start and window_end "
            "must be tz-aware",
        )

    shared_rows = await _fetch_window(
        shared_engine,
        company_id,
        window_start=window_start,
        window_end=window_end,
    )
    isolated_rows = await _fetch_window(
        isolated_engine,
        company_id,
        window_start=window_start,
        window_end=window_end,
    )

    shared_count, shared_terminal, shared_kinds = _summarize_rows(shared_rows)
    isolated_count, isolated_terminal, isolated_kinds = _summarize_rows(
        isolated_rows,
    )

    reasons: list[str] = []
    if shared_count != isolated_count:
        reasons.append(
            f"entry count mismatch: shared={shared_count}, "
            f"isolated={isolated_count}",
        )
    if shared_terminal != isolated_terminal:
        # Format hashes as hex for human-readable diagnostics; bytes
        # comparisons are exact above so this is purely cosmetic.
        sh = shared_terminal.hex() if shared_terminal else "None"
        ih = isolated_terminal.hex() if isolated_terminal else "None"
        reasons.append(
            f"terminal hash mismatch: shared={sh}, isolated={ih}",
        )
    if shared_kinds != isolated_kinds:
        # Build a per-kind diff for diagnostics.
        all_kinds = set(shared_kinds) | set(isolated_kinds)
        for k in sorted(all_kinds):
            s = shared_kinds.get(k, 0)
            i = isolated_kinds.get(k, 0)
            if s != i:
                reasons.append(
                    f"kind {k!r} count mismatch: shared={s}, isolated={i}",
                )

    is_consistent = not reasons

    return ParallelReplayDiff(
        tenant_slug=tenant_slug,
        window_start=window_start,
        window_end=window_end,
        shared_entry_count=shared_count,
        isolated_entry_count=isolated_count,
        shared_terminal_hash=shared_terminal,
        isolated_terminal_hash=isolated_terminal,
        kind_counts_shared=dict(shared_kinds),
        kind_counts_isolated=dict(isolated_kinds),
        is_consistent=is_consistent,
        inconsistency_reasons=tuple(reasons),
    )


__all__ = [
    "ParallelReplayDiff",
    "validate_parallel_replay",
]
