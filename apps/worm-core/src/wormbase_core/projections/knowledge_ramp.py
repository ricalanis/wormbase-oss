"""Knowledge-ramp gauge projections (Demo-day P2).

Three integer-counted gauges folded purely from the ledger row stream:

  * **ontology**       — count of concept entries
                         (`concept_proposed` + `concept_confirmed`)
  * **conversational** — count of `chat_received` entries (lurker path
                         and the channel-adapter ``emit_chat_received``
                         path both fold into the same gauge)
  * **relational**     — count of KPI tree growth entries
                         (`kpi_proposed` + `kpi_node` + `kpi_edge` —
                         all current and aspirational KPI-shaped emits)

Each gauge returns:

  * ``count`` — total integer count over the entire ledger for the tenant
  * ``sparkline`` — per-minute counts over the trailing 60 minutes,
                    capped at 100 contributing entries (whichever shorter
                    per the PRD §7 P2 spec)
  * ``last_seq`` — the seq of the most recent contributing entry
                   (the dashboard uses this to deep-link `/trace`
                   scrolled to the most recent row)

The PRD's ``concept_emitted`` / ``kpi_node_added`` / ``kpi_edge_added``
names are aspirational — the projection counts whatever real entries
match the conceptual axis today and will pick up additional kinds as
sister workstreams (P1, P9) extend the entries register. Empty axes
return ``0`` honestly; the dashboard renders the count + a hint string
rather than a fixture fallback (PRD §7 empty-state rule).

Determinism: the row stream is the only input. Two replays with
identical row sequences produce byte-identical gauge values. Tested by
``tests/test_knowledge_ramp_projection.py``.

Architectural fit (Triad):
  * a16z institutional — gauges are deterministic + auditable; every
    increment traces back to a hash-chained entry.
  * Karpathy memory — gauges grow at near-zero maintenance cost; the
    worm's lurking compounds into the count.
  * autoresearch — the gauges are the visible heartbeat of the
    self-improvement loop; tick during install arc by construction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

GaugeAxis = Literal["ontology", "conversational", "relational"]

#: All three axes in canonical render order. Stable across releases so the
#: dashboard tile layout is deterministic.
GAUGE_AXES: tuple[GaugeAxis, ...] = ("ontology", "conversational", "relational")

#: Sparkline window — last 60 minutes, one minute per bucket.
SPARKLINE_WINDOW: timedelta = timedelta(minutes=60)
SPARKLINE_BUCKETS: int = 60

#: Max contributing entries the sparkline summarizes; PRD §7 P2 caps at
#: 100 entries even when the 60-minute window contains more (keeps the
#: visual noise floor stable on busy tenants).
SPARKLINE_MAX_ENTRIES: int = 100

#: Trace-filter substring published by each gauge's deep-link. Picked
#: so the substring matches every contributing entry kind (the trace
#: filter does substring matching on the ``derivedKind``).
TRACE_FILTER_KIND: dict[GaugeAxis, str] = {
    # Substring 'concept_' matches both ``concept_proposed`` and
    # ``concept_confirmed`` derivedKinds in the trace stream.
    "ontology": "concept_",
    # Substring 'chat_received' matches both ``chat_received`` (lurker
    # path) and ``channel_adapter.emit_chat_received`` (wire path).
    "conversational": "chat_received",
    # Substring 'kpi_' matches ``kpi_proposed``, ``kpi_node``, and any
    # future ``kpi_edge`` / ``kpi_node_added`` kinds added by sister
    # workstreams without requiring a code change here.
    "relational": "kpi_",
}


@dataclass(frozen=True)
class GaugeReading:
    """One axis worth of gauge state.

    ``count`` is the integer over the whole ledger; ``sparkline`` is a
    fixed-length list of per-minute counts (oldest → newest); ``last_seq``
    points the trace deep-link at the most recent contributing row.
    """

    axis: GaugeAxis
    count: int
    sparkline: list[int]
    last_seq: int  # 0 when the axis has no entries yet
    last_ts: str | None  # ISO-8601 UTC of the most recent contributing row
    trace_filter: str  # substring filter for /trace?kind=<value>

    def to_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "count": self.count,
            "sparkline": list(self.sparkline),
            "last_seq": self.last_seq,
            "last_ts": self.last_ts,
            "trace_filter": self.trace_filter,
        }


@dataclass(frozen=True)
class KnowledgeRampGauges:
    """All three gauges in canonical order plus the projection horizon."""

    company_id: str
    computed_at: str  # ISO-8601 UTC
    window_seconds: int
    gauges: list[GaugeReading] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id,
            "computed_at": self.computed_at,
            "window_seconds": self.window_seconds,
            "gauges": [g.to_dict() for g in self.gauges],
        }

    def by_axis(self, axis: GaugeAxis) -> GaugeReading:
        for g in self.gauges:
            if g.axis == axis:
                return g
        raise KeyError(f"no gauge for axis {axis!r}")


# ---------------------------------------------------------------------------
# Pure-function fold
# ---------------------------------------------------------------------------


def _ts_of(row: Mapping[str, Any]) -> datetime:
    """Coerce a ledger row's ts to a tz-aware UTC datetime."""
    ts = row.get("ts")
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    if isinstance(ts, str):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    raise TypeError(f"unparseable ts on row seq={row.get('seq')!r}: {ts!r}")


