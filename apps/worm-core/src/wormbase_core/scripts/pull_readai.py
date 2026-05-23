"""Pull recent Read.AI meeting transcripts and ingest into the lake.

PRIMARY customer integration for Altis (Poncho's team uses Read.AI). The
companion pull_fireflies.py covers Ricardo's own Fireflies meetings.

This is the pragmatic Monday-deploy path. Sprint 2 follow-up:
refactor into a `readai.py` SurfaceDriver in `packages/lake-surfaces/`
so the agent can invoke it via MCP tools without a separate CLI. The
turn-emission logic already lives in ingest_transcript.ingest_turns,
so the refactor lifts cleanly.

See docs/superpowers/specs/2026-05-23-agent-driven-lake-extension-design.md.

Usage
-----
::

    $ READAI_API_KEY=<key> uv run wormbase-pull-readai \\
        --tenant altis \\
        --since 2026-05-15 \\
        --limit 20

    found 3 meetings since 2026-05-15
      altis-team-standup-abc123    May 22, 30:12   18 turns   [INGEST]
      altis-acme-discovery-def456  May 21, 47:00   42 turns   [SKIP — already ingested]
      altis-internal-ops-ghi789    May 20, 22:14   12 turns   [INGEST]
    ingested 2 new meetings, skipped 1 already-ingested
    total chat_received entries: 30
    ledger seq range: <X>..<X+29>

Flags
-----
--tenant <slug>              (required) — same uuid5 mapping as ledger_recent
--since <YYYY-MM-DD>         (optional, default: 7 days ago) — minimum meeting date
--limit N                    (optional, default 20) — max meetings to fetch
--api-key <key>              (optional) — overrides READAI_API_KEY env var
--dsn <url>                  (optional) — same pattern as ingest-transcript
--dry-run                    — fetch + summarize but don't write to ledger
--meeting-id-prefix <prefix> (optional, default: tenant slug) — synthesizes a
                               deterministic meeting_id from <prefix>-<readai_id>

Read.AI API (verified 2026-05-23 via MCP tool live call)
---------------------------------------------------------
Base URL:  https://api.read.ai
Meetings:  GET /v1/meetings
           Query params:
             expand=transcript          — include transcript.turns
             limit=<N>                  — page size (max 10 per page)
             start_time_gte=<epoch_ms>  — inclusive lower bound
             cursor=<ulid>              — cursor for next page (last id of prev page)
           Response:
             {
               "object": "list",
               "url": "/v1/meetings",
               "has_more": bool,
               "data": [
                 {
                   "id": "<ulid>",          # READAI: confirmed ULID
                   "title": str,
                   "start_time_ms": int,    # epoch ms, absolute
                   "end_time_ms": int,      # epoch ms, absolute
                   "participants": [{"name": str, "email": str, ...}],
                   "transcript": {
                     "speakers": [{"name": str}],
                     "turns": [
                       {
                         "start_time_ms": int,   # absolute epoch ms
                         "end_time_ms": int,      # absolute epoch ms
                         "speaker": {"name": str},
                         "text": str,
                       }
                     ]
                   }
                 }
               ]
             }

IMPORTANT DIFFERENCE from Fireflies
-------------------------------------
Read.AI returns transcript.turns with ABSOLUTE epoch-millisecond timestamps
(same epoch as start_time_ms), NOT relative seconds from meeting start.

ingest_turns() expects a base_dt and per-turn timedeltas (from SrtCue/Turn
internals). We convert absolute epoch ms → timedelta relative to start_time_ms
before calling group_turns() / ingest_turns().

# READAI: start_time_gte / start_time_lte param name unverified from MCP schema
# (MCP tool accepts start_datetime_gte). Actual REST API may differ.
# If the filter silently returns wrong data, check param name against
# https://api.read.ai/docs or try start_time_ms_gte / from_time_ms.

Idempotency
-----------
Before ingesting each Read.AI meeting, the script checks whether an
``execute`` ledger entry whose ``result_ref`` starts with
``"transcript-{meeting_id}-"`` already exists for the tenant.
``meeting_id`` is deterministically derived as ``"{prefix}-{readai_id}"``.

Error handling
--------------
- 401 → "READAI_API_KEY invalid"
- 429 → backoff + retry once
- Network errors → fail the meeting with clear log, continue to the next

Tenant resolution
-----------------
Mirrors ``apps/voice-agent/src/wormbase_voice_agent/app.py`` and
``apps/worm-core/src/wormbase_core/scripts/ingest_transcript.py``.

    namespace = UUID("6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f")
    company_id = uuid5(namespace, slug.strip().lower())
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from wormbase_core.scripts.ingest_transcript import (
    WORMBASE_TENANT_NAMESPACE,
    SrtCue,
    Turn,
    _tenant_to_company_uuid,
    group_turns,
    ingest_turns,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Read.AI REST API
# ---------------------------------------------------------------------------

_READAI_BASE_URL = "https://api.read.ai"
_READAI_MEETINGS_PATH = "/v1/meetings"

# READAI: query-param name for the lower-bound time filter as observed from MCP
# tool schema (start_datetime_gte). The actual REST API docs may use a different
# spelling. Verify at https://api.read.ai/docs if the date filter appears broken.
_READAI_SINCE_PARAM = "start_time_gte"


def _fetch_meetings(
    api_key: str,
    *,
    since: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    """Call the Read.AI REST API and return a list of meeting dicts with transcripts.

    Uses stdlib ``urllib.request`` — no extra deps.

    Paginates automatically until ``limit`` meetings are collected or there are
    no more pages.

    Each returned dict matches the Read.AI meeting shape::

        {
            "id": "<ulid>",
            "title": str,
            "start_time_ms": int,   # epoch ms
            "end_time_ms": int,     # epoch ms
            "participants": [...],
            "transcript": {
                "turns": [
                    {
                        "start_time_ms": int,  # absolute epoch ms
                        "end_time_ms": int,
                        "speaker": {"name": str},
                        "text": str,
                    }
                ]
            }
        }

    Raises:
        SystemExit(1): on 401 (invalid key).
        RuntimeError: on 429 after one retry, or other HTTP errors.
        urllib.error.URLError: on network-level errors.
    """
    since_ms = int(since.timestamp() * 1000)

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    all_meetings: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_meetings) < limit:
        # Build query params.
        page_size = min(10, limit - len(all_meetings))  # Read.AI max is 10/page
        params: dict[str, str] = {
            "expand": "transcript",
            "limit": str(page_size),
            _READAI_SINCE_PARAM: str(since_ms),
        }
        if cursor:
            params["cursor"] = cursor

        query = urllib.parse.urlencode(params)
        url = f"{_READAI_BASE_URL}{_READAI_MEETINGS_PATH}?{query}"

        def _do_request(url: str = url) -> tuple[int, bytes]:
            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()

        status, raw = _do_request()

        if status == 401:
            print(
                "ERROR: READAI_API_KEY invalid (HTTP 401). Check your key.",
                file=sys.stderr,
            )
            sys.exit(1)

        if status == 429:
            logger.warning("Read.AI API rate-limited (429). Retrying in 5s …")
            time.sleep(5)
            status, raw = _do_request()
            if status == 429:
                raise RuntimeError(
                    "Read.AI API still rate-limited after retry (HTTP 429). Aborting."
                )

        if status != 200:
            raise RuntimeError(
                f"Read.AI API returned HTTP {status}: {raw[:200]!r}"
            )

        page = json.loads(raw)
        meetings = page.get("data") or []
        all_meetings.extend(meetings)

        has_more = page.get("has_more", False)
        if not has_more or not meetings:
            break

        # Cursor = ULID of the last meeting in this page.
        cursor = meetings[-1].get("id")
        if not cursor:
            break

    return all_meetings[:limit]


# ---------------------------------------------------------------------------
# Turn conversion — Read.AI turns → grouped Turn objects
# ---------------------------------------------------------------------------

def _readai_turns_to_turns(
    raw_turns: list[dict[str, Any]],
    meeting_start_ms: int,
    gap_threshold_s: float = 30.0,
) -> list[Turn]:
    """Convert Read.AI transcript turns into grouped Turn objects.

    Read.AI already pre-groups utterances into speaker turns (unlike Fireflies
    which provides sentence-level data). However, we still run ``group_turns()``
    to merge consecutive same-speaker turns within ``gap_threshold_s`` seconds,
    which keeps the behaviour consistent with the Fireflies path.

    Each raw turn dict has::

        {
            "start_time_ms": int,   # absolute epoch ms
            "end_time_ms": int,     # absolute epoch ms
            "speaker": {"name": str},
            "text": str,
        }

    Timestamps are ABSOLUTE epoch ms (not relative to meeting start). We
    convert to timedeltas relative to ``meeting_start_ms`` so that
    ``ingest_turns()`` can anchor them correctly to ``base_dt``.
    """
    if not raw_turns:
        return []

    cues: list[SrtCue] = []
    for idx, turn in enumerate(raw_turns, start=1):
        # Absolute epoch ms → timedelta relative to meeting start.
        start_ms = int(turn.get("start_time_ms") or meeting_start_ms)
        end_ms = int(turn.get("end_time_ms") or start_ms)

        # Clamp negative relative times to zero (defensive; shouldn't happen).
        start_rel_s = max(0.0, (start_ms - meeting_start_ms) / 1000.0)
        end_rel_s = max(start_rel_s, (end_ms - meeting_start_ms) / 1000.0)

        speaker_obj = turn.get("speaker") or {}
        speaker_name = (
            speaker_obj.get("name")
            if isinstance(speaker_obj, dict)
            else str(speaker_obj)
        ) or "unknown"

        cues.append(
            SrtCue(
                index=idx,
                start_ts=timedelta(seconds=start_rel_s),
                end_ts=timedelta(seconds=end_rel_s),
                speaker=speaker_name,
                text=(turn.get("text") or "").strip(),
            )
        )

    return group_turns(cues, gap_threshold_s=gap_threshold_s)


# ---------------------------------------------------------------------------
# Idempotency check  (identical pattern to pull_fireflies)
# ---------------------------------------------------------------------------

async def _is_already_ingested(
    ledger: Any,
    *,
    company_id: UUID,
    meeting_id: str,
) -> bool:
    """Return True if the ledger already contains rows for this meeting_id.

    Checks for an execute row whose ``result_ref`` starts with
    ``"transcript-{meeting_id}-"``. Stable across re-runs because
    ``meeting_id`` is deterministically derived from the Read.AI ULID.
    """
    try:
        rows = await ledger.fetch(company_id)
    except Exception:  # noqa: BLE001
        return False

    prefix = f"transcript-{meeting_id}-"
    for row in rows:
        if row.get("kind") != "execute":
            continue
        payload = row.get("payload") or {}
        result_ref = payload.get("result_ref") or ""
        if result_ref.startswith(prefix):
            return True
    return False


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_meeting_date(start_time_ms: int | None) -> datetime:
    """Convert a Read.AI start_time_ms (epoch ms) to a UTC datetime.

    Fallback: UTC midnight today.
    """
    if start_time_ms:
        try:
            return datetime.fromtimestamp(int(start_time_ms) / 1000.0, tz=UTC)
        except (ValueError, TypeError, OSError):
            pass

    logger.warning(
        "Could not parse Read.AI start_time_ms %r; using UTC midnight today.",
        start_time_ms,
    )
    return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _format_meeting_date(dt: datetime) -> str:
    """Format a meeting datetime for the summary line: ``May 22, 10:35``."""
    return dt.strftime("%b %d, %H:%M")


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main(
    argv: list[str] | None = None,
    *,
    ledger: Any = None,
) -> None:
    """Entry point for the ``wormbase-pull-readai`` command.

    Args:
        argv:   Argument list (defaults to ``sys.argv[1:]`` when None).
        ledger: Optional pre-constructed Ledger or InMemoryLedger. When
                supplied (typically from tests), the --dsn flag is parsed
                but ignored. When None, a ``wormbase_ledger.Ledger`` is
                constructed from ``--dsn`` or ``WORMBASE_LEDGER_DSN``.
    """
    parser = argparse.ArgumentParser(
        prog="wormbase-pull-readai",
        description=(
            "Pull recent Read.AI meeting transcripts into the WormBase ledger. "
            "PRIMARY integration for Altis (customer-facing). "
            "Auth: READAI_API_KEY env var or --api-key flag."
        ),
    )
    parser.add_argument(
        "--tenant",
        required=True,
        metavar="SLUG",
        help="Tenant slug (e.g. 'altis'). Resolved to a company UUID via uuid5.",
    )
    parser.add_argument(
        "--since",
        default=None,
        metavar="YYYY-MM-DD",
        help="Fetch meetings from this date onward (default: 7 days ago).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        metavar="N",
        help="Maximum number of meetings to fetch from Read.AI (default: 20).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        metavar="KEY",
        help="Read.AI API key. Overrides READAI_API_KEY env var.",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        metavar="URL",
        help=(
            "PostgreSQL DSN (SQLAlchemy URL). Reads WORMBASE_LEDGER_DSN env var "
            "when not supplied. Ignored when a 'ledger' object is injected."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and summarize meetings without writing to the ledger.",
    )
    parser.add_argument(
        "--meeting-id-prefix",
        default=None,
        metavar="PREFIX",
        help=(
            "Prefix for synthesized meeting_id: '<prefix>-<readai_id>'. "
            "Defaults to the tenant slug, producing stable deterministic IDs."
        ),
    )

    args = parser.parse_args(argv)

    # --- API key resolution ---
    api_key = args.api_key or os.environ.get("READAI_API_KEY")
    if not api_key:
        print(
            "ERROR: no Read.AI API key configured. "
            "Supply --api-key or set READAI_API_KEY.",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Tenant resolution ---
    try:
        company_id = _tenant_to_company_uuid(args.tenant)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- Since date ---
    if args.since:
        try:
            since_date = date.fromisoformat(args.since)
            since_dt = datetime(since_date.year, since_date.month, since_date.day, tzinfo=UTC)
        except ValueError:
            print(
                f"ERROR: --since {args.since!r} is not a valid YYYY-MM-DD date.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        since_dt = datetime.now(UTC) - timedelta(days=7)

    # --- Meeting ID prefix ---
    prefix = args.meeting_id_prefix or args.tenant

    # --- Ledger construction (skipped when injected for testing) ---
    _owned_ledger = False
    if ledger is None:
        if args.dry_run:
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
            await _pull(
                ledger,
                api_key=api_key,
                company_id=company_id,
                tenant_slug=args.tenant,
                since_dt=since_dt,
                limit=args.limit,
                prefix=prefix,
                dry_run=args.dry_run,
            )
        finally:
            if _owned_ledger:
                await ledger.dispose()

    asyncio.run(_run())


async def _pull(
    ledger: Any,
    *,
    api_key: str,
    company_id: UUID,
    tenant_slug: str,
    since_dt: datetime,
    limit: int,
    prefix: str,
    dry_run: bool,
) -> None:
    """Fetch Read.AI meetings and ingest new ones into the ledger."""
    # Fetch from Read.AI (may sys.exit on 401).
    try:
        meetings = _fetch_meetings(api_key, since=since_dt, limit=limit)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: network error fetching Read.AI meetings: {exc}", file=sys.stderr)
        sys.exit(1)

    since_label = since_dt.strftime("%Y-%m-%d")
    print(f"found {len(meetings)} meetings since {since_label}")

    ingested_count = 0
    skipped_count = 0
    total_turns = 0

    for meeting in meetings:
        ra_id = meeting.get("id") or "unknown"
        title = meeting.get("title") or ra_id
        start_time_ms = meeting.get("start_time_ms")
        transcript_obj = meeting.get("transcript") or {}
        raw_turns = transcript_obj.get("turns") or []

        meeting_id = f"{prefix}-{ra_id}"
        meeting_dt = _parse_meeting_date(start_time_ms)
        date_label = _format_meeting_date(meeting_dt)

        # Convert Read.AI turns → grouped Turn objects.
        # READAI: turns already pre-grouped by speaker; group_turns() may merge
        # consecutive same-speaker turns that are within 30s (e.g. short pauses).
        turns = _readai_turns_to_turns(
            raw_turns,
            meeting_start_ms=int(start_time_ms or 0),
        )
        n_turns = len(turns)

        # Idempotency check.
        already_done = await _is_already_ingested(
            ledger, company_id=company_id, meeting_id=meeting_id
        )

        if already_done:
            print(f"  {meeting_id:<40} {date_label}  {n_turns:>3} turns   [SKIP — already ingested]")
            skipped_count += 1
            continue

        if dry_run:
            print(f"  {meeting_id:<40} {date_label}  {n_turns:>3} turns   [DRY-RUN — would ingest]")
            ingested_count += 1
            total_turns += n_turns
            continue

        # Ingest via shared helper.
        try:
            await ingest_turns(
                ledger,
                company_id=company_id,
                meeting_id=meeting_id,
                base_dt=meeting_dt,
                turns=turns,
                proposed_by="pull-readai",
            )
            print(f"  {meeting_id:<40} {date_label}  {n_turns:>3} turns   [INGEST]")
            ingested_count += 1
            total_turns += n_turns
        except Exception as exc:  # noqa: BLE001
            print(
                f"  {meeting_id:<40} {date_label}  {n_turns:>3} turns   [ERROR: {exc}]",
                file=sys.stderr,
            )

    # Summary line.
    meeting_word = "meeting" if ingested_count == 1 else "meetings"
    if dry_run:
        print(
            f"dry-run: would ingest {ingested_count} new {meeting_word}, "
            f"skip {skipped_count} already-ingested"
        )
    else:
        print(
            f"ingested {ingested_count} new {meeting_word}, "
            f"skipped {skipped_count} already-ingested"
        )
        print(f"total chat_received entries: {total_turns}")

    # Seq range (informational).
    if not dry_run and total_turns > 0:
        try:
            rows = await ledger.fetch(company_id)
            if rows:
                first_seq = rows[0].get("seq")
                last_seq = rows[-1].get("seq")
                print(f"ledger seq range: {first_seq}..{last_seq}")
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "WORMBASE_TENANT_NAMESPACE",
    "_fetch_meetings",
    "_readai_turns_to_turns",
    "_is_already_ingested",
    "ingest_turns",
    "main",
]
