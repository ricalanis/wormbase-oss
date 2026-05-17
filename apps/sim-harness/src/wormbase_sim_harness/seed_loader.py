"""Install-arc seed-sequence loader (Seed-S1..S4).

Loads and time-aligns the four JSONL seed files in
``tests/fixtures/install_arc_seed/`` so they can be replayed through
the channel-adapter wire-replay primitive during the install arc demo.

Why this module exists
----------------------

Per PRD §7 Seed-S1..S4, the install arc shows variation only when
specific reactivities trip at specific beats. The four curated seed
files each contain ~10 messages that target one reactivity:

* ``S1 cursed_csv_chatter`` ─ trips ``KpiReferenceWithoutKpiReactivity``
  (phenomenon-gap KPI) at Beat 6.
* ``S2 recurring_action_chatter`` ─ trips
  ``RecurringActionWithoutReactivityReactivity`` (the meta-loop) at
  Beat 6.5.
* ``S3 domain_touched_chatter`` ─ trips ``StatementToOwnerReactivity``
  at Beat 8 (Carol DM in real Slack).
* ``S4 recurring_question_chatter`` ─ trips
  ``RecurringQuestionProcessMapper`` (P10) at Beat 5.

The loader is deliberately thin: it walks the seed directory, parses
each JSONL line, optionally re-stamps timestamps relative to a base
clock, and returns the unioned event stream sorted by ``seq``. The
actual replay happens through ``WireReplayer`` (the only writer of
flow-driven entries — per CLAUDE.md invariant 1, no flow-bypass).

Integration
-----------

The CLI's ``cmd_seed`` plumbs the ``--rich`` flag (W7.A1) through to
``seed_tenant``. After personas are confirmed and the rich enrichment
lands, this loader unions the seed JSONLs into a temp file and feeds
them through ``WireReplayer`` exactly like ``--replay-history`` does.
That keeps the seeds on the same code path as recorded production
captures: same propose/execute/verify/resolve cycle, same
``channel_adapter.emit_chat_received`` envelopes, same hash chain.

Determinism
-----------

The loader is content-deterministic by construction. The JSONL files
are committed; ``message_id`` and ``sender_person`` are pinned per
line. Re-running ``make seed --rich`` produces the same execute rows
in the same order modulo the ``ref_id`` UUIDs that ``WireReplayer``
mints per call (those are intentional fresh-chain markers).

Time alignment
--------------

The seeds reference absolute timestamps anchored at
``2026-04-28T00:00:00+00:00`` (the canonical install-arc epoch). Beat
windows in the PRD §5 Act-I table are also expressed against that
anchor. The loader exposes a ``base_ts`` knob so a wall-clock demo
can shift the absolute times forward into the present while preserving
relative spacing. By default ``base_ts=None`` keeps the recorded
timestamps as-is (matches CI determinism).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger("wormbase.sim.seed_loader")


# ---------------------------------------------------------------------------
# Constants — canonical install-arc anchor + seed file names
# ---------------------------------------------------------------------------


# Pinned epoch the seed JSONLs are written against. Matches PRD §5 and
# the canonical ``install-arc-7beat-canonical.jsonl`` fixture.
INSTALL_ARC_EPOCH: datetime = datetime(2026, 4, 28, 0, 0, 0, tzinfo=timezone.utc)


# Names of the four seed files in the order S1..S4. The order is
# stable; tests assert against it.
SEED_FILES: tuple[str, ...] = (
    "cursed_csv_chatter.jsonl",          # S1
    "recurring_action_chatter.jsonl",    # S2
    "domain_touched_chatter.jsonl",      # S3
    "recurring_question_chatter.jsonl",  # S4
)


# Canonical persona UUIDs that the seed JSONLs reference. These match
# the install-arc-7beat-canonical fixture (W6.A4) and the W7.A1 rich-
# seed personas (Bob, Carol, Alice). Pinned here so a future renamer
# can grep them without touching every JSONL.
PERSONA_UUIDS: dict[str, str] = {
    "bob":   "11111111-1111-1111-1111-111111111111",
    "carol": "22222222-2222-2222-2222-222222222222",
    "alice": "33333333-3333-3333-3333-333333333333",
}


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeedEvent:
    """One parsed seed-stream event ready for wire-replay.

    Attributes
    ----------
    seq:
        The ``seq`` field from the JSONL — used only for stable ordering
        across files. ``WireReplayer`` mints fresh ``ref_id`` UUIDs per
        write so this seq does NOT propagate to the ledger; it is the
        loader's notion of order.
    ts:
        Effective timestamp after any base-ts shift. UTC-aware datetime.
    tool:
        Wire tool string (e.g. ``channel_adapter.emit_chat_received``).
    args:
        Wire payload args verbatim from the JSONL.
    seed_id:
        Which seed file produced this event ("S1".."S4"). Useful for
        beat-level trip assertions in tests.
    beat_index:
        Optional beat index from the JSONL — used by tests to assert
        timing alignment.
    beat_label:
        Optional human-readable label from the JSONL (e.g.
        ``s1.bob.cursed-column-warning``).
    """

    seq: int
    ts: datetime
    tool: str
    args: dict[str, Any]
    seed_id: str
    beat_index: float | int | None = None
    beat_label: str | None = None

    def to_wire_dict(self) -> dict[str, Any]:
        """Render back to the JSONL shape ``WireReplayer`` consumes.

        ``WireReplayer`` only reads ``tool`` and ``args``; the other
        keys are passed through verbatim for downstream tools that may
        want to inspect provenance (the loader's ``write_unioned_jsonl``
        relies on this).
        """
        return {
            "seq": self.seq,
            "ts": self.ts.isoformat(),
            "tool": self.tool,
            "args": dict(self.args),
            "seed_id": self.seed_id,
            "beat_index": self.beat_index,
            "beat_label": self.beat_label,
        }


@dataclass
class SeedLoadReport:
    """Outcome of a ``load_install_arc_seeds`` call.

    Reports per-file event counts and the union total. Tests use the
    per-file counts to assert the loader didn't silently drop entries.
    """

    fixture_dir: Path
    base_ts: datetime | None
    total_events: int = 0
    events_per_seed: dict[str, int] = field(default_factory=dict)
    skipped_lines: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "fixture_dir": str(self.fixture_dir),
            "base_ts": self.base_ts.isoformat() if self.base_ts else None,
            "total_events": self.total_events,
            "events_per_seed": dict(self.events_per_seed),
            "skipped_lines": self.skipped_lines,
        }


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def default_fixture_dir() -> Path:
    """Locate ``tests/fixtures/install_arc_seed/`` from this module path.

    The sim-harness lives at ``apps/sim-harness/src/wormbase_sim_harness/``
    and the fixtures live at ``tests/fixtures/install_arc_seed/`` from
    the repo root. Walk up until we find a sibling ``tests`` directory
    so the helper survives re-rooting under a different layout.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "tests" / "fixtures" / "install_arc_seed"
        if candidate.is_dir():
            return candidate
    # Last resort: assume the canonical repo layout. This will surface
    # a clean FileNotFoundError later if the path is wrong, which is
    # better than guessing.
    return (
        here.parents[4] / "tests" / "fixtures" / "install_arc_seed"
    )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _seed_id_for(filename: str) -> str:
    """Map a seed-file name to its short id (``S1``..``S4``).

    Order matches ``SEED_FILES``. Defensive against an unknown file:
    returns ``"S?"`` so callers don't silently lose attribution.
    """
    try:
        idx = SEED_FILES.index(filename)
    except ValueError:
        return "S?"
    return f"S{idx + 1}"


