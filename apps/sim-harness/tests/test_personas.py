"""Tests for the persona registry loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from wormbase_sim_harness.personas import Persona, PersonaRegistry


VALID_YAML = """\
personas:
  alice:
    display_name: Alice Chen
    icon_emoji: ":woman_office_worker:"
    role: Marketing
    voice_hint: friendly
  bob:
    display_name: Bob Martin
    icon_emoji: ":man:"
    role: DE
"""


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "personas.yml"
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_valid_personas(tmp_path: Path) -> None:
    reg = PersonaRegistry.from_yaml(_write(tmp_path, VALID_YAML))
    assert len(reg) == 2
    assert reg.has("alice") and reg.has("bob")
    alice = reg.get("alice")
    assert isinstance(alice, Persona)
    assert alice.display_name == "Alice Chen"
    assert alice.icon_emoji == ":woman_office_worker:"


def test_rejects_missing_top_level_key(tmp_path: Path) -> None:
    bad = "name: nope\n"
    with pytest.raises(ValueError, match="top-level 'personas' key"):
        PersonaRegistry.from_yaml(_write(tmp_path, bad))


def test_rejects_empty_personas_block(tmp_path: Path) -> None:
    bad = "personas: {}\n"
    with pytest.raises(ValueError, match="non-empty"):
        PersonaRegistry.from_yaml(_write(tmp_path, bad))


def test_rejects_bad_emoji_format(tmp_path: Path) -> None:
    bad = (
        "personas:\n"
        "  x:\n"
        "    display_name: X\n"
        "    icon_emoji: woman\n"
        "    role: Whatever\n"
    )
    with pytest.raises(Exception, match="colon form"):
        PersonaRegistry.from_yaml(_write(tmp_path, bad))


def test_unknown_persona_raises_keyerror(tmp_path: Path) -> None:
    reg = PersonaRegistry.from_yaml(_write(tmp_path, VALID_YAML))
    with pytest.raises(KeyError):
        reg.get("nobody")


def test_repo_personas_yml_loads() -> None:
    """The shipped personas.yml must always load cleanly."""
    here = Path(__file__).resolve().parents[1] / "personas.yml"
    reg = PersonaRegistry.from_yaml(here)
    assert {"alice", "bob", "carol"}.issubset(set(reg.personas))
