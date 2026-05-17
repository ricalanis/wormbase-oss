"""Tests for the 7-beat install-arc scenario YAML + new beat directives.

Covers:

  * The repo-shipped ``install-arc-7beat.yml`` parses, validates, and
    declares the seven beats PRD §10 prescribes (one per ~30s window).
  * The new ``wait_for`` directive in :class:`Scenario` accepts both
    the bare-string shorthand and the structured form.
  * The new ``dm`` directive is parseable and engine-dispatched.
  * The engine's ``wait_for`` resolves against an in-memory ledger that
    fakes a tool landing after a poll cycle (asserts the polling logic
    is alive and the count semantics are correct).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from wormbase_sim_harness.clock import VirtualClock
from wormbase_sim_harness.engine import ScenarioEngine
from wormbase_sim_harness.personas import PersonaRegistry
from wormbase_sim_harness.scenario import Scenario, WaitFor


REPO_ROOT = Path(__file__).resolve().parents[2].parent


# ---------------------------------------------------------------------------
# Schema-level: the YAML parses and matches PRD §10.
# ---------------------------------------------------------------------------


def _scenario_path() -> Path:
    return (
        REPO_ROOT
        / "apps/sim-harness/scenarios/install-arc-7beat.yml"
    )


def test_install_arc_7beat_yaml_parses_and_validates() -> None:
    """install-arc-7beat.yml loads cleanly with the v3 chat-first shape.

    Block I6 (PRD §17, REVISED 2026-04-27 minimal-friction) reverted
    Beat 1 to chat-platform connect; the default local lake provisions
    automatically during install. The wizard-vs-bot fork moved out of
    the install arc — it's now a banner CTA on the dashboard, not a
    waitable wire event.

      * Beat 1a  — emit_install_completed             (Slack OAuth on stage)
      * Beat 1b  — emit_source_proposed               (default local lake)
      * Beat 5   — dashboard.tenant_switched
      * Beat 6   — dashboard.research_loaded
      * Beat 8   — emit_mcp_call_received             (Claude Desktop MCP)
      * Beat 9a  — emit_resource_conversation_proposed (W5.A2 fires)
      * Beat 9b  — emit_resource_conversation_replied  (Carol DMs back)
    Total wait_for beats: 7. Drop/dm/say beats: 1 drop, 2 dms, 4 says.
    """
    path = _scenario_path()
    assert path.is_file(), f"scenario not found at {path}"
    scen = Scenario.from_yaml(path)
    assert scen.name == "install-arc-7beat"
    assert scen.default_channel.startswith("#")

    waits = [b for b in scen.beats if b.wait_for is not None]
    drops = [b for b in scen.beats if b.drop is not None]
    dms = [b for b in scen.beats if b.dm is not None]
    says = [
        b for b in scen.beats
        if b.say is not None
        and b.drop is None
        and b.dm is None
        and b.wait_for is None
    ]
    assert len(waits) == 7, f"expected 7 wait_for beats, got {len(waits)}"
    assert len(drops) == 1, f"expected 1 drop beat, got {len(drops)}"
    assert len(dms) == 2, f"expected 2 dm beats, got {len(dms)}"
    assert len(says) == 4, f"expected 4 plain say beats, got {len(says)}"

    # The seven wait_for tools are the canonical install-arc anchors,
    # including Beat 8 (MCP via Claude Desktop, J7 2026-04-26) and
    # Beat 9 (Statement-to-Owner reactivity, W5.A2 2026-04-28).
    tools = sorted(b.wait_for.tool for b in waits)  # type: ignore[union-attr]
    assert tools == sorted([
        "emit_install_completed",
        "emit_source_proposed",
        "emit_mcp_call_received",
        "emit_resource_conversation_proposed",
        "emit_resource_conversation_replied",
        "dashboard.tenant_switched",
        "dashboard.research_loaded",
    ])

    # Beats are monotonic in 'at'.
    assert sorted(b.at for b in scen.beats) == [b.at for b in scen.beats]


def test_wait_for_bare_string_form_parses() -> None:
    """``wait_for: <tool>`` shorthand picks up sibling timeout_s + count."""
    yml = """
name: t
default_channel: "#x"
beats:
  - at: 0
    wait_for: emit_install_completed
    timeout_s: 45
    count: 2
