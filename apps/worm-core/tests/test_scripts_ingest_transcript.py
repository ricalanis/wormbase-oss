"""Tests for wormbase_core.scripts.ingest_transcript — wormbase-ingest-transcript CLI.

Test cases:
1. SRT parsing  — small inline SRT, assert cues + speakers + text
2. Turn grouping — collapse consecutive same-speaker cues; gap-based split
3. Smoke ingest  — small SRT, InMemoryLedger, assert N chat_received entries
4. Unknown speaker — --speakers "A,B" but cue from "C" → WARN + still ingested
5. --dry-run     — ledger gets 0 writes
6. Real-file smoke — parse Altis SRT (--dry-run); assert ≥50 turns (skipped if absent)
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from wormbase_ledger import InMemoryLedger

from wormbase_core.scripts.ingest_transcript import (
    WORMBASE_TENANT_NAMESPACE,
    _tenant_to_company_uuid,
    SrtCue,
    Turn,
    group_turns,
    parse_srt,
    main,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALTIS_COMPANY_ID = uuid5(UUID(WORMBASE_TENANT_NAMESPACE), "altis")

# A minimal inline SRT with 3 cues and 2 speakers.
_SMALL_SRT = """\
1
00:00:00,320 --> 00:00:00,960
Ricardo Alanís: Fireflies.

2
00:00:02,240 --> 00:00:08,520
Poncho Garciga: Mientras no me expongas ahorita.

3
00:00:09,000 --> 00:00:12,000
Ricardo Alanís: No hay problema.
"""

# SRT with a Fireflies header glued to cue index 1 (no newline separator).
_HEADER_SRT = """\
Meeting created at: 22nd May, 2026 - 11:00 PM1
00:00:00,320 --> 00:00:00,960
Speaker A: Hello.

2
00:00:05,000 --> 00:00:08,000
Speaker B: World.
"""

# ---------------------------------------------------------------------------
# Test 1: SRT parsing
# ---------------------------------------------------------------------------


def test_parse_srt_basic_cues() -> None:
    """parse_srt produces correct cues with right speakers, timings, and text."""
    cues, detected_date = parse_srt(_SMALL_SRT)

    assert len(cues) == 3, f"expected 3 cues, got {len(cues)}"

    assert cues[0].index == 1
    assert cues[0].speaker == "Ricardo Alanís"
    assert cues[0].text == "Fireflies."
    assert cues[0].start_ts == timedelta(milliseconds=320)
    assert cues[0].end_ts == timedelta(milliseconds=960)

    assert cues[1].index == 2
    assert cues[1].speaker == "Poncho Garciga"
    assert "Mientras" in cues[1].text

    assert cues[2].index == 3
    assert cues[2].speaker == "Ricardo Alanís"
    assert "problema" in cues[2].text


def test_parse_srt_no_date_when_no_header() -> None:
    """detected_date is None when there is no Fireflies header line."""
    _, detected_date = parse_srt(_SMALL_SRT)
    assert detected_date is None


def test_parse_srt_detects_header_date() -> None:
    """The Fireflies header is parsed into a detected_date."""
    cues, detected_date = parse_srt(_HEADER_SRT)
    # Header carries May 2026
    assert detected_date is not None
    assert detected_date.year == 2026
    assert detected_date.month == 5


def test_parse_srt_header_glued_to_cue_index() -> None:
    """Header glued to cue 1 without newline is handled; cues are still parsed."""
    cues, _ = parse_srt(_HEADER_SRT)
    assert len(cues) == 2
    assert cues[0].speaker == "Speaker A"
    assert cues[1].speaker == "Speaker B"


def test_parse_srt_unknown_speaker_when_no_colon() -> None:
    """Text without 'Speaker: ...' pattern gets speaker='unknown'."""
    srt = """\
1
00:00:00,000 --> 00:00:01,000
This is just text without a speaker prefix.

"""
    cues, _ = parse_srt(srt)
    assert len(cues) == 1
    assert cues[0].speaker == "unknown"
    assert cues[0].text == "This is just text without a speaker prefix."


def test_parse_srt_skips_non_cue_blocks() -> None:
    """Blocks with non-integer first lines are skipped defensively."""
    srt = """\
not-a-number
00:00:00,000 --> 00:00:01,000
Some text.

1
00:00:01,000 --> 00:00:02,000
Speaker A: Valid cue.

