"""Tests for the scenario YAML loader + validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from wormbase_sim_harness.personas import PersonaRegistry
from wormbase_sim_harness.scenario import Scenario, list_scenarios


VALID = """\
name: smoke
description: A two-beat smoke scenario.
default_channel: "#general"
beats:
  - at: 0
    persona: alice
    say: "morning"
  - at: 5
    persona: bob
    drop:
      file: foo.csv
      caption: here
"""


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


def _write(tmp_path: Path, body: str, name: str = "scenario.yml") -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_valid_scenario(tmp_path: Path) -> None:
    s = Scenario.from_yaml(_write(tmp_path, VALID))
    assert s.name == "smoke"
    assert len(s.beats) == 2
    assert s.beats[0].say == "morning"
    assert s.beats[1].drop and s.beats[1].drop.file == "foo.csv"


def test_rejects_monotonicity_violation(tmp_path: Path) -> None:
    bad = (
        "name: bad\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 10\n    persona: a\n    say: hi\n"
        "  - at: 5\n    persona: a\n    say: oops\n"
    )
    with pytest.raises(Exception, match="monotonic"):
        Scenario.from_yaml(_write(tmp_path, bad))


def test_rejects_beat_with_neither_say_nor_drop(tmp_path: Path) -> None:
    bad = (
        "name: bad2\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 0\n    persona: alice\n"
    )
    with pytest.raises(Exception, match="say|drop"):
        Scenario.from_yaml(_write(tmp_path, bad))


def test_improv_requires_seed(tmp_path: Path) -> None:
    bad = (
        "name: bad3\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 0\n    persona: alice\n    improv: true\n    drop:\n      file: x\n"
    )
    with pytest.raises(Exception, match="improv"):
        Scenario.from_yaml(_write(tmp_path, bad))


def test_validate_against_rejects_unknown_persona(tmp_path: Path) -> None:
    s = Scenario.from_yaml(_write(tmp_path, VALID))
    pfile = _write(tmp_path, PERSONAS_YAML, "p.yml")
    reg = PersonaRegistry.from_yaml(pfile)
    # Both alice and bob are present — should pass.
    s.validate_against(reg)

    # Add a 3rd beat with an unknown persona.
    extra = VALID + "  - at: 10\n    persona: ghost\n    say: boo\n"
    s2 = Scenario.from_yaml(_write(tmp_path, extra, "s2.yml"))
    with pytest.raises(ValueError, match="ghost"):
        s2.validate_against(reg)


def test_list_scenarios(tmp_path: Path) -> None:
    (tmp_path / "a.yml").write_text("name: a\ndefault_channel: '#x'\nbeats: []\n")
    (tmp_path / "b.yaml").write_text("name: b\ndefault_channel: '#x'\nbeats: []\n")
    (tmp_path / "c.txt").write_text("ignored")
    names = list_scenarios(tmp_path)
    assert names == ["a", "b"]


def test_repo_demo_scenario_loads_and_matches_personas() -> None:
    here = Path(__file__).resolve().parents[1]
    s = Scenario.from_yaml(here / "scenarios" / "demo-c-plus-b.yml")
    reg = PersonaRegistry.from_yaml(here / "personas.yml")
    s.validate_against(reg)
    # Sanity: at least one drop, at least one mention-style beat.
    assert any(b.drop is not None for b in s.beats)
    assert any(b.say and "@WormBase" in b.say for b in s.beats)


def _load_repo_scenario(stem: str) -> tuple[Scenario, PersonaRegistry]:
    here = Path(__file__).resolve().parents[1]
    s = Scenario.from_yaml(here / "scenarios" / f"{stem}.yml")
    reg = PersonaRegistry.from_yaml(here / "personas.yml")
    return s, reg


def _assert_monotonic(s: Scenario) -> None:
    last = -1.0
    for i, beat in enumerate(s.beats):
        assert beat.at >= last, (
            f"scenario {s.name!r} beat {i} at={beat.at} < previous {last}"
        )
        last = beat.at


def test_repo_demo_c_plus_b_full_arc() -> None:
    """The C+B scenario must hit all 5 acts of the canonical product arc.

    We can't introspect comments, so we verify the structural fingerprint:
      - >= 14 beats (acts I-V padded scenario)
      - has at least one file drop (Act II)
      - has at least 3 @WormBase mentions (Act III + IV + V)
      - last @WormBase mention is at-or-after t=110 (Act V research beat)
    """
    s, reg = _load_repo_scenario("demo-c-plus-b")
    s.validate_against(reg)
    _assert_monotonic(s)
    assert len(s.beats) >= 14
    assert any(b.drop is not None for b in s.beats)
    mentions = [b for b in s.beats if b.say and "@WormBase" in b.say]
    assert len(mentions) >= 3, "need >= 3 @WormBase beats across Acts III/IV/V"
    assert mentions[-1].at >= 110, (
        "final @WormBase beat should be the Act V research-log question"
    )


def test_repo_extended_replay_full_week() -> None:
    """The extended-replay scenario must span a fictional week with 4 personas."""
    s, reg = _load_repo_scenario("extended-replay")
    s.validate_against(reg)
    _assert_monotonic(s)
    # ~30 beats across 5 days
    assert len(s.beats) >= 28
    # All 4 personas (alice, bob, carol, dave) participate
    used = {b.persona for b in s.beats}
    assert {"alice", "bob", "carol", "dave"}.issubset(used), (
        f"extended-replay must use all 4 personas; got {used}"
    )
    # >= 5 file drops (one per workday-ish)
    drops = [b for b in s.beats if b.drop is not None]
    assert len(drops) >= 5
    # >= 5 @WormBase mentions distributed across the week
    mentions = [b for b in s.beats if b.say and "@WormBase" in b.say]
    assert len(mentions) >= 5
    # Last beat lands well past 200s — Friday research-log territory
    assert s.beats[-1].at >= 180


def test_repo_proactivity_demo_hero_beat() -> None:
    """The proactivity scenario must showcase mentioned_in_conv'n + credential."""
    s, reg = _load_repo_scenario("proactivity-demo")
    s.validate_against(reg)
    _assert_monotonic(s)
    # ~60s focused scenario
    assert s.beats[-1].at <= 65, "proactivity-demo must stay under ~60s"
    assert s.beats[-1].at >= 50
    # The Stripe mention (no @WormBase) must come BEFORE the
    # credential @WormBase post — this is the trigger ordering.
    stripe_idx = next(
        (i for i, b in enumerate(s.beats) if b.say and "Stripe" in b.say),
        None,
    )
    assert stripe_idx is not None
    cred_idx = next(
        (
            i
            for i, b in enumerate(s.beats)
            if b.say and "@WormBase" in b.say and "key" in b.say.lower()
        ),
        None,
    )
    assert cred_idx is not None
    assert stripe_idx < cred_idx


def test_repo_personas_yaml_has_dave() -> None:
    """personas.yml must register the Data Engineer persona used by extended-replay."""
    here = Path(__file__).resolve().parents[1]
    reg = PersonaRegistry.from_yaml(here / "personas.yml")
    assert reg.has("dave")
    dave = reg.get("dave")
    assert "Engineer" in dave.role
    assert dave.icon_emoji.startswith(":") and dave.icon_emoji.endswith(":")
