"""Unit tests for ``wormbase_sim_harness.seed_loader``.

Covers:

  * ``default_fixture_dir`` resolves to ``tests/fixtures/install_arc_seed``
    relative to the repo root.
  * Each of the four canonical seed JSONLs is loadable, returns a
    non-empty event list, and tags every event with the right ``seed_id``.
  * ``load_install_arc_seeds`` returns the union sorted by ``ts`` then
    ``seq``; total count equals the sum of per-file counts.
  * ``base_ts`` re-anchors timestamps so install-arc-relative spacing
    is preserved.
  * ``write_unioned_jsonl`` produces a JSONL the WireReplayer can read.
  * Malformed lines are skipped with a warning (not a hard failure).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from wormbase_sim_harness.seed_loader import (
    INSTALL_ARC_EPOCH,
    PERSONA_UUIDS,
    SEED_FILES,
    SeedEvent,
    default_fixture_dir,
    load_install_arc_seeds,
    load_seed_file,
    write_unioned_jsonl,
)


# ---------------------------------------------------------------------------
# default_fixture_dir
# ---------------------------------------------------------------------------


def test_default_fixture_dir_resolves_under_repo() -> None:
    fdir = default_fixture_dir()
    assert fdir.is_dir(), f"expected fixture dir to exist: {fdir}"
    assert fdir.name == "install_arc_seed"


def test_canonical_seed_files_are_present() -> None:
    fdir = default_fixture_dir()
    missing = [f for f in SEED_FILES if not (fdir / f).is_file()]
    assert not missing, f"missing canonical seed files: {missing}"


# ---------------------------------------------------------------------------
# load_seed_file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fname,expected_seed_id",
    [
        ("cursed_csv_chatter.jsonl", "S1"),
        ("recurring_action_chatter.jsonl", "S2"),
        ("domain_touched_chatter.jsonl", "S3"),
        ("recurring_question_chatter.jsonl", "S4"),
    ],
)
def test_load_seed_file_tags_seed_id(fname: str, expected_seed_id: str) -> None:
    fdir = default_fixture_dir()
    events = load_seed_file(fdir / fname)
    assert events, f"{fname} produced zero events"
    for ev in events:
        assert ev.seed_id == expected_seed_id, (
            f"event in {fname} tagged with {ev.seed_id}, expected "
            f"{expected_seed_id}"
        )
        assert ev.tool.startswith("channel_adapter."), (
            "all seed events must be channel-adapter wire tools"
        )


def test_load_seed_file_preserves_ts_when_no_base_ts() -> None:
    fdir = default_fixture_dir()
    events = load_seed_file(fdir / "cursed_csv_chatter.jsonl")
    # The first event's ts should be in April 2026.
    first = events[0]
    assert first.ts.year == 2026
    assert first.ts.month == 4
    # All ts are tz-aware UTC.
    for ev in events:
        assert ev.ts.tzinfo is not None
        assert ev.ts.utcoffset() == timedelta(0)


def test_load_seed_file_re_anchors_with_base_ts() -> None:
    """A non-default ``base_ts`` shifts every event by the same delta."""
    fdir = default_fixture_dir()
    new_anchor = datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    raw = load_seed_file(fdir / "cursed_csv_chatter.jsonl")
    shifted = load_seed_file(
        fdir / "cursed_csv_chatter.jsonl", base_ts=new_anchor,
    )
    assert len(raw) == len(shifted)
    for r, s in zip(raw, shifted):
        delta_raw = r.ts - INSTALL_ARC_EPOCH
        delta_shifted = s.ts - new_anchor
        assert delta_raw == delta_shifted, (
            "shift should preserve relative spacing; "
            f"raw={delta_raw} shifted={delta_shifted}"
        )


def test_load_seed_file_skips_malformed_lines(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    good = {
        "seq": 1,
        "ts": "2026-04-28T00:00:00+00:00",
        "tool": "channel_adapter.emit_chat_received",
        "args": {"channel_id": "C0", "text": "ok"},
    }
    p.write_text(
        "\n".join(["", "not-json", json.dumps(good), "[]", ""]) + "\n",
    )
    events = load_seed_file(p)
    assert len(events) == 1
    assert events[0].tool == "channel_adapter.emit_chat_received"


def test_load_seed_file_skips_records_missing_ts(tmp_path: Path) -> None:
    p = tmp_path / "no_ts.jsonl"
    bad = {"seq": 1, "tool": "channel_adapter.emit_chat_received", "args": {}}
    good = {
        "seq": 2,
        "ts": "2026-04-28T00:00:00+00:00",
        "tool": "channel_adapter.emit_chat_received",
        "args": {"channel_id": "C0"},
    }
    p.write_text(json.dumps(bad) + "\n" + json.dumps(good) + "\n")
    events = load_seed_file(p)
    assert len(events) == 1
    assert events[0].seq == 2


# ---------------------------------------------------------------------------
# load_install_arc_seeds
# ---------------------------------------------------------------------------


def test_load_install_arc_seeds_returns_sorted_union() -> None:
    events, report = load_install_arc_seeds()
    assert report.total_events == len(events) > 0
    # Sum of per-seed counts equals the total.
    assert sum(report.events_per_seed.values()) == report.total_events
    # All four seeds contribute.
    assert set(report.events_per_seed.keys()) == {"S1", "S2", "S3", "S4"}
    for sid, n in report.events_per_seed.items():
        assert n > 0, f"seed {sid} contributed zero events"
    # Sorted ascending by ts (tie-broken by seq).
    for prev, curr in zip(events, events[1:]):
        assert (prev.ts, prev.seq) <= (curr.ts, curr.seq)


def test_load_install_arc_seeds_personas_are_canonical() -> None:
    """Every seed event references one of the canonical persona UUIDs."""
    events, _ = load_install_arc_seeds()
    canonical = set(PERSONA_UUIDS.values())
    for ev in events:
        sender = ev.args.get("sender_person")
        if sender is None:
            continue
        assert sender in canonical, (
            f"non-canonical sender_person {sender!r} in seed "
            f"{ev.seed_id} ({ev.beat_label})"
        )


def test_load_install_arc_seeds_with_base_ts_shifts_all() -> None:
    new_anchor = datetime(2030, 6, 1, tzinfo=timezone.utc)
    raw, raw_report = load_install_arc_seeds()
    shifted, shifted_report = load_install_arc_seeds(base_ts=new_anchor)
    assert raw_report.total_events == shifted_report.total_events
    # Every event's effective ts moves forward by the same delta.
    target_delta = new_anchor - INSTALL_ARC_EPOCH
    for r, s in zip(raw, shifted):
        # Same seq → same shifted relationship (sort is stable).
        assert s.ts - r.ts == target_delta


# ---------------------------------------------------------------------------
# write_unioned_jsonl
# ---------------------------------------------------------------------------


def test_write_unioned_jsonl_round_trips(tmp_path: Path) -> None:
    events, _ = load_install_arc_seeds()
    out = tmp_path / "union.jsonl"
    n = write_unioned_jsonl(events, out)
    assert n == len(events)
    # Re-load through load_seed_file.
    reloaded = load_seed_file(out, seed_id="S?")
    assert len(reloaded) == n
    # Wire shape is preserved.
    for orig, copy in zip(events, reloaded):
        assert orig.tool == copy.tool
        assert orig.args == copy.args


def test_write_unioned_jsonl_only_required_fields_for_wire_replay(
    tmp_path: Path,
) -> None:
    """``WireReplayer`` only inspects ``tool`` and ``args`` — verify both
    are JSON-serialisable on every record."""
    events, _ = load_install_arc_seeds()
    out = tmp_path / "union.jsonl"
    write_unioned_jsonl(events, out)
    with out.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            assert isinstance(rec.get("tool"), str)
            assert isinstance(rec.get("args"), dict)


# ---------------------------------------------------------------------------
# Beat-level structural checks
# ---------------------------------------------------------------------------


def test_seed_s1_references_cursed_csv_column_literally() -> None:
    """S1 must reference the literal cursed CSV column name so the
    phenomenon-gap detector has concrete chatter to point at on stage."""
    fdir = default_fixture_dir()
    text_corpus = (fdir / "cursed_csv_chatter.jsonl").read_text()
    assert "Q3 Rev (final)(USE THIS)" in text_corpus, (
        "S1 must cite the literal cursed CSV column name "
        "fixtures/cursed_finance_export.csv"
    )


def test_seed_s4_has_at_least_three_recurrences_of_one_triplet() -> None:
    """S4 must trip P10's threshold: same (asker, askee, topic) ≥3 times."""
    fdir = default_fixture_dir()
    events = load_seed_file(fdir / "recurring_question_chatter.jsonl")
    triplets: dict[tuple[str, str, str], int] = {}
    for ev in events:
        asker = str(ev.args.get("sender_person", ""))
        askee = str(ev.args.get("thread_parent_person", ""))
        topic = str(ev.args.get("topic", ""))
        if not (asker and askee and topic):
            continue
        triplets[(asker, askee, topic)] = (
            triplets.get((asker, askee, topic), 0) + 1
        )
    assert any(c >= 3 for c in triplets.values()), (
        f"S4 must contain at least one (asker, askee, topic) triplet "
        f"appearing ≥3 times; got {triplets}"
    )


