"""wormbase-ingest-transcript — ingest an SRT meeting transcript into the ledger.

Usage
-----
::

    $ uv run wormbase-ingest-transcript \\
        --tenant altis \\
        --meeting-id altis-wormbase-kickoff-prep \\
        --srt /path/to/meeting.srt \\
        --speakers "Ricardo Alanís,Poncho Garciga,Ruben Madiedo"

    parsed 135 cues, 60 turns after speaker-grouping
    ingested 60 chat_received entries for tenant altis
    session_id: meeting-altis-wormbase-kickoff-prep
    time range: 2026-05-22T23:00:00 .. 2026-05-22T23:10:35 (10m 35s)
    ledger seq range: 4567..4626

Flags
-----
--tenant <slug>           (required) — resolves via uuid5
--meeting-id <id>         (required) — opaque slug
--srt <path>              (required) — path to SRT file
--speakers <n1>,<n2>,...  (optional) — expected speakers; warn on unknown
--meeting-date YYYY-MM-DD (optional) — base date; derived from header or today
--dsn <url>               (optional) — falls back to WORMBASE_LEDGER_DSN
--dry-run                 — parse + summarize, no ledger writes

NOTE: delivery_mode
-------------------
``ChatReceivedPayload.delivery_mode`` is ``Literal["push", "history_sync"]``.
The value ``"transcript"`` is not in the schema. Transcript ingestion uses
``"history_sync"`` as the closest semantic match (bulk replay of historical
content, not a live-wire push event). A future schema extension can add
``"transcript"`` and this script can be updated.

Tenant resolution
-----------------
Cross-reference: ``apps/voice-agent/src/wormbase_voice_agent/app.py``
defines ``_tenant_to_company_uuid`` using the identical namespace + uuid5
logic. Both must stay in sync; the namespace UUID is the canonical constant
defined in ``WORMBASE_TENANT_NAMESPACE``.

    namespace = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")
    company_id = uuid5(namespace, slug.strip().lower())
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
import warnings
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tenant resolution — mirrors apps/voice-agent/src/wormbase_voice_agent/app.py
# ---------------------------------------------------------------------------

WORMBASE_TENANT_NAMESPACE: str = "6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f"


def _tenant_to_company_uuid(slug: str) -> UUID:
    """Convert a tenant slug to a deterministic company UUID (mirrors ledger_recent)."""
    if not slug or not slug.strip():
        raise ValueError("tenant slug must be non-empty")
    return uuid5(UUID(WORMBASE_TENANT_NAMESPACE), slug.strip().lower())


# Stable namespace for transcript speaker → sender_person UUID mapping.
TRANSCRIPT_SPEAKER_NAMESPACE = uuid5(
    UUID(WORMBASE_TENANT_NAMESPACE),
    "transcript-speaker-namespace",
)


def speaker_to_person_uuid(speaker: str | None) -> UUID:
    """Deterministic mapping of a speaker name to a sender_person UUID."""
    if not speaker:
        return uuid5(TRANSCRIPT_SPEAKER_NAMESPACE, "__unknown_speaker__")
    return uuid5(TRANSCRIPT_SPEAKER_NAMESPACE, speaker.strip())


# ---------------------------------------------------------------------------
# SRT parsing
# ---------------------------------------------------------------------------

_TIMING_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)
_SPEAKER_RE = re.compile(r"^(.+?):\s+(.+)$", re.DOTALL)
# Header line pattern: "Meeting created at: 22nd May, 2026 - 11:00 PM"
_HEADER_DATE_RE = re.compile(
    r"Meeting created at:\s*(\d+)\w*\s+(\w+),?\s+(\d{4})\s+-\s+(\d+:\d+)\s*(AM|PM)?",
    re.IGNORECASE,
)
_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


@dataclass
class SrtCue:
    """One parsed cue from an SRT file."""

    index: int
    start_ts: timedelta
    end_ts: timedelta
    speaker: str
    text: str


@dataclass
class Turn:
    """Consecutive cues from the same speaker grouped into one conversational turn."""

    speaker: str
    start_ts: timedelta
    end_ts: timedelta
    texts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.texts)


def _parse_timing(line: str) -> tuple[timedelta, timedelta] | None:
    """Parse a timing line ``HH:MM:SS,mmm --> HH:MM:SS,mmm`` to two timedeltas.

    Returns ``None`` when the line doesn't match (defensive).
    """
    m = _TIMING_RE.search(line)
    if not m:
        return None
    h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in m.groups())
    start = timedelta(hours=h1, minutes=m1, seconds=s1, milliseconds=ms1)
    end = timedelta(hours=h2, minutes=m2, seconds=s2, milliseconds=ms2)
    return start, end


def _parse_text(raw: str) -> tuple[str, str]:
    """Split ``Speaker: body`` text into (speaker, body).

    Returns ``("unknown", raw)`` when the pattern doesn't match.
    """
    m = _SPEAKER_RE.match(raw.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "unknown", raw.strip()


def parse_srt(content: str) -> tuple[list[SrtCue], datetime | None]:
    """Parse SRT content into cues, returning ``(cues, detected_start_dt)``.

    ``detected_start_dt`` is a timezone-aware UTC datetime extracted from a
    Fireflies header line if present (``Meeting created at: ...``), else
    ``None``. When the header carries a time-of-day (e.g. "11:00 PM"), the
    returned datetime includes that time so cue offsets anchor correctly to
    the real meeting start rather than to UTC midnight.

    Defensive: skips blocks that don't have a valid index + timing. The
    Fireflies header may be glued to cue index 1 without a separating newline
    (i.e. ``"Meeting created at: ... 11:00 PM1"`` as a single line before the
    timing) — this function normalises that case.
    """
    # Normalise line endings.
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # Detect and strip optional Fireflies header. The header may be:
    # (a) its own line, then a blank line, then cue 1
    # (b) glued directly to "1" with no separator newline
    detected_start_dt: datetime | None = None
    lines = content.splitlines()
    cleaned_lines: list[str] = []
    for line in lines:
        hm = _HEADER_DATE_RE.search(line)
        if hm:
            # Groups: 1=day, 2=month-name, 3=year, 4=HH:MM, 5=AM/PM (may be None)
            day = int(hm.group(1))
            month_str = hm.group(2).lower()
            year = int(hm.group(3))
            time_str = hm.group(4)  # e.g. "11:00"
            ampm = (hm.group(5) or "").upper()
            month = _MONTH_MAP.get(month_str)
            if month:
                try:
                    d = date(year, month, day)
                except ValueError:
                    d = date(year, month, 1)
                # Parse time component if present.
                hour, minute = 0, 0
                if time_str:
                    try:
                        hh, mm = (int(x) for x in time_str.split(":"))
                        if ampm == "PM" and hh != 12:
                            hh += 12
                        elif ampm == "AM" and hh == 12:
                            hh = 0
                        hour, minute = hh, mm
                    except (ValueError, AttributeError):
                        pass
                detected_start_dt = datetime(
                    d.year, d.month, d.day, hour, minute, tzinfo=UTC
                )
            # The header may be glued to the next token. Strip the header
            # portion and keep the remainder (e.g. "1" for cue index).
            remainder = _HEADER_DATE_RE.sub("", line).strip()
            if remainder:
                cleaned_lines.append(remainder)
            # else: header was its own line — drop it entirely.
        else:
            cleaned_lines.append(line)

    # Re-join and split into blocks on blank lines.
    cleaned = "\n".join(cleaned_lines)
    blocks = re.split(r"\n\s*\n", cleaned)

    cues: list[SrtCue] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        blines = block.splitlines()
        if len(blines) < 2:
            continue

        # Line 0 should be the cue index (integer).
        try:
            idx = int(blines[0].strip())
        except ValueError:
            continue  # Not a valid cue block — skip defensively.

        # Line 1 should be the timing.
        timing = _parse_timing(blines[1])
        if timing is None:
            continue  # Malformed timing — skip.
        start_ts, end_ts = timing

        # Lines 2+ are text.
        raw_text = "\n".join(blines[2:]).strip()
        if not raw_text:
            continue

        speaker, text = _parse_text(raw_text)
        cues.append(SrtCue(index=idx, start_ts=start_ts, end_ts=end_ts, speaker=speaker, text=text))

    return cues, detected_start_dt


def group_turns(cues: list[SrtCue], gap_threshold_s: float = 30.0) -> list[Turn]:
    """Group consecutive cues from the same speaker into turns.

    A new turn starts when:
    - The speaker changes, OR
    - The gap between the previous cue's end_ts and this cue's start_ts
      exceeds ``gap_threshold_s`` seconds.

    Args:
        cues:             Ordered list of parsed SRT cues.
        gap_threshold_s:  Maximum gap in seconds to merge into the same turn.

    Returns:
        List of Turn objects in chronological order.
    """
    if not cues:
        return []

    turns: list[Turn] = []
    current: Turn | None = None

    for cue in cues:
        gap = (cue.start_ts - (current.end_ts if current else timedelta(0))).total_seconds()
        same_speaker = current is not None and cue.speaker == current.speaker
        within_gap = gap <= gap_threshold_s

        if current is None or not same_speaker or not within_gap:
            # Start a new turn.
            current = Turn(
                speaker=cue.speaker,
                start_ts=cue.start_ts,
                end_ts=cue.end_ts,
                texts=[cue.text],
            )
            turns.append(current)
        else:
            # Merge into the current turn.
            current.end_ts = max(current.end_ts, cue.end_ts)
            current.texts.append(cue.text)

    return turns


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------

async def _emit_turn(
    ledger: Any,
    *,
    company_id: UUID,
    session_id: str,
    channel_id: str,
    message_id: str,
    turn: Turn,
    platform_ts: datetime,
    proposed_by: str = "ingest-transcript",
) -> Any:
    """Persist one transcript turn via the canonical PEVR cycle.

    Uses ``delivery_mode="history_sync"`` because ``"transcript"`` is not in
    the current ``ChatReceivedPayload`` schema (Literal["push", "history_sync"]).
    This is the closest semantic match: batched historical content, not a
    live-wire event.

    NOTE: A future schema extension can add ``delivery_mode="transcript"``; this
    call site can be updated at that time without restructuring the PEVR pattern.
    """
    # Local import so tests that inject InMemoryLedger don't need DB deps.
    from wormbase_ledger.entries import ChatReceivedPayload  # noqa: PLC0415

    ref_id = uuid4()
    sender_person = speaker_to_person_uuid(turn.speaker)

    payload = ChatReceivedPayload(
        channel_id=channel_id,
        message_id=message_id,
        sender_person=sender_person,
        text=turn.text,
        classification="internal",
        delivery_mode="history_sync",
        platform_ts=platform_ts,
        platform_user_id=turn.speaker or None,
    )
    args = payload.model_dump(mode="json")

    return await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "chat_received",
            "ref_id": str(ref_id),
            "reason": f"transcript inbound from {turn.speaker}",
            "proposed_by": proposed_by,
        },
        execute_fn=lambda: {
            "tool": "ingest_transcript.emit_chat_received",
            "args": args,
            "result_ref": message_id,
            "modality": "transcript",
            "audio_ref": None,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "payload_valid", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "transcript turn persisted",
        },
        timestamp=platform_ts,
        quadrant="active_probabilistic",
    )


# ---------------------------------------------------------------------------
# Shared turn-emission helper (used by both ingest_transcript and pull_fireflies)
# ---------------------------------------------------------------------------

async def ingest_turns(
    ledger: Any,
    *,
    company_id: UUID,
    meeting_id: str,
    base_dt: datetime,
    turns: list[Turn],
    proposed_by: str = "ingest-transcript",
) -> None:
    """Emit one ledger PEVR cycle per turn into ``ledger``.

    This is the canonical entry point for writing transcript turns — both
    ``wormbase-ingest-transcript`` (SRT path) and ``wormbase-pull-fireflies``
    (Fireflies sentences path) call this function so the per-turn ledger shape
    is identical across ingestion methods.

    Args:
        ledger:      Ledger or InMemoryLedger instance.
        company_id:  Resolved company UUID for the tenant.
        meeting_id:  Opaque meeting slug (e.g. ``"altis-ff-meet-aaaa-1111"``).
        base_dt:     UTC datetime that anchors turn offsets (cue start_ts is
                     added to this to produce ``platform_ts``).
        turns:       Ordered list of Turn objects to emit.
        proposed_by: String recorded in the ``proposed_by`` field of each
                     propose entry. Defaults to ``"ingest-transcript"`` for
                     backward compatibility.
    """
    channel_id = f"meeting:{meeting_id}"

    for turn_idx, turn in enumerate(turns):
        message_id = f"transcript-{meeting_id}-{turn_idx:04d}"
        platform_ts = base_dt + turn.start_ts
        await _emit_turn(
            ledger,
            company_id=company_id,
            session_id=f"meeting-{meeting_id}",
            channel_id=channel_id,
            message_id=message_id,
            turn=turn,
            platform_ts=platform_ts,
            proposed_by=proposed_by,
        )


# ---------------------------------------------------------------------------
# Date resolution helpers
# ---------------------------------------------------------------------------

def _derive_base_datetime(
    detected_start_dt: datetime | None,
    *,
    meeting_date_str: str | None,
) -> tuple[datetime, list[str]]:
    """Resolve the base UTC datetime for anchoring transcript cue offsets.

    Priority:
    1. ``--meeting-date`` CLI flag (YYYY-MM-DD) — anchors to UTC midnight on
       that date (time-of-day from the SRT header is discarded when an explicit
       date is given, since the user override may be in a different timezone).
    2. ``detected_start_dt`` from SRT header (date + time-of-day; UTC).
    3. Today's date at UTC midnight with WARN.

    Returns ``(base_dt, warnings)`` where ``warnings`` is a list of warning
    strings to print after the summary.
    """
    warns: list[str] = []

    if meeting_date_str:
        try:
            d = date.fromisoformat(meeting_date_str)
            return datetime(d.year, d.month, d.day, tzinfo=UTC), warns
        except ValueError:
            warns.append(
                f"WARN: --meeting-date {meeting_date_str!r} is not a valid YYYY-MM-DD date; falling back."
            )

    if detected_start_dt is not None:
        return detected_start_dt, warns

    today = date.today()
    warns.append(
        f"WARN: no meeting date found in SRT header and --meeting-date not supplied; "
        f"defaulting to today ({today.isoformat()})."
    )
    return datetime(today.year, today.month, today.day, tzinfo=UTC), warns


def _format_duration(td: timedelta) -> str:
    """Format a timedelta as ``Xm Ys``."""
    total_seconds = int(td.total_seconds())
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds}s"


# ---------------------------------------------------------------------------
# Core ingest logic
# ---------------------------------------------------------------------------

async def _ingest(
    ledger: Any,
    *,
    company_id: UUID,
    tenant_slug: str,
    meeting_id: str,
    srt_content: str,
    speakers: set[str] | None,
    base_date_str: str | None,
    dry_run: bool,
) -> None:
    """Parse the SRT content and emit ledger entries.

    Prints the summary block to stdout. Warnings go to stderr.
    """
    cues, detected_start_dt = parse_srt(srt_content)
    turns = group_turns(cues)

    base_dt, date_warns = _derive_base_datetime(
        detected_start_dt,
        meeting_date_str=base_date_str,
    )

    session_id = f"meeting-{meeting_id}"
    channel_id = f"meeting:{meeting_id}"

    # Speaker validation.
    speaker_warns: list[str] = []
    if speakers is not None:
        seen_unknown = set()
        for turn in turns:
            if turn.speaker not in speakers and turn.speaker not in seen_unknown:
                seen_unknown.add(turn.speaker)
                speaker_warns.append(
                    f"WARN: speaker {turn.speaker!r} is not in the expected speakers list."
                )

    # Collect seq range info.
    first_seq: int | None = None
    last_seq: int | None = None

    if not dry_run:
        await ingest_turns(
            ledger,
            company_id=company_id,
            meeting_id=meeting_id,
            base_dt=base_dt,
            turns=turns,
        )
        try:
            rows = await ledger.fetch(company_id)
            if rows:
                first_seq = rows[0].get("seq")
                last_seq = rows[-1].get("seq")
        except Exception:  # noqa: BLE001
            pass

    # Print summary.
    if turns:
        time_start = base_dt + turns[0].start_ts
        time_end = base_dt + turns[-1].end_ts
        duration = turns[-1].end_ts - turns[0].start_ts
        time_range = (
            f"{time_start.strftime('%Y-%m-%dT%H:%M:%S')} .. "
            f"{time_end.strftime('%Y-%m-%dT%H:%M:%S')} "
            f"({_format_duration(duration)})"
        )
    else:
        time_range = "no turns"

    print(f"parsed {len(cues)} cues, {len(turns)} turns after speaker-grouping")
    if dry_run:
        print(f"dry-run: no ledger writes (would have ingested {len(turns)} chat_received entries for tenant {tenant_slug})")
    else:
        print(f"ingested {len(turns)} chat_received entries for tenant {tenant_slug}")
    print(f"session_id: {session_id}")
    print(f"time range: {time_range}")
    if first_seq is not None and last_seq is not None:
        print(f"ledger seq range: {first_seq}..{last_seq}")

    # Emit any accumulated warnings to stderr.
    for w in date_warns + speaker_warns:
        print(w, file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    ledger: Any = None,
) -> None:
    """Entry point for the ``wormbase-ingest-transcript`` command.

    Args:
        argv:   Argument list (defaults to ``sys.argv[1:]`` when None).
        ledger: Optional pre-constructed Ledger or InMemoryLedger. When
                supplied (typically from tests), the --dsn flag is parsed
                but ignored. When None, a ``wormbase_ledger.Ledger`` is
                constructed from ``--dsn`` or ``WORMBASE_LEDGER_DSN``.
    """
    parser = argparse.ArgumentParser(
        prog="wormbase-ingest-transcript",
        description="Ingest an SRT meeting transcript into the WormBase ledger.",
    )
    parser.add_argument(
        "--tenant",
        required=True,
        metavar="SLUG",
        help="Tenant slug (e.g. 'altis'). Resolved to a company UUID via uuid5.",
    )
    parser.add_argument(
        "--meeting-id",
        required=True,
        metavar="ID",
        help="Opaque meeting slug. Forms session_id='meeting-<id>' and channel_id='meeting:<id>'.",
    )
    parser.add_argument(
        "--srt",
        required=True,
        metavar="PATH",
        help="Path to the SRT file to ingest.",
    )
    parser.add_argument(
        "--speakers",
        default=None,
        metavar="NAME[,NAME...]",
        help=(
            "Comma-separated list of expected speaker names. "
            "A WARN is emitted to stderr for any speaker not in this set. "
            "If omitted, any speaker is accepted."
        ),
    )
    parser.add_argument(
        "--meeting-date",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Base date to anchor cue timestamps (UTC midnight). "
            "Derived from the SRT header when omitted; defaults to today with WARN."
        ),
    )
    parser.add_argument(
        "--dsn",
        default=None,
        metavar="URL",
        help=(
            "PostgreSQL DSN (SQLAlchemy URL). Reads WORMBASE_LEDGER_DSN env "
            "var when not supplied. Ignored when a 'ledger' object is injected."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and summarize the SRT without writing to the ledger.",
    )

    args = parser.parse_args(argv)

    # --- Tenant resolution ---
    try:
        company_id = _tenant_to_company_uuid(args.tenant)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- Speaker set ---
    speakers: set[str] | None = None
    if args.speakers:
        speakers = {s.strip() for s in args.speakers.split(",") if s.strip()}

    # --- Read SRT file ---
    try:
        with open(args.srt, encoding="utf-8") as fh:
            srt_content = fh.read()
    except OSError as exc:
        print(f"ERROR: cannot read SRT file {args.srt!r}: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- Ledger construction (skipped when injected for testing) ---
    _owned_ledger = False
    if ledger is None:
        if args.dry_run:
            # Dry-run with no injected ledger: use InMemoryLedger as a scratch pad.
            from wormbase_ledger import InMemoryLedger  # noqa: PLC0415
            ledger = InMemoryLedger()
        else:
            dsn = args.dsn or os.environ.get("WORMBASE_LEDGER_DSN")
            if not dsn:
                print(
                    "ERROR: no DSN configured. Supply --dsn or set WORMBASE_LEDGER_DSN.",
                    file=sys.stderr,
                )
                sys.exit(1)
            from wormbase_ledger import Ledger  # noqa: PLC0415
            ledger = Ledger(dsn)
            _owned_ledger = True

    async def _run() -> None:
        try:
            await _ingest(
                ledger,
                company_id=company_id,
                tenant_slug=args.tenant,
                meeting_id=args.meeting_id,
                srt_content=srt_content,
                speakers=speakers,
                base_date_str=args.meeting_date,
                dry_run=args.dry_run,
            )
        finally:
            if _owned_ledger:
                await ledger.dispose()

    asyncio.run(_run())


__all__ = [
    "WORMBASE_TENANT_NAMESPACE",
    "TRANSCRIPT_SPEAKER_NAMESPACE",
    "_tenant_to_company_uuid",
    "speaker_to_person_uuid",
    "SrtCue",
    "Turn",
    "parse_srt",
    "group_turns",
    "ingest_turns",
    "main",
]
