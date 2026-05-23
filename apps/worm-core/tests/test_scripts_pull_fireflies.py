"""Tests for wormbase_core.scripts.pull_fireflies — wormbase-pull-fireflies CLI.

Test cases:
1. Mock Fireflies response  — 2-meeting canned response; assert 2 meetings ingested,
   correct turn counts written to InMemoryLedger.
2. Idempotency              — pre-seed ledger with one meeting; run pull-fireflies;
   assert that meeting is SKIPPED, the other is INGESTED.
3. --dry-run               — mock returns meetings; assert 0 ledger writes; summary printed.
4. --api-key error         — no env var, no --api-key flag; assert clear error + sys.exit(1).
5. Turn extraction         — 3 speakers in mock sentences; assert grouping merges consecutive
   same-speaker sentences within 30s and splits across gap / speaker change.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid5

import pytest

from wormbase_ledger import InMemoryLedger

from wormbase_core.scripts.pull_fireflies import (
    WORMBASE_TENANT_NAMESPACE,
    _sentences_to_turns,
    _is_already_ingested,
    _fetch_transcripts,
    ingest_turns,
    main,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALTIS_COMPANY_ID = uuid5(UUID(WORMBASE_TENANT_NAMESPACE), "altis")

# ---------------------------------------------------------------------------
# Canned Fireflies API responses
# ---------------------------------------------------------------------------

_MEETING_A_ID = "ff-meet-aaaa-1111"
_MEETING_B_ID = "ff-meet-bbbb-2222"

# Meeting A: 4 sentences — 2 from Alice (merging within 30s), then 1 Bob, then 1 Alice.
# Expected: 3 turns (Alice/merged, Bob, Alice).
_SENTENCES_A = [
    {
        "speaker_name": "Alice",
        "text": "Hello everyone.",
        "start_time": 0.0,
        "end_time": 2.0,
    },
    {
        "speaker_name": "Alice",
        "text": "Thanks for joining.",
        "start_time": 3.0,
        "end_time": 5.0,
    },
    {
        "speaker_name": "Bob",
        "text": "Happy to be here.",
        "start_time": 6.0,
        "end_time": 9.0,
    },
    {
        "speaker_name": "Alice",
        "text": "Great. Let's start.",
        "start_time": 10.0,
        "end_time": 13.0,
    },
]

# Meeting B: 2 sentences from Carol only (should merge to 1 turn).
_SENTENCES_B = [
    {
        "speaker_name": "Carol",
        "text": "This is a short meeting.",
        "start_time": 0.0,
        "end_time": 3.0,
    },
    {
        "speaker_name": "Carol",
        "text": "Wrap it up.",
        "start_time": 5.0,
        "end_time": 7.0,
    },
]


def _make_transcript(
    tid: str,
    title: str,
    date_str: str,
    sentences: list[dict],
) -> dict:
    """Build a canned Fireflies transcript dict matching the GraphQL shape."""
    return {
        "id": tid,
        "title": title,
        "date": date_str,
        "duration": 600,
        "transcript_url": None,
        "participants": ["alice@example.com"],
        "sentences": sentences,
    }


_TWO_MEETING_RESPONSE = [
    _make_transcript(_MEETING_A_ID, "Altis: Product Review", "2026-05-22T10:00:00Z", _SENTENCES_A),
    _make_transcript(_MEETING_B_ID, "Altis: Standup", "2026-05-21T09:00:00Z", _SENTENCES_B),
]


# ---------------------------------------------------------------------------
# Helper: monkey-patch _fetch_transcripts
# ---------------------------------------------------------------------------

def _patch_fetcher(monkeypatch, transcripts: list[dict]) -> None:
    """Replace _fetch_transcripts in the pull_fireflies module with a stub."""
    import wormbase_core.scripts.pull_fireflies as mod

    def _fake_fetch(api_key: str, *, since: datetime, limit: int) -> list[dict]:  # noqa: ARG001
        return transcripts

    monkeypatch.setattr(mod, "_fetch_transcripts", _fake_fetch)


# ---------------------------------------------------------------------------
# Test 1: Mock Fireflies response — 2 meetings ingested, correct turn counts
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

    # Meeting A has 3 turns (Alice merged, Bob, Alice), Meeting B has 1 turn.
    # Total = 4 turns × 4 PEVR rows each = 16 rows total.
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
    from wormbase_core.scripts.pull_fireflies import _sentences_to_turns
    from wormbase_core.scripts.ingest_transcript import _tenant_to_company_uuid

    company_id = _tenant_to_company_uuid("altis")
    meeting_id_b = f"altis-{_MEETING_B_ID}"
    base_dt = datetime(2026, 5, 21, 9, 0, 0, tzinfo=UTC)
    turns_b = _sentences_to_turns(_SENTENCES_B)

    asyncio.run(
        ingest_turns(
            ledger,
            company_id=company_id,
            meeting_id=meeting_id_b,
            base_dt=base_dt,
            turns=turns_b,
        )
    )

    # Confirm pre-seed: Meeting B's 1 turn → 4 PEVR rows.
    rows_before = asyncio.run(ledger.fetch(company_id))
    assert len(rows_before) == 4

    # Now run the CLI.
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
    assert "found 2 transcripts" in out


# ---------------------------------------------------------------------------
# Test 4: --api-key error → clear error + sys.exit(1)
# ---------------------------------------------------------------------------


def test_missing_api_key_exits_with_error(monkeypatch, capsys) -> None:
    """No FIREFLIES_API_KEY env + no --api-key → error message + exit 1."""
    # Remove FIREFLIES_API_KEY from environment if set.
    monkeypatch.delenv("FIREFLIES_API_KEY", raising=False)

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
    assert "FIREFLIES_API_KEY" in err


# ---------------------------------------------------------------------------
# Test 5: Turn extraction — grouping logic
# ---------------------------------------------------------------------------


def test_sentences_to_turns_merges_same_speaker_within_30s() -> None:
    """Consecutive same-speaker sentences within 30s merge to one turn."""
    sentences = [
        {"speaker_name": "Alice", "text": "one", "start_time": 0.0, "end_time": 2.0},
        {"speaker_name": "Alice", "text": "two", "start_time": 5.0, "end_time": 7.0},
        {"speaker_name": "Alice", "text": "three", "start_time": 10.0, "end_time": 12.0},
    ]
    turns = _sentences_to_turns(sentences)
    assert len(turns) == 1
    assert turns[0].speaker == "Alice"
    assert "one" in turns[0].text
    assert "three" in turns[0].text


def test_sentences_to_turns_splits_on_speaker_change() -> None:
    """Different speaker always starts a new turn."""
    sentences = [
        {"speaker_name": "Alice", "text": "hello", "start_time": 0.0, "end_time": 2.0},
        {"speaker_name": "Bob", "text": "world", "start_time": 3.0, "end_time": 5.0},
        {"speaker_name": "Alice", "text": "back", "start_time": 6.0, "end_time": 8.0},
    ]
    turns = _sentences_to_turns(sentences)
    assert len(turns) == 3
    assert turns[0].speaker == "Alice"
    assert turns[1].speaker == "Bob"
    assert turns[2].speaker == "Alice"


def test_sentences_to_turns_splits_on_large_gap() -> None:
    """Same speaker but >30s gap starts a new turn."""
    sentences = [
        {"speaker_name": "Alice", "text": "early", "start_time": 0.0, "end_time": 5.0},
        {"speaker_name": "Alice", "text": "late", "start_time": 60.0, "end_time": 65.0},
    ]
    turns = _sentences_to_turns(sentences)
    assert len(turns) == 2
    assert turns[0].text == "early"
    assert turns[1].text == "late"


def test_sentences_to_turns_three_speakers_complex() -> None:
    """3-speaker interleaved sentences produce correct turn sequence."""
    # Meeting A sentences → should yield 3 turns.
    turns = _sentences_to_turns(_SENTENCES_A)
    assert len(turns) == 3
    assert turns[0].speaker == "Alice"
    assert "Hello everyone." in turns[0].text
    assert "Thanks for joining." in turns[0].text
    assert turns[1].speaker == "Bob"
    assert turns[2].speaker == "Alice"
    assert "Let's start" in turns[2].text


def test_sentences_to_turns_empty() -> None:
    """Empty sentence list produces no turns."""
    turns = _sentences_to_turns([])
    assert turns == []


# ---------------------------------------------------------------------------
# Test 6: _is_already_ingested — checks ledger for existing rows
# ---------------------------------------------------------------------------


def test_is_already_ingested_false_when_empty() -> None:
    """Empty ledger → not already ingested."""
    ledger = InMemoryLedger()
    result = asyncio.run(
        _is_already_ingested(ledger, company_id=ALTIS_COMPANY_ID, meeting_id="altis-ff-new")
    )
    assert result is False


def test_is_already_ingested_true_after_seed(monkeypatch) -> None:
    """After seeding a meeting, _is_already_ingested returns True."""
    ledger = InMemoryLedger()
    meeting_id = "altis-ff-seeded-meet"
    base_dt = datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC)
    sentences = [
        {"speaker_name": "Alice", "text": "hi", "start_time": 0.0, "end_time": 1.0}
    ]
    turns = _sentences_to_turns(sentences)

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
# Test 7: meeting-id-prefix flag controls synthesized meeting_id
# ---------------------------------------------------------------------------


def test_meeting_id_prefix_flag(monkeypatch, capsys) -> None:
    """--meeting-id-prefix controls synthesized meeting_id = <prefix>-<fireflies_id>."""
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

    # All message_ids should start with "transcript-myprefix-ff-meet-aaaa-1111-"
    for r in execute_rows:
        result_ref = r["payload"]["result_ref"]
        assert result_ref.startswith("transcript-myprefix-"), (
            f"result_ref {result_ref!r} does not start with 'transcript-myprefix-'"
        )
