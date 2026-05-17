"""Keep-rate projection (Demo-day P1).

Reads ``experiment_resolved`` entries from the ledger and folds them
into per-(scope, day) ``kept / total`` ratios. Three scopes:

  * ``person``  — ``experiment_proposed.audience`` starts with ``"person:"``
  * ``team``    — audience starts with ``"team:"``
  * ``company`` — audience equals ``"company"``

Pre-W5.A4 experiments without an ``audience`` field are interpreted as
Person-scoped (the canonical migration-safe interpretation; see
``ExperimentProposedPayload`` docstring).

The projection is the read-side of ``keep_rate_publisher`` (the
nightly job that materializes published rows as
``metrics_keep_rate_published`` ledger entries). The dashboard chart
prefers published rows when present and falls back to a real-time
recomputation otherwise — the projection here is the source for both.

Output rows are tagged ``synthetic`` when the day's data is below a
minimum-sample threshold (default: 3 resolutions). The dashboard
renders this as a "synthetic baseline" badge so the chart never lies
about its sample size.

Replay safety: identical row stream → identical (kept, total, ratio)
tuple per (scope, day). Day buckets use ISO-8601 dates anchored to
UTC so a tenant in Sydney and a tenant in San Francisco bucket
identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Mapping

# Below this resolution count for a (scope, day), the chart marks the
# point ``synthetic`` so the dashboard can render a "synthetic baseline"
# badge. Set to 1 so any single resolution still publishes a real ratio
# (the ratio is honest; the badge surfaces the small-sample caveat).
_MIN_RESOLUTIONS_FOR_REAL_BASELINE: int = 3


@dataclass(frozen=True)
class KeepRateRow:
    """One (scope, day, ratio) sample."""

    scope: str  # "person" | "team" | "company"
    day: str  # ISO-8601 date YYYY-MM-DD (UTC bucket)
    kept: int
    total: int
    ratio: float
    synthetic: bool = False


def _audience_to_scope(audience: str | None) -> str:
    """Pre-W5.A4 audience-less rows interpret as ``person`` (per entries.py)."""
    if not audience:
        return "person"
    if audience.startswith("person:"):
        return "person"
    if audience.startswith("team:"):
        return "team"
    if audience == "company":
        return "company"
    return "person"


def _ts_of(row: Mapping[str, Any]) -> datetime:
    ts = row.get("ts")
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    if isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    raise TypeError(f"unparseable ts on row seq={row.get('seq')!r}: {ts!r}")


def _is_execute_with_tool(row: Mapping[str, Any], tool: str) -> bool:
    return (
        row.get("kind") == "execute"
        and row.get("payload", {}).get("tool") == tool
    )


def _proposal_audience_index(
    rows: list[Mapping[str, Any]],
) -> dict[str, str]:
    """experiment_id → audience (resolved). Pre-W5.A4 rows default to person."""
    out: dict[str, str] = {}
    for r in rows:
        if not _is_execute_with_tool(r, "emit_experiment_proposed"):
            continue
        args = r.get("payload", {}).get("args", {}) or {}
        eid = args.get("experiment_id")
        audience = args.get("audience")
        if not eid:
            continue
        out[str(eid)] = audience or "person"
    return out


def keep_rate_for_window(
    rows: list[Mapping[str, Any]],
    *,
    day: date,
    scopes: tuple[str, ...] = ("person", "team", "company"),
) -> list[KeepRateRow]:
    """Per-scope keep-rate over the trailing-24h window anchored at ``day``.

    Used by ``keep_rate_publisher`` to write one
    ``metrics_keep_rate_published`` ledger entry per scope per day.
    Idempotent at the projection layer — running for the same day with
    the same row stream returns byte-identical rows.
    """
    audience_idx = _proposal_audience_index(rows)
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    end = start + timedelta(days=1)

    # Bucket resolutions by scope.
    counts: dict[str, dict[str, int]] = {
        s: {"kept": 0, "discarded": 0} for s in scopes
    }
    for r in rows:
        if not _is_execute_with_tool(r, "emit_experiment_resolved"):
            continue
        ts = _ts_of(r)
        if ts < start or ts >= end:
            continue
        args = r.get("payload", {}).get("args", {}) or {}
        eid = str(args.get("experiment_id", ""))
        outcome = args.get("outcome")
        scope = _audience_to_scope(audience_idx.get(eid))
        if scope not in counts:
            continue
        if outcome == "keep":
            counts[scope]["kept"] += 1
        elif outcome == "discard":
            counts[scope]["discarded"] += 1

    rows_out: list[KeepRateRow] = []
    for scope in scopes:
        kept = counts[scope]["kept"]
        discarded = counts[scope]["discarded"]
        total = kept + discarded
        ratio = (kept / total) if total > 0 else 0.0
        synthetic = total < _MIN_RESOLUTIONS_FOR_REAL_BASELINE
        rows_out.append(
            KeepRateRow(
                scope=scope,
                day=day.isoformat(),
                kept=kept,
                total=total,
                ratio=ratio,
                synthetic=synthetic,
            )
        )
    return rows_out


def keep_rate_series(
    rows: list[Mapping[str, Any]],
    *,
    days: int = 7,
    end_day: date | None = None,
    scopes: tuple[str, ...] = ("person", "team", "company"),
) -> list[KeepRateRow]:
    """Per-scope per-day keep-rate over the trailing ``days`` window.

    Always emits ``days * len(scopes)`` rows so the chart has a
    consistent x-axis even when a scope had zero resolutions on a day.
    Days with insufficient data carry ``synthetic=True`` (the
    dashboard badges them).
    """
    end = end_day or datetime.now(UTC).date()
    out: list[KeepRateRow] = []
    for offset in range(days - 1, -1, -1):
        d = end - timedelta(days=offset)
        out.extend(keep_rate_for_window(rows, day=d, scopes=scopes))
    return out