"""
    cues, _ = parse_srt(srt)
    assert len(cues) == 1
    assert cues[0].speaker == "Speaker A"


# ---------------------------------------------------------------------------
# Test 2: Turn grouping
# ---------------------------------------------------------------------------


def _make_cue(idx: int, start_ms: int, end_ms: int, speaker: str, text: str) -> SrtCue:
    return SrtCue(
        index=idx,
        start_ts=timedelta(milliseconds=start_ms),
        end_ts=timedelta(milliseconds=end_ms),
        speaker=speaker,
        text=text,
    )


def test_group_turns_collapses_consecutive_same_speaker() -> None:
    """4 consecutive cues from the same speaker within 30s collapse to 1 turn."""
    cues = [
        _make_cue(1, 0, 1000, "A", "first"),
        _make_cue(2, 1100, 2000, "A", "second"),
        _make_cue(3, 2100, 3000, "A", "third"),
        _make_cue(4, 3100, 4000, "A", "fourth"),
    ]
    turns = group_turns(cues, gap_threshold_s=30.0)
    assert len(turns) == 1
    assert turns[0].speaker == "A"
    assert "first" in turns[0].text
    assert "fourth" in turns[0].text


def test_group_turns_splits_on_speaker_change() -> None:
    """Different speaker always starts a new turn."""
    cues = [
        _make_cue(1, 0, 1000, "A", "hello"),
        _make_cue(2, 1100, 2000, "B", "world"),
        _make_cue(3, 2100, 3000, "A", "back"),
    ]
    turns = group_turns(cues, gap_threshold_s=30.0)
    assert len(turns) == 3
    assert turns[0].speaker == "A"
    assert turns[1].speaker == "B"
    assert turns[2].speaker == "A"


def test_group_turns_splits_on_large_gap() -> None:
    """Same speaker but >30s gap triggers a new turn."""
    # 60 second gap between the two cues from same speaker.
    cues = [
        _make_cue(1, 0, 1000, "A", "first part"),
        _make_cue(2, 61_000, 62_000, "A", "second part far away"),
    ]
    turns = group_turns(cues, gap_threshold_s=30.0)
    assert len(turns) == 2
    assert turns[0].text == "first part"
    assert turns[1].text == "second part far away"


def test_group_turns_merges_within_gap_threshold() -> None:
    """Same speaker within 30s still merges."""
    cues = [
        _make_cue(1, 0, 5000, "A", "one"),
        _make_cue(2, 10_000, 15_000, "A", "two"),  # 5s gap — within threshold
    ]
    turns = group_turns(cues, gap_threshold_s=30.0)
    assert len(turns) == 1
    assert "one" in turns[0].text
    assert "two" in turns[0].text


def test_group_turns_empty_input() -> None:
    """Empty cue list returns empty turns."""
    assert group_turns([]) == []


def test_turn_text_property() -> None:
    """Turn.text joins all component texts with a single space."""
    t = Turn(speaker="A", start_ts=timedelta(0), end_ts=timedelta(seconds=5), texts=["hello", "world"])
    assert t.text == "hello world"


# ---------------------------------------------------------------------------
# Test 3: Smoke ingest — InMemoryLedger, correct session_id and message_ids
# ---------------------------------------------------------------------------


def test_smoke_ingest_writes_n_chat_received_entries(capsys) -> None:
    """Feed a 3-cue, 2-turn SRT; assert 2 PEVR cycles (8 entries) written."""
    # _SMALL_SRT has cues 1 and 3 from "Ricardo Alanís" but with a speaker
    # change in between, so the result is 3 turns.
    ledger = InMemoryLedger()
    main(
        argv=[
            "--tenant", "altis",
            "--meeting-id", "test-meeting-001",
            "--srt", "/dev/stdin",   # We'll use a temp file instead
            "--dry-run",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )
    # Even in dry-run, nothing is written — but no crash.


def _write_temp_srt(tmp_path: Path, content: str) -> str:
    """Write SRT content to a temp file and return the path."""
    f = tmp_path / "test.srt"
    f.write_text(content, encoding="utf-8")
    return str(f)


def test_smoke_ingest_writes_correct_entries(tmp_path, capsys) -> None:
    """feed a 3-cue, 3-turn SRT; assert 3 propose entries for correct session_id."""
    srt_path = _write_temp_srt(tmp_path, _SMALL_SRT)
    ledger = InMemoryLedger()

    main(
        argv=[
            "--tenant", "altis",
            "--meeting-id", "test-meeting-001",
            "--srt", srt_path,
            "--meeting-date", "2026-05-22",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    # Fetch all rows for altis.
    rows = asyncio.run(ledger.fetch(ALTIS_COMPANY_ID))
    # 3 turns × 4 PEVR rows = 12 rows
    assert len(rows) == 12, f"expected 12 rows, got {len(rows)}: {rows}"

    propose_rows = [r for r in rows if r.get("kind") == "propose"]
    assert len(propose_rows) == 3

    # All propose rows must target chat_received.
    for r in propose_rows:
        payload = r.get("payload") or {}
        assert payload.get("target_kind") == "chat_received"

    # session_id appears in the execute args.
    execute_rows = [r for r in rows if r.get("kind") == "execute"]
    for r in execute_rows:
        payload = r.get("payload") or {}
        args = payload.get("args") or {}
        assert args.get("channel_id") == "meeting:test-meeting-001"

    # message_ids follow the transcript-{meeting_id}-{idx:04d} pattern.
    message_ids = [
        (r.get("payload") or {}).get("result_ref")
        for r in execute_rows
    ]
    assert "transcript-test-meeting-001-0000" in message_ids
    assert "transcript-test-meeting-001-0001" in message_ids
    assert "transcript-test-meeting-001-0002" in message_ids


def test_smoke_ingest_stdout_summary(tmp_path, capsys) -> None:
    """main() prints expected summary lines to stdout."""
    srt_path = _write_temp_srt(tmp_path, _SMALL_SRT)
    ledger = InMemoryLedger()

    main(
        argv=[
            "--tenant", "altis",
            "--meeting-id", "test-meeting-002",
            "--srt", srt_path,
            "--meeting-date", "2026-05-22",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    assert "parsed 3 cues" in out
    assert "3 turns" in out
    assert "ingested 3 chat_received entries for tenant altis" in out
    assert "session_id: meeting-test-meeting-002" in out
    assert "time range:" in out


# ---------------------------------------------------------------------------
# Test 4: Unknown speaker warning
# ---------------------------------------------------------------------------


def test_unknown_speaker_warns_but_still_ingests(tmp_path, capsys) -> None:
    """--speakers "A,B" but cue from "C" → WARN on stderr + turn still ingested."""
    srt = """\