def _seq_of(row: Mapping[str, Any]) -> int:
    seq = row.get("seq", 0)
    try:
        return int(seq)
    except (TypeError, ValueError):
        return 0


def _execute_tool(row: Mapping[str, Any]) -> str | None:
    """Return ``payload.tool`` for execute rows, else None."""
    if row.get("kind") != "execute":
        return None
    payload = row.get("payload") or {}
    tool = payload.get("tool")
    return tool if isinstance(tool, str) else None


def _matches_axis(row: Mapping[str, Any], axis: GaugeAxis) -> bool:
    """True iff ``row`` is a contributing entry for ``axis``.

    Counts both the canonical PEVR ``execute`` shape (with
    ``payload.tool``) and any direct-kind shapes ledger writers may use
    historically. The two paths are equivalent for the gauge fold —
    both register one entry's worth of ramp motion.
    """
    kind = row.get("kind")

    if axis == "ontology":
        if kind in ("concept_proposed", "concept_confirmed"):
            return True
        tool = _execute_tool(row)
        if tool in (
            "emit_concept_proposed",
            "emit_concept_confirmed",
            "emit_concept_emitted",  # aspirational PRD name
        ):
            return True
        return False

    if axis == "conversational":
        if kind == "chat_received":
            return True
        tool = _execute_tool(row)
        if tool in (
            "emit_chat_received",
            "channel_adapter.emit_chat_received",
        ):
            return True
        return False

    if axis == "relational":
        if kind in ("kpi_proposed",):
            return True
        tool = _execute_tool(row)
        if tool in (
            "emit_kpi_proposed",
            "emit_kpi_node",
            "emit_kpi_edge",  # aspirational, future P9/P12 scope
            "emit_kpi_node_added",
            "emit_kpi_edge_added",
        ):
            return True
        return False

    return False


def _bucket_index(ts: datetime, *, now: datetime, buckets: int) -> int | None:
    """Return the sparkline-bucket index for a ts, or None if out of window.

    Buckets are 1-minute wide, indexed 0 (oldest) → buckets-1 (newest).
    Out-of-window entries return None and are dropped from the sparkline
    (they still count toward the cumulative ``count``).
    """
    delta = now - ts
    if delta < timedelta(0):
        # Future-dated row (clock skew or test fixture); slot at newest.
        return buckets - 1
    if delta >= SPARKLINE_WINDOW:
        return None
    seconds_old = int(delta.total_seconds())
    minutes_old = seconds_old // 60
    idx = (buckets - 1) - minutes_old
    if idx < 0:
        return 0
    if idx >= buckets:
        return buckets - 1
    return idx


