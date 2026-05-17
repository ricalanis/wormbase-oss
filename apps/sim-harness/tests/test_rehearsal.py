"""Tests for the rehearsal pipeline.

Covers:

* MockSlackPoster records ``post_as`` / ``upload_as`` calls.
* ``run_rehearsal`` against a 3-beat scenario completes with a passing
  RehearsalReport.
* The pipeline correctly orders calls (asserts beats fire in declared
  ``at`` order).
* When pre-flight + seed deps are unavailable (CI, mid-hackathon), the
  rehearsal emits warnings rather than crashing and the report still
  reports the run/structural phases.
* ``run_rehearsal`` flags an ordering violation when the engine is
  bypassed and a hand-rolled call sequence is fed in.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from wormbase_sim_harness.personas import Persona
from wormbase_sim_harness.rehearsal import (
    MockSlackPoster,
    RehearsalReport,
    _ordering_violations,
    assert_rehearsal_invariants,
    run_rehearsal,
)
from wormbase_sim_harness.scenario import Scenario


PERSONAS_YAML = """\
personas:
  alice:
    display_name: Alice
    icon_emoji: ":woman:"
    role: PM
  bob:
    display_name: Bob
    icon_emoji: ":man:"
    role: DE
"""


def _write_personas(tmp_path: Path) -> Path:
    p = tmp_path / "personas.yml"
    p.write_text(PERSONAS_YAML, encoding="utf-8")
    return p


def _write_scenario(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "scenario.yml"
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# MockSlackPoster
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_post_as_records_call() -> None:
    poster = MockSlackPoster()
    persona = Persona(
        id="alice",
        display_name="Alice",
        icon_emoji=":woman:",
        role="PM",
    )
    resp = await poster.post_as(persona, "#x", "hello")
    assert resp["ok"] is True
    assert resp["channel"] == "#x"
    assert len(poster.calls) == 1
    call = poster.calls[0]
    assert call.kind == "post"
    assert call.persona_id == "alice"
    assert call.channel == "#x"
    assert call.text == "hello"
    assert call.seq == 1
    # Convenience views.
    assert poster.post_calls == [call]
    assert poster.upload_calls == []
    assert poster.calls_by_persona("alice") == [call]


@pytest.mark.asyncio
async def test_mock_upload_as_records_call(tmp_path: Path) -> None:
    poster = MockSlackPoster()
    persona = Persona(
        id="bob",
        display_name="Bob",
        icon_emoji=":man:",
        role="DE",
    )
    fpath = tmp_path / "drop.csv"
    fpath.write_text("col\n1\n", encoding="utf-8")
    resp = await poster.upload_as(persona, "#x", fpath, caption="here")
    assert resp["ok"] is True
    assert resp["file_id"].startswith("mockF")
    assert len(poster.calls) == 1
    call = poster.calls[0]
    assert call.kind == "upload"
    assert call.persona_id == "bob"
    assert call.channel == "#x"
    assert call.file_path is not None and call.file_path.endswith("drop.csv")
    assert call.caption == "here"
    assert poster.upload_calls == [call]
    assert poster.post_calls == []


@pytest.mark.asyncio
async def test_mock_records_post_and_upload_in_order(tmp_path: Path) -> None:
    poster = MockSlackPoster()
    alice = Persona(id="alice", display_name="A", icon_emoji=":a:", role="PM")
    bob = Persona(id="bob", display_name="B", icon_emoji=":b:", role="DE")
    fpath = tmp_path / "f.csv"
    fpath.write_text("a\n1\n", encoding="utf-8")
    await poster.post_as(alice, "#x", "hi")
    await poster.upload_as(bob, "#x", fpath, caption="here")
    await poster.post_as(alice, "#x", "thanks")
    kinds = [c.kind for c in poster.calls]
    assert kinds == ["post", "upload", "post"]
    assert [c.seq for c in poster.calls] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Ordering helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ordering_violations_detects_swapped_beats(tmp_path: Path) -> None:
    fpath = tmp_path / "f.csv"
    fpath.write_text("a\n", encoding="utf-8")
    body = (
        "name: t\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 0\n    persona: alice\n    say: hi\n"
        "  - at: 1\n    persona: bob\n    say: hey\n"
    )
    sfile = _write_scenario(tmp_path, body)
    scen = Scenario.from_yaml(sfile)
    poster = MockSlackPoster()
    alice = Persona(id="alice", display_name="A", icon_emoji=":a:", role="PM")
    bob = Persona(id="bob", display_name="B", icon_emoji=":b:", role="DE")
    # Inject calls IN THE WRONG ORDER (bob before alice).
    await poster.post_as(bob, "#x", "hey")
    await poster.post_as(alice, "#x", "hi")

    violations = _ordering_violations(scen, poster)
    assert violations, "expected ordering violations for swapped beats"
    assert any("beat 0" in v for v in violations)


# ---------------------------------------------------------------------------
# run_rehearsal — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_rehearsal_three_beat_scenario_passes(tmp_path: Path) -> None:
    pfile = _write_personas(tmp_path)
    fpath = tmp_path / "fixtures" / "f.csv"
    fpath.parent.mkdir()
    fpath.write_text("col\n1\n", encoding="utf-8")
    body = (
        "name: rehearse-t\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 0\n    persona: alice\n    say: hi\n"
        "  - at: 1\n    persona: bob\n"
        "    drop:\n      file: f.csv\n      caption: hereyago\n"
        "  - at: 2\n    persona: alice\n    say: thanks\n"
    )
    sfile = _write_scenario(tmp_path, body)

    with warnings.catch_warnings():
        # pre-flight + seed will warn (no docker, no DSN); test still passes.
        warnings.simplefilter("ignore", RuntimeWarning)
        report = await run_rehearsal(
            sfile,
            ledger_dsn=None,  # skip seed
            tenant="baseworm",
            personas_path=pfile,
            fixtures_root=fpath.parent,
        )
    assert isinstance(report, RehearsalReport)
    assert report.scenario == "rehearse-t"
    assert report.tenant == "baseworm"
    # 1 post + 1 upload + 1 post = 3 calls.
    assert report.total_calls == 3
    assert report.drops_observed == 1
    assert report.ordering_violations == []
    assert not report.errors
    # Posts: alice spoke twice; bob's drop posted nothing extra.
    assert report.posts_per_persona == {"alice": 2}
    assert report.uploads_per_persona == {"bob": 1}
    # Phases: preflight (skipped on no-docker), seed (skipped no-DSN),
    # run (passed), rehearsal_invariants (passed), ledger_acceptance (skipped).
    phase_names = [p.name for p in report.phases]
    assert "run" in phase_names
    assert "rehearsal_invariants" in phase_names
    run_phase = next(p for p in report.phases if p.name == "run")
    assert run_phase.passed is True
    inv_phase = next(p for p in report.phases if p.name == "rehearsal_invariants")
    assert inv_phase.passed is True
    # Whole report is passed because every fail-eligible phase passed.
    assert report.passed is True


@pytest.mark.asyncio
async def test_run_rehearsal_emits_calls_in_beat_order(tmp_path: Path) -> None:
    pfile = _write_personas(tmp_path)
    fpath = tmp_path / "fixtures" / "f.csv"
    fpath.parent.mkdir()
    fpath.write_text("col\n1\n", encoding="utf-8")
    body = (
        "name: order-test\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 0\n    persona: alice\n    say: first\n"
        "  - at: 1\n    persona: bob\n    say: second\n"
        "  - at: 2\n    persona: alice\n"
        "    drop:\n      file: f.csv\n"
        "  - at: 3\n    persona: bob\n    say: fourth\n"
    )
    sfile = _write_scenario(tmp_path, body)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        report = await run_rehearsal(
            sfile,
            ledger_dsn=None,
            personas_path=pfile,
            fixtures_root=fpath.parent,
        )
    assert report.passed is True
    assert report.ordering_violations == []
    # Total calls: 4 beats, beat 2 is a drop with no 'say' so 1 upload only.
    assert report.total_calls == 4
    assert report.drops_observed == 1


# ---------------------------------------------------------------------------
# run_rehearsal — degraded paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_rehearsal_warns_when_preflight_seed_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No docker + no DSN must produce warnings, not crashes."""
    pfile = _write_personas(tmp_path)
    body = (
        "name: minimal\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 0\n    persona: alice\n    say: hi\n"
    )
    sfile = _write_scenario(tmp_path, body)

    # Simulate "no docker on PATH" by stubbing shutil.which to return None.
    import wormbase_sim_harness.rehearsal as rh

    monkeypatch.setattr(rh, "_docker_available", lambda: False)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        report = await run_rehearsal(
            sfile,
            ledger_dsn=None,
            personas_path=pfile,
            fixtures_root=tmp_path,
        )
    # At least one RuntimeWarning fired (pre-flight skip).
    assert any(
        issubclass(w.category, RuntimeWarning)
        and "docker" in str(w.message).lower()
        for w in caught
    ), "expected a docker-related RuntimeWarning"
    # Run still completes; whole report still passed.
    assert report.passed is True
    preflight = next(p for p in report.phases if p.name == "preflight")
    assert preflight.skipped is True
    seed = next(p for p in report.phases if p.name == "seed")
    assert seed.skipped is True


