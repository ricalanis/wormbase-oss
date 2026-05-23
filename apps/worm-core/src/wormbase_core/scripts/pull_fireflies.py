"""wormbase-pull-fireflies — pull recent Fireflies.ai transcripts into the WormBase lake.

This is the pragmatic Monday-deploy path. Sprint 2 follow-up: refactor into a
``fireflies.py`` SurfaceDriver in ``packages/lake-surfaces/`` so the agent can
invoke it via MCP tools without a separate CLI.

Usage
-----
::

    $ FIREFLIES_API_KEY=<key> uv run wormbase-pull-fireflies \\
        --tenant altis \\
        --since 2026-05-15 \\
        --limit 20

    found 5 transcripts since 2026-05-15
      altis-wormbase-72b96c65    May 22, 10:35  53 turns   [INGEST]
      altis-internal-standup-89  May 21, 5:12   12 turns   [SKIP — already ingested]
      altis-acme-discovery-...   May 20, 22:00  47 turns   [INGEST]
    ingested 4 new meetings, skipped 1 already-ingested
    total chat_received entries: 156
    ledger seq range: <X>..<X+155>

Flags
-----
--tenant <slug>              (required) — same uuid5 mapping as ledger_recent
--since <YYYY-MM-DD>         (optional, default: 7 days ago) — minimum meeting date
--limit N                    (optional, default 20) — max transcripts to fetch
--api-key <key>              (optional) — overrides FIREFLIES_API_KEY env var
--dsn <url>                  (optional) — same pattern as ingest-transcript
--dry-run                    — fetch + summarize but don't write to ledger
--meeting-id-prefix <prefix> (optional, default: tenant slug) — synthesizes a
                               deterministic meeting_id from <prefix>-<fireflies_id>

Idempotency
-----------
Before ingesting each Fireflies transcript, the script checks whether a
``propose`` ledger entry with the same ``source_meeting_id`` already exists
for the tenant. If so, the meeting is skipped. This makes repeated runs safe:
the same Fireflies state never produces duplicate ledger rows.

Error handling
--------------
- 401 → "FIREFLIES_API_KEY invalid"
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
import urllib.request
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from wormbase_core.scripts.ingest_transcript import (
    WORMBASE_TENANT_NAMESPACE,
    Turn,
    _tenant_to_company_uuid,
    group_turns,
    ingest_turns,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fireflies GraphQL API
# ---------------------------------------------------------------------------

_FIREFLIES_API_URL = "https://api.fireflies.ai/graphql"

_TRANSCRIPTS_QUERY = """
query RecentTranscripts($limit: Int, $fromDate: DateTime) {
  transcripts(limit: $limit, fromDate: $fromDate) {
    id
    title
    date
    duration
    transcript_url
    participants
    sentences {
      speaker_name
      text
      start_time
      end_time
    }
  }
}
"""


def _fetch_transcripts(
    api_key: str,
    *,
    since: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    """Call the Fireflies GraphQL API and return the list of transcript dicts.

    Uses stdlib ``urllib.request`` — no extra deps.

    Raises:
        SystemExit(1): on 401 (invalid key).
        RuntimeError: on 429 after one retry, or other HTTP errors.
        urllib.error.URLError: on network-level errors.
    """
    # Fireflies expects ISO 8601 with a Z suffix.
    from_date_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    body = json.dumps(
        {
            "query": _TRANSCRIPTS_QUERY,
            "variables": {"limit": limit, "fromDate": from_date_str},
        }
    ).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    def _do_request() -> tuple[int, bytes]:
        req = urllib.request.Request(
            _FIREFLIES_API_URL,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    status, raw = _do_request()

    if status == 401:
        print(
            "ERROR: FIREFLIES_API_KEY invalid (HTTP 401). Check your key.",
            file=sys.stderr,
        )
        sys.exit(1)

    if status == 429:
        # Retry once after a brief backoff.
        logger.warning("Fireflies API rate-limited (429). Retrying in 5s …")
        time.sleep(5)
        status, raw = _do_request()
        if status == 429:
            raise RuntimeError(
                "Fireflies API still rate-limited after retry (HTTP 429). Aborting."
            )

    if status != 200:
        raise RuntimeError(
            f"Fireflies API returned HTTP {status}: {raw[:200]!r}"
        )

    data = json.loads(raw)
    if "errors" in data:
        raise RuntimeError(f"Fireflies GraphQL errors: {data['errors']}")

    return data.get("data", {}).get("transcripts") or []


# ---------------------------------------------------------------------------
# Sentence → Turn conversion
# ---------------------------------------------------------------------------

def _sentences_to_turns(
    sentences: list[dict[str, Any]],
    gap_threshold_s: float = 30.0,
) -> list[Turn]:
    """Convert Fireflies sentence-level data into grouped Turn objects.

    Each sentence dict has::

        {
            "speaker_name": str,
            "text": str,
            "start_time": float,  # seconds from start of meeting
            "end_time": float,
        }

    The grouping rules are the same as ``group_turns()`` in ingest_transcript:
    consecutive cues from the same speaker within ``gap_threshold_s`` seconds
    merge into one turn.
    """
    from wormbase_core.scripts.ingest_transcript import SrtCue  # noqa: PLC0415

    if not sentences:
        return []

    # Convert sentences to SrtCue objects (re-using the existing grouping logic).
    cues: list[SrtCue] = []
    for idx, s in enumerate(sentences, start=1):
        start_s = float(s.get("start_time") or 0.0)
        end_s = float(s.get("end_time") or start_s)
        cues.append(
            SrtCue(
                index=idx,
                start_ts=timedelta(seconds=start_s),
                end_ts=timedelta(seconds=end_s),
                speaker=s.get("speaker_name") or "unknown",
                text=(s.get("text") or "").strip(),
            )
        )

    return group_turns(cues, gap_threshold_s=gap_threshold_s)


# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------

async def _is_already_ingested(
    ledger: Any,
    *,
    company_id: UUID,
    meeting_id: str,
) -> bool:
    """Return True if the ledger already contains rows for this meeting_id.

    Checks for a ``propose`` row whose ``execute_payload`` references the
    ``source_meeting_id``. For the InMemoryLedger (and the real DB), we scan
    the execute-kind rows: the execute payload carries ``result_ref`` in the
    form ``transcript-<meeting_id>-0000``.

    Implementation note: we look for an execute row whose ``result_ref``
    starts with ``"transcript-{meeting_id}-"``. This is stable across re-runs
    because ``meeting_id`` is deterministically derived from the Fireflies id.
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