def _parse_event_ts(rec: dict[str, Any]) -> datetime | None:
    """Pull a UTC-aware datetime out of the record's ``ts`` field.

    Supports ISO-8601 strings (preferred — that's what the JSONLs use)
    and plain unix-epoch floats (defensive — recorded captures may emit
    those). Returns ``None`` if neither parses, in which case the
    record will be skipped with a warning. Naive datetimes are upgraded
    to UTC.
    """
    raw = rec.get("ts")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(raw, str) and raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None
    return None


def _shift_ts(ts: datetime, *, anchor: datetime, base_ts: datetime) -> datetime:
    """Re-anchor ``ts`` so the install-arc epoch maps to ``base_ts``.

    Computes ``base_ts + (ts - anchor)`` while preserving sub-second
    precision. Pure-function so the loader stays trivially testable.
    """
    delta: timedelta = ts - anchor
    return base_ts + delta


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """Yield non-empty parsed JSON objects from ``path``.

    Mirrors ``wire_replay._iter_jsonl`` but kept local so the loader
    has zero hard dep on the channel-adapter package at parse time.
    """
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "seed_loader: skipping malformed line in %s: %s",
                    path.name, exc,
                )
                continue
            if not isinstance(rec, dict):
                logger.warning(
                    "seed_loader: skipping non-object record in %s: %r",
                    path.name, rec,
                )
                continue
            yield rec