@pytest.mark.asyncio
async def test_run_rehearsal_drop_only_scenario_records_upload(tmp_path: Path) -> None:
    pfile = _write_personas(tmp_path)
    fpath = tmp_path / "fixtures" / "data.csv"
    fpath.parent.mkdir()
    fpath.write_text("a,b\n1,2\n", encoding="utf-8")
    body = (
        "name: drop-only\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 0\n    persona: bob\n"
        "    drop:\n      file: data.csv\n      caption: heres-the-thing\n"
    )
    sfile = _write_scenario(tmp_path, body)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        report = await run_rehearsal(
            sfile,
            ledger_dsn=None,
            personas_path=pfile,
            fixtures_root=fpath.parent,
        )
    assert report.passed is True
    assert report.total_calls == 1
    assert report.drops_observed == 1
    assert report.uploads_per_persona == {"bob": 1}
    assert report.posts_per_persona == {}


# ---------------------------------------------------------------------------
# assert_rehearsal_invariants — pure-Python checks
# ---------------------------------------------------------------------------


def test_assert_rehearsal_invariants_passes_for_clean_report() -> None:
    rep = RehearsalReport(scenario="x", tenant="baseworm")
    rep.total_calls = 3
    rep.drops_observed = 1
    out = assert_rehearsal_invariants(rep)
    inv = next(p for p in out.phases if p.name == "rehearsal_invariants")
    assert inv.passed is True


def test_assert_rehearsal_invariants_flags_zero_calls() -> None:
    rep = RehearsalReport(scenario="x", tenant="baseworm")
    rep.total_calls = 0
    out = assert_rehearsal_invariants(rep)
    inv = next(p for p in out.phases if p.name == "rehearsal_invariants")
    assert inv.passed is False
    assert "zero poster calls" in inv.detail


def test_assert_rehearsal_invariants_flags_ordering_violations() -> None:
    rep = RehearsalReport(scenario="x", tenant="baseworm")
    rep.total_calls = 2
    rep.ordering_violations.append("beat 0: expected (alice,post) got (bob,post)")
    out = assert_rehearsal_invariants(rep)
    inv = next(p for p in out.phases if p.name == "rehearsal_invariants")
    assert inv.passed is False
    assert "ordering violations" in inv.detail