def test_seed_s4_threaded_messages_have_thread_ts_distinct_from_ts() -> None:
    """P10's InThread predicate requires ``thread_ts != ts``."""
    fdir = default_fixture_dir()
    events = load_seed_file(fdir / "recurring_question_chatter.jsonl")
    for ev in events:
        ts = ev.args.get("ts")
        thread_ts = ev.args.get("thread_ts")
        if ts and thread_ts:
            assert ts != thread_ts, (
                f"S4 event {ev.beat_label} has thread_ts == ts; will "
                f"not match InThread predicate"
            )


def test_seed_s2_recurring_pattern_phrasings_present() -> None:
    """S2 must contain at least one ``every <cadence>`` and one
    ``whenever`` template so DescribesRecurringPattern fires both
    regex families."""
    fdir = default_fixture_dir()
    text_corpus = (
        fdir / "recurring_action_chatter.jsonl"
    ).read_text().lower()
    assert "every friday" in text_corpus or "every monday" in text_corpus
    assert "whenever" in text_corpus or "every time" in text_corpus


def test_event_to_wire_dict_matches_seed_event_round_trip() -> None:
    ev = SeedEvent(
        seq=42,
        ts=datetime(2026, 4, 28, 0, 5, 0, tzinfo=timezone.utc),
        tool="channel_adapter.emit_chat_received",
        args={"channel_id": "C0", "text": "hi"},
        seed_id="S1",
        beat_index=6,
        beat_label="x",
    )
    wire = ev.to_wire_dict()
    assert wire["tool"] == ev.tool
    assert wire["args"] == ev.args
    assert wire["seq"] == ev.seq
    assert wire["seed_id"] == "S1"
    assert wire["beat_index"] == 6
    assert wire["beat_label"] == "x"