"""
    import yaml as _yaml
    data = _yaml.safe_load(yml)
    scen = Scenario.model_validate(data)
    assert len(scen.beats) == 1
    spec = scen.beats[0].wait_for
    assert isinstance(spec, WaitFor)
    assert spec.tool == "emit_install_completed"
    assert spec.timeout_s == 45.0
    assert spec.count == 2


def test_wait_for_structured_form_parses() -> None:
    """``wait_for: {tool, count, timeout_s}`` structured form parses."""
    yml = """
name: t
default_channel: "#x"
beats:
  - at: 0
    wait_for:
      tool: emit_domain_registered
      count: 4
      timeout_s: 20
"""
    import yaml as _yaml
    scen = Scenario.model_validate(_yaml.safe_load(yml))
    spec = scen.beats[0].wait_for
    assert isinstance(spec, WaitFor)
    assert spec.tool == "emit_domain_registered"
    assert spec.count == 4
    assert spec.timeout_s == 20.0


def test_wait_for_rejects_mixed_forms() -> None:
    """Passing a sibling timeout_s alongside the structured form fails."""
    yml = """
name: t
default_channel: "#x"
beats:
  - at: 0
    wait_for:
      tool: emit_x
    timeout_s: 5
"""
    import yaml as _yaml
    with pytest.raises(Exception):
        Scenario.model_validate(_yaml.safe_load(yml))


def test_dm_beat_parses() -> None:
    """``dm: {to, text}`` parses; persona is required."""
    yml = """
name: t
default_channel: "#x"
beats:
  - at: 0
    persona: carol
    dm:
      to: "@WormBase"
      text: "sk_test_demo_key_42"
"""
    import yaml as _yaml
    scen = Scenario.model_validate(_yaml.safe_load(yml))
    beat = scen.beats[0]
    assert beat.persona == "carol"
    assert beat.dm is not None
    assert beat.dm.to == "@WormBase"
    assert beat.dm.text == "sk_test_demo_key_42"


def test_wait_for_rejects_persona() -> None:
    """``wait_for`` beats are engine-driven; persona is forbidden."""
    yml = """
name: t
default_channel: "#x"
beats:
  - at: 0
    persona: carol
    wait_for: emit_x
"""
    import yaml as _yaml
    with pytest.raises(Exception):
        Scenario.model_validate(_yaml.safe_load(yml))


# ---------------------------------------------------------------------------
# Engine-level: wait_for actually polls the ledger and resolves.
# ---------------------------------------------------------------------------


class _FakeLedger:
    """Minimal in-memory ledger: returns the rows it's been told about."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(self, tool: str, kind: str = "execute") -> None:
        self.rows.append({"kind": kind, "payload": {"tool": tool}})

    async def fetch(  # noqa: D401 — Protocol shape
        self, company_id: UUID, until_ts: Any | None = None,
    ) -> list[dict[str, Any]]:
        return list(self.rows)


class _NoopPoster:
    """Drop-in for SlackPoster — never posts."""

    @property
    def client(self) -> Any:  # pragma: no cover — not exercised here
        raise AssertionError("client should not be needed for wait_for-only tests")

    async def post_as(self, persona, channel, text):  # type: ignore[no-untyped-def]
        return {"ok": True}

    async def upload_as(  # type: ignore[no-untyped-def]
        self, persona, channel, file_path, caption=None,
    ):
        return {"ok": True}


@pytest.mark.asyncio
async def test_engine_wait_for_resolves_when_tool_lands(tmp_path: Path) -> None:
    """The engine's wait_for polls the ledger until ``count`` arrivals."""
    pfile = tmp_path / "personas.yml"
    pfile.write_text(
        "personas:\n"
        "  alice:\n"
        "    display_name: Alice\n"
        "    icon_emoji: ':bar_chart:'\n"
        "    role: PM\n",
        encoding="utf-8",
    )
    sfile = tmp_path / "s.yml"
    sfile.write_text(
        "name: t\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 0\n"
        "    wait_for: emit_install_completed\n"
        "    timeout_s: 5\n",
        encoding="utf-8",
    )

    registry = PersonaRegistry.from_yaml(pfile)
    scen = Scenario.from_yaml(sfile)
    ledger = _FakeLedger()
    company = UUID("00000000-0000-0000-0000-000000000001")
    engine = ScenarioEngine(
        registry,
        ledger=ledger,
        company_id=company,
        wait_poll_interval_s=0.01,
    )
    poster = _NoopPoster()

    async def _arrival() -> None:
        # Simulate the dashboard writing the install entry mid-run.
        await asyncio.sleep(0.05)
        ledger.add("emit_install_completed")

    arrival_task = asyncio.create_task(_arrival())
    report = await engine.run(scen, VirtualClock(), poster)  # type: ignore[arg-type]
    await arrival_task

    assert len(report.beats) == 1
    beat = report.beats[0]
    assert beat.kind == "wait_for"
    assert beat.response.get("tool") == "emit_install_completed"
    assert beat.response.get("observed") == 1