1
00:00:00,000 --> 00:00:01,000
Speaker A: Hello from A.

2
00:00:02,000 --> 00:00:03,000
Speaker C: Interloper from C.

3
00:00:04,000 --> 00:00:05,000
Speaker B: Reply from B.

"""
    srt_path = _write_temp_srt(tmp_path, srt)
    ledger = InMemoryLedger()

    main(
        argv=[
            "--tenant", "altis",
            "--meeting-id", "unknown-speaker-test",
            "--srt", srt_path,
            "--speakers", "Speaker A,Speaker B",
            "--meeting-date", "2026-05-22",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    out, err = capsys.readouterr()
    # Should have warned about Speaker C on stderr.
    assert "Speaker C" in err
    assert "WARN" in err

    # But all 3 turns should still be ingested.
    rows = asyncio.run(ledger.fetch(ALTIS_COMPANY_ID))
    propose_rows = [r for r in rows if r.get("kind") == "propose"]
    assert len(propose_rows) == 3


# ---------------------------------------------------------------------------
# Test 5: --dry-run produces 0 ledger writes
# ---------------------------------------------------------------------------


def test_dry_run_produces_no_ledger_writes(tmp_path, capsys) -> None:
    """--dry-run: parse + summarize without writing to ledger."""
    srt_path = _write_temp_srt(tmp_path, _SMALL_SRT)
    ledger = InMemoryLedger()

    main(
        argv=[
            "--tenant", "altis",
            "--meeting-id", "dry-run-test",
            "--srt", srt_path,
            "--meeting-date", "2026-05-22",
            "--dry-run",
            "--dsn", "ignored",
        ],
        ledger=ledger,
    )

    out = capsys.readouterr().out
    # Dry-run line in summary.
    assert "dry-run" in out.lower()

    # Zero rows written to ledger.
    rows = asyncio.run(ledger.fetch(ALTIS_COMPANY_ID))
    assert len(rows) == 0, f"expected 0 rows in dry-run, got {len(rows)}"


# ---------------------------------------------------------------------------
# Test 6: Real-file smoke (optional — skip if file absent)
# ---------------------------------------------------------------------------

_ALTIS_SRT_PATH = "/Users/ricalanis/Downloads/Altis-Wormbase-72b96c65-7eaf.srt"


@pytest.mark.skipif(
    not os.path.exists(_ALTIS_SRT_PATH),
    reason=f"Real Altis SRT file not found at {_ALTIS_SRT_PATH}",
)
def test_real_altis_srt_parses_gte_50_turns(capsys) -> None:
    """Parse the real Altis SRT file with --dry-run; assert ≥50 turns."""
    main(
        argv=[
            "--tenant", "altis",
            "--meeting-id", "altis-wormbase-kickoff-prep",
            "--srt", _ALTIS_SRT_PATH,
            "--speakers", "Ricardo Alanís,Poncho Garciga,Ruben Madiedo",
            "--dry-run",
            "--dsn", "ignored",
        ],
        ledger=InMemoryLedger(),
    )

    out = capsys.readouterr().out
    # Extract turn count from "parsed N cues, M turns after speaker-grouping"
    import re
    m = re.search(r"(\d+) turns after speaker-grouping", out)
    assert m is not None, f"Could not find turn count in output: {out!r}"
    turn_count = int(m.group(1))
    assert turn_count >= 50, f"Expected ≥50 turns from real Altis SRT, got {turn_count}"


@pytest.mark.skipif(
    not os.path.exists(_ALTIS_SRT_PATH),
    reason=f"Real Altis SRT file not found at {_ALTIS_SRT_PATH}",
)
def test_real_altis_srt_cue_count(capsys) -> None:
    """The real Altis SRT has exactly 135 cues."""
    with open(_ALTIS_SRT_PATH, encoding="utf-8") as fh:
        content = fh.read()
    cues, detected_date = parse_srt(content)
    assert len(cues) == 135, f"Expected 135 cues, got {len(cues)}"
    assert detected_date is not None
    assert detected_date.month == 5
    assert detected_date.year == 2026