def compute_knowledge_ramp_gauges(
    rows: Iterable[Mapping[str, Any]],
    *,
    company_id: UUID | str,
    now: datetime | None = None,
) -> KnowledgeRampGauges:
    """Fold a ledger row stream into three integer-counted gauges.

    Pure function. ``rows`` is the full row stream for a tenant (caller
    is responsible for tenant filtering — pass ``ledger.fetch(company_id)``
    or its SQL-side equivalent). ``now`` lets tests pin the window
    horizon for determinism; defaults to ``datetime.now(UTC)``.

    Empty-state rule: an axis with zero contributing entries returns a
    ``GaugeReading`` with ``count=0`` and a sparkline of zeros. The
    dashboard renders ``0`` plus a hint string honestly — no fixture
    fallback.
    """
    now_dt = now if now is not None else datetime.now(UTC)
    company_str = str(company_id)

    # Per-axis state accumulators.
    counts: dict[GaugeAxis, int] = {a: 0 for a in GAUGE_AXES}
    sparklines: dict[GaugeAxis, list[int]] = {
        a: [0] * SPARKLINE_BUCKETS for a in GAUGE_AXES
    }
    last_seq: dict[GaugeAxis, int] = {a: 0 for a in GAUGE_AXES}
    last_ts: dict[GaugeAxis, datetime | None] = {a: None for a in GAUGE_AXES}

    # Two-pass: collect contributing rows per axis, take the most recent
    # SPARKLINE_MAX_ENTRIES for the sparkline (PRD: 60min OR 100 entries,
    # whichever shorter). Walking the rows once and keeping a per-axis
    # sliding window of recent seqs is O(N) and replay-stable.
    contributing: dict[GaugeAxis, list[tuple[int, datetime]]] = {
        a: [] for a in GAUGE_AXES
    }

    for row in rows:
        for axis in GAUGE_AXES:
            if not _matches_axis(row, axis):
                continue
            counts[axis] += 1
            seq = _seq_of(row)
            ts = _ts_of(row)
            if seq > last_seq[axis]:
                last_seq[axis] = seq
                last_ts[axis] = ts
            contributing[axis].append((seq, ts))

    # Sparkline fill — last min(window, 100) contributing entries.
    for axis in GAUGE_AXES:
        # Sort by seq so "most recent" is well-defined regardless of
        # in-memory row ordering.
        contribs_sorted = sorted(contributing[axis], key=lambda x: x[0])
        # Cap to the most-recent SPARKLINE_MAX_ENTRIES; this is the
        # "100 entries" half of the PRD's "60min OR 100 entries"
        # constraint.
        recent = contribs_sorted[-SPARKLINE_MAX_ENTRIES:]
        for _seq, ts in recent:
            idx = _bucket_index(ts, now=now_dt, buckets=SPARKLINE_BUCKETS)
            if idx is None:
                continue
            sparklines[axis][idx] += 1

    gauges = [
        GaugeReading(
            axis=axis,
            count=counts[axis],
            sparkline=sparklines[axis],
            last_seq=last_seq[axis],
            last_ts=last_ts[axis].isoformat() if last_ts[axis] else None,
            trace_filter=TRACE_FILTER_KIND[axis],
        )
        for axis in GAUGE_AXES
    ]

    return KnowledgeRampGauges(
        company_id=company_str,
        computed_at=now_dt.isoformat(),
        window_seconds=int(SPARKLINE_WINDOW.total_seconds()),
        gauges=gauges,
    )


__all__ = [
    "GAUGE_AXES",
    "GaugeAxis",
    "GaugeReading",
    "KnowledgeRampGauges",
    "SPARKLINE_BUCKETS",
    "SPARKLINE_MAX_ENTRIES",
    "SPARKLINE_WINDOW",
    "TRACE_FILTER_KIND",
    "compute_knowledge_ramp_gauges",
]