def load_seed_file(
    path: Path,
    *,
    seed_id: str | None = None,
    base_ts: datetime | None = None,
    anchor: datetime = INSTALL_ARC_EPOCH,
) -> list[SeedEvent]:
    """Parse one seed JSONL file into a list of :class:`SeedEvent`.

    Parameters
    ----------
    path:
        JSONL file path.
    seed_id:
        Override the auto-derived ``S1``..``S4`` id. Pass ``"S?"`` if
        loading an ad-hoc file outside the canonical four.
    base_ts:
        If non-None, shift each event's timestamp so ``anchor`` maps
        to ``base_ts``. Use ``None`` (default) for byte-deterministic
        replay against CI; use a wall-clock now() for live demos.
    anchor:
        The reference time the JSONLs were written against. Defaults
        to ``INSTALL_ARC_EPOCH``.
    """
    sid = seed_id or _seed_id_for(path.name)
    out: list[SeedEvent] = []
    for rec in _iter_jsonl(path):
        ts = _parse_event_ts(rec)
        if ts is None:
            logger.warning(
                "seed_loader: skipping record without parseable ts in %s",
                path.name,
            )
            continue
        if base_ts is not None:
            ts = _shift_ts(ts, anchor=anchor, base_ts=base_ts)
        tool = rec.get("tool")
        args = rec.get("args")
        if not isinstance(tool, str) or not isinstance(args, dict):
            logger.warning(
                "seed_loader: skipping record with bad tool/args in %s: %r",
                path.name, rec,
            )
            continue
        seq = int(rec.get("seq", 0) or 0)
        out.append(SeedEvent(
            seq=seq,
            ts=ts,
            tool=tool,
            args=dict(args),
            seed_id=sid,
            beat_index=rec.get("beat_index"),
            beat_label=rec.get("beat_label"),
        ))
    return out


def load_install_arc_seeds(
    fixture_dir: Path | None = None,
    *,
    base_ts: datetime | None = None,
    seed_files: Iterable[str] = SEED_FILES,
) -> tuple[list[SeedEvent], SeedLoadReport]:
    """Load all four seed JSONLs and return the time-sorted union.

    Returns
    -------
    events:
        Combined :class:`SeedEvent` list, sorted ascending by ``ts``
        and then by ``seq`` to break ties deterministically.
    report:
        :class:`SeedLoadReport` with per-file counts and totals.
    """
    fdir = fixture_dir or default_fixture_dir()
    if not fdir.is_dir():
        raise FileNotFoundError(
            f"install-arc seed fixture dir not found: {fdir}",
        )
    report = SeedLoadReport(fixture_dir=fdir, base_ts=base_ts)
    all_events: list[SeedEvent] = []
    for fname in seed_files:
        path = fdir / fname
        if not path.is_file():
            # Missing file is a structural problem — fail loud so
            # ``make seed --rich`` doesn't silently drop a beat.
            raise FileNotFoundError(
                f"install-arc seed file missing: {path}",
            )
        sid = _seed_id_for(fname)
        loaded = load_seed_file(
            path, seed_id=sid, base_ts=base_ts,
        )
        report.events_per_seed[sid] = len(loaded)
        all_events.extend(loaded)
    # Sort by (ts, seq) so the wire-replay reads them in install-arc
    # chronological order regardless of which file contributed which
    # event.
    all_events.sort(key=lambda e: (e.ts, e.seq))
    report.total_events = len(all_events)
    return all_events, report


# ---------------------------------------------------------------------------
# Union JSONL writer
# ---------------------------------------------------------------------------


def write_unioned_jsonl(
    events: Iterable[SeedEvent],
    out_path: Path,
) -> int:
    """Write events as a single JSONL file consumable by ``WireReplayer``.

    The wire-replay tool reads only ``tool`` and ``args`` per record,
    so we re-stamp each ``ts`` to its (possibly shifted) effective
    value and preserve the seed attribution + beat metadata for any
    downstream consumer (e.g. integration tests, /trace overlays).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev.to_wire_dict(), separators=(",", ":")))
            f.write("\n")
            n += 1
    return n


__all__ = [
    "INSTALL_ARC_EPOCH",
    "PERSONA_UUIDS",
    "SEED_FILES",
    "SeedEvent",
    "SeedLoadReport",
    "default_fixture_dir",
    "load_install_arc_seeds",
    "load_seed_file",
    "write_unioned_jsonl",
]