def _parse_meeting_date(date_str: str | None) -> datetime:
    """Parse a Fireflies meeting date string to a UTC datetime.

    Fireflies date field is typically ISO 8601: ``"2026-05-22T10:00:00Z"`` or
    epoch milliseconds as a string. Fallback: UTC midnight today.
    """
    if not date_str:
        return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    # Try ISO 8601 with Z suffix.
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue

    # Try epoch milliseconds.
    try:
        epoch_ms = int(date_str)
        return datetime.fromtimestamp(epoch_ms / 1000.0, tz=UTC)
    except (ValueError, TypeError):
        pass

    logger.warning("Could not parse Fireflies date %r; using UTC midnight today.", date_str)
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
    """Entry point for the ``wormbase-pull-fireflies`` command.

    Args:
        argv:   Argument list (defaults to ``sys.argv[1:]`` when None).
        ledger: Optional pre-constructed Ledger or InMemoryLedger. When
                supplied (typically from tests), the --dsn flag is parsed
                but ignored. When None, a ``wormbase_ledger.Ledger`` is
                constructed from ``--dsn`` or ``WORMBASE_LEDGER_DSN``.
    """
    parser = argparse.ArgumentParser(
        prog="wormbase-pull-fireflies",
        description=(
            "Pull recent Fireflies.ai meeting transcripts into the WormBase ledger."
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
        help="Fetch transcripts from this date onward (default: 7 days ago).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        metavar="N",
        help="Maximum number of transcripts to fetch from Fireflies (default: 20).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        metavar="KEY",
        help="Fireflies API key. Overrides FIREFLIES_API_KEY env var.",
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
        help="Fetch and summarize transcripts without writing to the ledger.",
    )
    parser.add_argument(
        "--meeting-id-prefix",
        default=None,
        metavar="PREFIX",
        help=(
            "Prefix for synthesized meeting_id: '<prefix>-<fireflies_id>'. "
            "Defaults to the tenant slug, producing stable deterministic IDs."
        ),
    )

    args = parser.parse_args(argv)

    # --- API key resolution ---
    api_key = args.api_key or os.environ.get("FIREFLIES_API_KEY")
    if not api_key:
        print(
            "ERROR: no Fireflies API key configured. "
            "Supply --api-key or set FIREFLIES_API_KEY.",
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
    """Fetch Fireflies transcripts and ingest new ones into the ledger."""
    # Fetch from Fireflies (may sys.exit on 401).
    try:
        transcripts = _fetch_transcripts(api_key, since=since_dt, limit=limit)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: network error fetching Fireflies transcripts: {exc}", file=sys.stderr)
        sys.exit(1)

    since_label = since_dt.strftime("%Y-%m-%d")
    print(f"found {len(transcripts)} transcripts since {since_label}")

    ingested_count = 0
    skipped_count = 0
    total_turns = 0

    for transcript in transcripts:
        ff_id = transcript.get("id") or "unknown"
        title = transcript.get("title") or ff_id
        date_str = transcript.get("date")
        sentences = transcript.get("sentences") or []

        meeting_id = f"{prefix}-{ff_id}"
        meeting_dt = _parse_meeting_date(date_str)
        date_label = _format_meeting_date(meeting_dt)

        # Convert sentences → turns.
        turns = _sentences_to_turns(sentences)
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
                proposed_by="pull-fireflies",
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
    "_fetch_transcripts",
    "_sentences_to_turns",
    "_is_already_ingested",
    "ingest_turns",
    "main",
]
