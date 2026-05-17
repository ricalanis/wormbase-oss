"""Tests for ScenarioEngine — drives a stub poster + virtual clock."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wormbase_sim_harness.clock import VirtualClock
from wormbase_sim_harness.engine import ScenarioEngine
from wormbase_sim_harness.personas import PersonaRegistry
from wormbase_sim_harness.scenario import Scenario


PERSONAS = """\
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


SCENARIO_TMPL = """\
name: t
default_channel: "#general"
beats:
  - at: 0
    persona: alice
    say: hi
  - at: 1
    persona: bob
    drop:
      file: {file}
      caption: have a look
  - at: 2
    persona: alice
    say: thanks
"""


class StubPoster:
    """Records every method call instead of touching Slack."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post_as(self, persona, channel, text):  # type: ignore[no-untyped-def]
        self.calls.append(
            ("post", {"persona": persona.id, "channel": channel, "text": text})
        )
        return {"ok": True, "ts": f"post-{len(self.calls)}"}

    async def upload_as(self, persona, channel, file_path, caption=None):  # type: ignore[no-untyped-def]
        self.calls.append(
            (
                "upload",
                {
                    "persona": persona.id,
                    "channel": channel,
                    "file_path": str(file_path),
                    "caption": caption,
                },
            )
        )
        return {"ok": True, "file_id": f"F{len(self.calls)}"}


@pytest.mark.asyncio
async def test_engine_runs_three_beats_in_order(tmp_path: Path) -> None:
    fpath = tmp_path / "drop.csv"
    fpath.write_text("a\n1\n", encoding="utf-8")

    pfile = tmp_path / "personas.yml"
    pfile.write_text(PERSONAS, encoding="utf-8")
    sfile = tmp_path / "s.yml"
    sfile.write_text(SCENARIO_TMPL.format(file=str(fpath)), encoding="utf-8")

    reg = PersonaRegistry.from_yaml(pfile)
    scen = Scenario.from_yaml(sfile)
    engine = ScenarioEngine(reg, improv=None, fixtures_root=tmp_path)
    poster = StubPoster()

    report = await engine.run(scen, VirtualClock(), poster)  # type: ignore[arg-type]

    # Three beats run, but the drop emits an upload AND no follow-up post
    # (no 'say' on that beat) so total calls = 1 post + 1 upload + 1 post = 3.
    assert len(poster.calls) == 3
    kinds = [k for k, _ in poster.calls]
    assert kinds == ["post", "upload", "post"]

    # First post: alice / hi
    assert poster.calls[0][1]["persona"] == "alice"
    assert poster.calls[0][1]["text"] == "hi"

    # Upload: bob / drop.csv with caption
    up = poster.calls[1][1]
    assert up["persona"] == "bob"
    assert up["caption"] == "have a look"
    assert up["file_path"].endswith("drop.csv")

    # Last post: alice / thanks
    assert poster.calls[2][1]["text"] == "thanks"

    # Report sanity.
    assert report.scenario == "t"
    assert len(report.beats) == 3
    assert report.beats[1].file is not None


@pytest.mark.asyncio
async def test_engine_drop_with_say_posts_follow_up(tmp_path: Path) -> None:
    fpath = tmp_path / "f.csv"
    fpath.write_text("a\n", encoding="utf-8")

    pfile = tmp_path / "personas.yml"
    pfile.write_text(PERSONAS, encoding="utf-8")

    body = (
        "name: t\n"
        'default_channel: "#x"\n'
        "beats:\n"
        f"  - at: 0\n    persona: bob\n"
        f"    say: 'fyi the file'\n"
        f"    drop:\n      file: {fpath}\n      caption: cap\n"
    )
    sfile = tmp_path / "s.yml"
    sfile.write_text(body, encoding="utf-8")

    reg = PersonaRegistry.from_yaml(pfile)
    scen = Scenario.from_yaml(sfile)
    engine = ScenarioEngine(reg, fixtures_root=tmp_path)
    poster = StubPoster()
    await engine.run(scen, VirtualClock(), poster)  # type: ignore[arg-type]

    kinds = [k for k, _ in poster.calls]
    assert kinds == ["upload", "post"]
    # The follow-up post must carry the say text.
    assert poster.calls[1][1]["text"] == "fyi the file"


@pytest.mark.asyncio
async def test_engine_channel_resolver(tmp_path: Path) -> None:
    pfile = tmp_path / "p.yml"
    pfile.write_text(PERSONAS, encoding="utf-8")
    sfile = tmp_path / "s.yml"
    sfile.write_text(
        "name: t\n"
        'default_channel: "#general"\n'
        "beats:\n"
        "  - at: 0\n    persona: alice\n    say: hi\n",
        encoding="utf-8",
    )
    reg = PersonaRegistry.from_yaml(pfile)
    scen = Scenario.from_yaml(sfile)
    engine = ScenarioEngine(reg)
    poster = StubPoster()
    await engine.run(
        scen,
        VirtualClock(),
        poster,  # type: ignore[arg-type]
        channel_resolver=lambda c: "C0RESOLVED",
    )
    assert poster.calls[0][1]["channel"] == "C0RESOLVED"