@pytest.mark.asyncio
async def test_engine_wait_for_times_out_when_tool_never_lands(
    tmp_path: Path,
) -> None:
    """If the tool never lands within ``timeout_s``, the engine raises."""
    pfile = tmp_path / "personas.yml"
    pfile.write_text(
        "personas:\n"
        "  alice:\n"
        "    display_name: Alice\n"
        "    icon_emoji: ':bar_chart:'\n"
        "    role: PM\n",
        encoding="utf-8",
    )
    sfile = tmp_path / "s.yml"
    sfile.write_text(
        "name: t\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 0\n"
        "    wait_for: emit_never_arrives\n"
        "    timeout_s: 0.05\n",
        encoding="utf-8",
    )
    registry = PersonaRegistry.from_yaml(pfile)
    scen = Scenario.from_yaml(sfile)
    ledger = _FakeLedger()
    company = UUID("00000000-0000-0000-0000-000000000002")
    engine = ScenarioEngine(
        registry,
        ledger=ledger,
        company_id=company,
        wait_poll_interval_s=0.01,
    )

    with pytest.raises(TimeoutError):
        await engine.run(scen, VirtualClock(), _NoopPoster())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_engine_wait_for_only_counts_new_arrivals(
    tmp_path: Path,
) -> None:
    """Pre-existing rows for the tool don't satisfy the wait — only new ones do."""
    pfile = tmp_path / "personas.yml"
    pfile.write_text(
        "personas:\n"
        "  alice:\n"
        "    display_name: Alice\n"
        "    icon_emoji: ':bar_chart:'\n"
        "    role: PM\n",
        encoding="utf-8",
    )
    sfile = tmp_path / "s.yml"
    sfile.write_text(
        "name: t\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 0\n"
        "    wait_for: emit_x\n"
        "    timeout_s: 0.5\n"
        "    count: 1\n",
        encoding="utf-8",
    )
    registry = PersonaRegistry.from_yaml(pfile)
    scen = Scenario.from_yaml(sfile)
    ledger = _FakeLedger()
    # Pre-existing rows. wait_for must NOT be satisfied by these.
    ledger.add("emit_x")
    ledger.add("emit_x")
    company = UUID("00000000-0000-0000-0000-000000000003")
    engine = ScenarioEngine(
        registry,
        ledger=ledger,
        company_id=company,
        wait_poll_interval_s=0.01,
    )

    async def _new_arrival() -> None:
        await asyncio.sleep(0.05)
        ledger.add("emit_x")

    arrival_task = asyncio.create_task(_new_arrival())
    report = await engine.run(scen, VirtualClock(), _NoopPoster())  # type: ignore[arg-type]
    await arrival_task

    assert len(report.beats) == 1
    assert report.beats[0].response.get("observed") == 1


@pytest.mark.asyncio
async def test_engine_wait_for_without_ledger_raises(tmp_path: Path) -> None:
    """An engine without ledger wired in must reject wait_for beats."""
    pfile = tmp_path / "personas.yml"
    pfile.write_text(
        "personas:\n"
        "  alice:\n"
        "    display_name: Alice\n"
        "    icon_emoji: ':bar_chart:'\n"
        "    role: PM\n",
        encoding="utf-8",
    )
    sfile = tmp_path / "s.yml"
    sfile.write_text(
        "name: t\n"
        'default_channel: "#x"\n'
        "beats:\n"
        "  - at: 0\n"
        "    wait_for: emit_x\n"
        "    timeout_s: 1\n",
        encoding="utf-8",
    )
    registry = PersonaRegistry.from_yaml(pfile)
    scen = Scenario.from_yaml(sfile)
    engine = ScenarioEngine(registry)  # no ledger / company_id
    with pytest.raises(RuntimeError, match="wait_for beats require a ledger"):
        await engine.run(scen, VirtualClock(), _NoopPoster())  # type: ignore[arg-type]
