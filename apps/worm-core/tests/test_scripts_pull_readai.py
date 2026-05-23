"""Tests for wormbase_core.scripts.pull_readai — wormbase-pull-readai CLI.

Test cases:
1. Mock Read.AI response    — 2-meeting canned response; assert 2 meetings ingested,
   correct turn counts written to InMemoryLedger.
2. Idempotency              — pre-seed ledger with one meeting; run pull-readai;
   assert that meeting is SKIPPED, the other is INGESTED.
3. --dry-run               — mock returns meetings; assert 0 ledger writes; summary printed.
4. --api-key error         — no env var, no --api-key flag; assert clear error + sys.exit(1).
5. Turn extraction         — 3 speakers in mock turns; assert grouping merges consecutive
   same-speaker turns within 30s and splits across gap / speaker change.
6. --meeting-id-prefix     — controls result_ref prefix stored in ledger.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

import pytest

from wormbase_ledger import InMemoryLedger

from wormbase_core.scripts.pull_readai import (
    WORMBASE_TENANT_NAMESPACE,
    _readai_turns_to_turns,
    _is_already_ingested,
    _fetch_meetings,
    ingest_turns,
    main,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALTIS_COMPANY_ID = uuid5(UUID(WORMBASE_TENANT_NAMESPACE), "altis")

# ---------------------------------------------------------------------------
# Epoch-ms helpers
# The Read.AI API uses absolute epoch-millisecond timestamps for both the
# meeting start and the individual transcript turns.
# ---------------------------------------------------------------------------

# Base epoch for test meetings (2026-05-22T10:00:00Z in ms).
_BASE_EPOCH_MS = int(datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC).timestamp() * 1000)
_BASE_EPOCH_MS_B = int(datetime(2026, 5, 21, 9, 0, 0, tzinfo=UTC).timestamp() * 1000)

_MEETING_A_ID = "01KS8D1YYP936T5PMW8W33P7BR"
_MEETING_B_ID = "01KS84G305T9F89H9BBAG3Z294"

# Meeting A: 4 turns.
# Turns 0+1 are Alice within 30s → merge.  Turn 2 is Bob.  Turn 3 is Alice.
# Expected: 3 grouped turns (Alice/merged, Bob, Alice).
_TURNS_A = [
    {
        "start_time_ms": _BASE_EPOCH_MS + 0,
        "end_time_ms": _BASE_EPOCH_MS + 2000,
        "speaker": {"name": "Alice"},
        "text": "Hello everyone.",
    },
    {
        "start_time_ms": _BASE_EPOCH_MS + 3000,
        "end_time_ms": _BASE_EPOCH_MS + 5000,
        "speaker": {"name": "Alice"},
        "text": "Thanks for joining.",
    },
    {
        "start_time_ms": _BASE_EPOCH_MS + 6000,
        "end_time_ms": _BASE_EPOCH_MS + 9000,
        "speaker": {"name": "Bob"},
        "text": "Happy to be here.",
    },
    {
        "start_time_ms": _BASE_EPOCH_MS + 10000,
        "end_time_ms": _BASE_EPOCH_MS + 13000,
        "speaker": {"name": "Alice"},
        "text": "Great. Let's start.",
    },
]

# Meeting B: 2 turns from Carol, within 30s → merge to 1 grouped turn.
_TURNS_B = [
    {
        "start_time_ms": _BASE_EPOCH_MS_B + 0,
        "end_time_ms": _BASE_EPOCH_MS_B + 3000,
        "speaker": {"name": "Carol"},
        "text": "This is a short meeting.",
    },
    {
        "start_time_ms": _BASE_EPOCH_MS_B + 5000,
        "end_time_ms": _BASE_EPOCH_MS_B + 7000,
        "speaker": {"name": "Carol"},
        "text": "Wrap it up.",
    },
]


def _make_meeting(
    mid: str,
    title: str,
    start_epoch_ms: int,
    raw_turns: list[dict],
) -> dict:
    """Build a canned Read.AI meeting dict matching the REST API shape."""
    return {
        "id": mid,
        "title": title,
        "start_time_ms": start_epoch_ms,
        "end_time_ms": start_epoch_ms + 600_000,
        "participants": [{"name": "Alice", "email": "alice@example.com", "attended": True}],
        "transcript": {
            "speakers": [{"name": "Alice"}, {"name": "Bob"}, {"name": "Carol"}],
            "turns": raw_turns,
        },
    }


_TWO_MEETING_RESPONSE = [
    _make_meeting(_MEETING_A_ID, "Altis: Product Review", _BASE_EPOCH_MS, _TURNS_A),
    _make_meeting(_MEETING_B_ID, "Altis: Standup", _BASE_EPOCH_MS_B, _TURNS_B),
]


# ---------------------------------------------------------------------------
# Helper: monkey-patch _fetch_meetings
# ---------------------------------------------------------------------------

def _patch_fetcher(monkeypatch, meetings: list[dict]) -> None:
    """Replace _fetch_meetings in the pull_readai module with a stub."""
    import wormbase_core.scripts.pull_readai as mod

    def _fake_fetch(api_key: str, *, since: datetime, limit: int) -> list[dict]:  # noqa: ARG001
        return meetings

    monkeypatch.setattr(mod, "_fetch_meetings", _fake_fetch)


# ---------------------------------------------------------------------------
# Test 1: Mock Read.AI response — 2 meetings ingested, correct turn counts
# ---------------------------------------------------------------------------


def test_two_meetings_ingested(monkeypatch, capsys) -> None:
    """Two-meeting mock response → both ingested; ledger rows match expected turn counts."""
    _patch_fetcher(monkeypatch, _TWO_MEETING_RESPONSE)
    ledger = InMemoryLedger()

    main(
        argv=[
            "--tenant", "altis",
            "--api-key", "fake-key",
            "--since", "2026-05-20",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    rows = asyncio.run(ledger.fetch(ALTIS_COMPANY_ID))
    propose_rows = [r for r in rows if r.get("kind") == "propose"]

    # Meeting A: 4 raw turns → 3 grouped (Alice merged, Bob, Alice)
    # Meeting B: 2 raw turns → 1 grouped (Carol merged)
    # Total: 4 turns × 4 PEVR rows each = 16 rows.
    assert len(propose_rows) == 4, f"expected 4 propose rows, got {len(propose_rows)}"

    # All targets should be chat_received.
    for r in propose_rows:
        assert r["payload"]["target_kind"] == "chat_received"

    out = capsys.readouterr().out
    assert "ingested 2 new meetings" in out
    assert "skipped 0" in out


# ---------------------------------------------------------------------------
# Test 2: Idempotency — pre-seed one meeting; it must be SKIPPED
# ---------------------------------------------------------------------------


def test_idempotency_skip_already_ingested(monkeypatch, capsys) -> None:
    """Pre-seed Meeting B → run → Meeting B SKIPPED, Meeting A INGESTED."""
    _patch_fetcher(monkeypatch, _TWO_MEETING_RESPONSE)
    ledger = InMemoryLedger()

    # Pre-seed Meeting B via the shared ingest_turns helper.
    from wormbase_core.scripts.ingest_transcript import _tenant_to_company_uuid

    company_id = _tenant_to_company_uuid("altis")
    meeting_id_b = f"altis-{_MEETING_B_ID}"
    base_dt = datetime(2026, 5, 21, 9, 0, 0, tzinfo=UTC)
    turns_b = _readai_turns_to_turns(_TURNS_B, meeting_start_ms=_BASE_EPOCH_MS_B)

    asyncio.run(
        ingest_turns(
            ledger,
            company_id=company_id,
            meeting_id=meeting_id_b,
            base_dt=base_dt,
            turns=turns_b,
        )
    )

    # Pre-seed: Meeting B 1 grouped turn → 4 PEVR rows.
    rows_before = asyncio.run(ledger.fetch(company_id))
    assert len(rows_before) == 4

    # Run the CLI.
    main(
        argv=[
            "--tenant", "altis",
            "--api-key", "fake-key",
            "--since", "2026-05-20",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    rows_after = asyncio.run(ledger.fetch(company_id))
    propose_after = [r for r in rows_after if r.get("kind") == "propose"]

    # Total propose rows: 1 (pre-seed) + 3 (meeting A) = 4.
    assert len(propose_after) == 4, (
        f"expected 4 total propose rows (1 pre-seed + 3 from meeting A), got {len(propose_after)}"
    )

    out = capsys.readouterr().out
    assert "SKIP" in out
    assert "already ingested" in out
    assert "ingested 1 new meeting" in out


# ---------------------------------------------------------------------------
# Test 3: --dry-run → no ledger writes; summary printed
# ---------------------------------------------------------------------------


def test_dry_run_no_ledger_writes(monkeypatch, capsys) -> None:
    """--dry-run: fetch + summarize but write nothing to ledger."""
    _patch_fetcher(monkeypatch, _TWO_MEETING_RESPONSE)
    ledger = InMemoryLedger()

    main(
        argv=[
            "--tenant", "altis",
            "--api-key", "fake-key",
            "--since", "2026-05-20",
            "--dry-run",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    rows = asyncio.run(ledger.fetch(ALTIS_COMPANY_ID))
    assert len(rows) == 0, f"expected 0 rows in dry-run, got {len(rows)}"

    out = capsys.readouterr().out
    assert "dry-run" in out.lower()
    assert "found 2 meetings" in out


# ---------------------------------------------------------------------------
# Test 4: Missing API key → exit 1 + clear error
# ---------------------------------------------------------------------------


def test_missing_api_key_exits_with_error(monkeypatch, capsys) -> None:
    """No READAI_API_KEY env + no --api-key → error message + exit 1."""
    monkeypatch.delenv("READAI_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main(
            argv=[
                "--tenant", "altis",
                "--since", "2026-05-20",
                "--dsn", "ignored",
            ],
            ledger=InMemoryLedger(),
        )

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "READAI_API_KEY" in err


# ---------------------------------------------------------------------------
# Test 5: Turn extraction — grouping logic
# ---------------------------------------------------------------------------


def test_readai_turns_merges_same_speaker_within_30s() -> None:
    """Consecutive same-speaker turns within 30s merge to one Turn."""
    base_ms = _BASE_EPOCH_MS
    raw = [
        {"start_time_ms": base_ms + 0,     "end_time_ms": base_ms + 2000,  "speaker": {"name": "Alice"}, "text": "one"},
        {"start_time_ms": base_ms + 5000,  "end_time_ms": base_ms + 7000,  "speaker": {"name": "Alice"}, "text": "two"},
        {"start_time_ms": base_ms + 10000, "end_time_ms": base_ms + 12000, "speaker": {"name": "Alice"}, "text": "three"},
    ]
    turns = _readai_turns_to_turns(raw, meeting_start_ms=base_ms)
    assert len(turns) == 1
    assert turns[0].speaker == "Alice"
    assert "one" in turns[0].text
    assert "three" in turns[0].text


def test_readai_turns_splits_on_speaker_change() -> None:
    """Different speaker always starts a new Turn."""
    base_ms = _BASE_EPOCH_MS
    raw = [
        {"start_time_ms": base_ms + 0,    "end_time_ms": base_ms + 2000, "speaker": {"name": "Alice"}, "text": "hello"},
        {"start_time_ms": base_ms + 3000, "end_time_ms": base_ms + 5000, "speaker": {"name": "Bob"},   "text": "world"},
        {"start_time_ms": base_ms + 6000, "end_time_ms": base_ms + 8000, "speaker": {"name": "Alice"}, "text": "back"},
    ]
    turns = _readai_turns_to_turns(raw, meeting_start_ms=base_ms)
    assert len(turns) == 3
    assert turns[0].speaker == "Alice"
    assert turns[1].speaker == "Bob"
    assert turns[2].speaker == "Alice"


def test_readai_turns_splits_on_large_gap() -> None:
    """Same speaker but >30s gap starts a new Turn."""
    base_ms = _BASE_EPOCH_MS
    raw = [
        {"start_time_ms": base_ms + 0,      "end_time_ms": base_ms + 5000,  "speaker": {"name": "Alice"}, "text": "early"},
        {"start_time_ms": base_ms + 60_000, "end_time_ms": base_ms + 65_000, "speaker": {"name": "Alice"}, "text": "late"},
    ]
    turns = _readai_turns_to_turns(raw, meeting_start_ms=base_ms)
    assert len(turns) == 2
    assert turns[0].text == "early"
    assert turns[1].text == "late"


def test_readai_turns_three_speakers_complex() -> None:
    """3-speaker interleaved turns produce correct Turn sequence."""
    turns = _readai_turns_to_turns(_TURNS_A, meeting_start_ms=_BASE_EPOCH_MS)
    assert len(turns) == 3
    assert turns[0].speaker == "Alice"
    assert "Hello everyone." in turns[0].text
    assert "Thanks for joining." in turns[0].text
    assert turns[1].speaker == "Bob"
    assert turns[2].speaker == "Alice"
    assert "Let's start" in turns[2].text


def test_readai_turns_empty() -> None:
    """Empty turn list produces no Turns."""
    turns = _readai_turns_to_turns([], meeting_start_ms=_BASE_EPOCH_MS)
    assert turns == []


def test_readai_turns_relative_timestamps_correct() -> None:
    """Turn timestamps relative to meeting start are calculated correctly."""
    base_ms = _BASE_EPOCH_MS
    # Turn starts 10s into the meeting.
    raw = [
        {
            "start_time_ms": base_ms + 10_000,
            "end_time_ms": base_ms + 15_000,
            "speaker": {"name": "Alice"},
            "text": "ten seconds in",
        }
    ]
    turns = _readai_turns_to_turns(raw, meeting_start_ms=base_ms)
    assert len(turns) == 1
    assert abs(turns[0].start_ts.total_seconds() - 10.0) < 0.01


def test_readai_turns_unknown_speaker_handled() -> None:
    """UNKNOWN_SPEAKER (as seen in real Read.AI data) is handled gracefully."""
    base_ms = _BASE_EPOCH_MS
    raw = [
        {
            "start_time_ms": base_ms,
            "end_time_ms": base_ms + 3000,
            "speaker": {"name": "UNKNOWN_SPEAKER"},
            "text": "who said this",
        }
    ]
    turns = _readai_turns_to_turns(raw, meeting_start_ms=base_ms)
    assert len(turns) == 1
    assert turns[0].speaker == "UNKNOWN_SPEAKER"


# ---------------------------------------------------------------------------
# Test: _is_already_ingested
# ---------------------------------------------------------------------------


def test_is_already_ingested_false_when_empty() -> None:
    """Empty ledger → not already ingested."""
    ledger = InMemoryLedger()
    result = asyncio.run(
        _is_already_ingested(ledger, company_id=ALTIS_COMPANY_ID, meeting_id="altis-ra-new")
    )
    assert result is False


def test_is_already_ingested_true_after_seed() -> None:
    """After seeding a meeting, _is_already_ingested returns True."""
    ledger = InMemoryLedger()
    meeting_id = "altis-ra-seeded-meet"
    base_dt = datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC)
    base_ms = int(base_dt.timestamp() * 1000)
    raw = [
        {
            "start_time_ms": base_ms,
            "end_time_ms": base_ms + 1000,
            "speaker": {"name": "Alice"},
            "text": "hi",
        }
    ]
    turns = _readai_turns_to_turns(raw, meeting_start_ms=base_ms)

    asyncio.run(
        ingest_turns(
            ledger,
            company_id=ALTIS_COMPANY_ID,
            meeting_id=meeting_id,
            base_dt=base_dt,
            turns=turns,
        )
    )

    result = asyncio.run(
        _is_already_ingested(ledger, company_id=ALTIS_COMPANY_ID, meeting_id=meeting_id)
    )
    assert result is True


# ---------------------------------------------------------------------------
# Test 6: --meeting-id-prefix controls result_ref prefix
# ---------------------------------------------------------------------------


def test_meeting_id_prefix_flag(monkeypatch, capsys) -> None:
    """--meeting-id-prefix controls synthesized meeting_id = <prefix>-<readai_id>."""
    _patch_fetcher(monkeypatch, [_TWO_MEETING_RESPONSE[0]])  # only meeting A
    ledger = InMemoryLedger()

    main(
        argv=[
            "--tenant", "altis",
            "--api-key", "fake-key",
            "--since", "2026-05-20",
            "--meeting-id-prefix", "myprefix",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    rows = asyncio.run(ledger.fetch(ALTIS_COMPANY_ID))
    execute_rows = [r for r in rows if r.get("kind") == "execute"]

    expected_prefix = f"transcript-myprefix-{_MEETING_A_ID}-"
    for r in execute_rows:
        result_ref = r["payload"]["result_ref"]
        assert result_ref.startswith("transcript-myprefix-"), (
            f"result_ref {result_ref!r} does not start with 'transcript-myprefix-'"
        )
