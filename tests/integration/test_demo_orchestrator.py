"""L5 integration: demo orchestrator's per-beat auto-recovery (W3.A11).

The demo orchestrator wraps the install-arc-7beat scenario so
``make demo`` succeeds first try, every try. Every beat carries a
``failure_recovery`` directive in the YAML; the orchestrator follows
it on stall.

These tests exercise the recovery decision-tree in **sandbox mode**
(``WORMBASE_DEMO_SKIP_RUN=1``) so the docker-compose stack is not
required. The sandbox switches force each branch of the state machine:

1. Happy-path → every beat succeeds first-try.
2. Forced single-beat timeout → recovery target runs, beat then succeeds.
3. Forced timeout + forced recovery failure → wire-replay fallback.
4. Forced timeout + forced recovery + forced replay failure → halt.

Quality bar: the orchestrator MUST go through wire-replay (not a
direct-ledger-write) for fallback. The test asserts the orchestrator
attempts the canonical fixture rather than bypassing the wire.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = REPO_ROOT / "scripts" / "demo-orchestrator.py"
SCENARIO_YAML = REPO_ROOT / "apps" / "sim-harness" / "scenarios" / "install-arc-7beat.yml"
CANONICAL_FIXTURE = (
    REPO_ROOT / "apps" / "sim-harness" / "fixtures"
    / "install-arc-7beat-canonical.jsonl"
)


# ── module load helper ────────────────────────────────────────────────


def _load_orchestrator():
    """Import the orchestrator script as a module without requiring
    that ``scripts/`` be on sys.path.

    Dataclass post-init resolution looks up ``cls.__module__`` in
    ``sys.modules``, so we register the loaded module there before
    exec — otherwise the dataclass decorator fails with
    ``AttributeError: 'NoneType' object has no attribute '__dict__'``.
    """
    if "demo_orchestrator" in sys.modules:
        return sys.modules["demo_orchestrator"]
    spec = importlib.util.spec_from_file_location(
        "demo_orchestrator", ORCHESTRATOR
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["demo_orchestrator"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── unit-style tests on the loaded module ────────────────────────────


def test_canonical_fixture_exists() -> None:
    """The wire-replay fallback needs a checked-in JSONL fixture."""
    assert CANONICAL_FIXTURE.is_file(), (
        f"canonical fixture missing at {CANONICAL_FIXTURE}; "
        f"regenerate via `wormbase demo wire-record` against a "
        f"known-good run"
    )
    # Every line must be valid JSON with a tool + beat_index.
    n = 0
    with CANONICAL_FIXTURE.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            assert "tool" in rec
            assert "args" in rec
            assert "beat_index" in rec, f"missing beat_index: {rec}"
            n += 1
    assert n >= 4, f"expected ≥4 canonical events, got {n}"


def test_load_scenario_plan_returns_per_beat_plans() -> None:
    """The orchestrator must enumerate every beat with its recovery directive."""
    mod = _load_orchestrator()
    path, plans, raw = mod.load_scenario_plan("install-arc-7beat")
    assert path == SCENARIO_YAML
    assert raw["name"] == "install-arc-7beat"
    assert len(plans) >= 8, f"expected ≥8 beats, got {len(plans)}"
    # Every beat must carry an explicit failure_recovery directive
    # (W3.A11 acceptance: the YAML is the source of truth for recovery
    # paths, not the orchestrator).
    for plan in plans:
        assert plan.failure_recovery in {
            "worm-restart", "adapter-restart", "wire-replay", "beat8-script",
        }, (
            f"beat {plan.index} has unexpected failure_recovery="
            f"{plan.failure_recovery!r}"
        )


def test_beat8_recovery_directive_is_beat8_script() -> None:
    """Beat 8 (Claude Desktop / MCP) uses the canonical script per Block J.

    Beat 8 is identified by ``failure_recovery=beat8-script``; after
    Wave 5 added Beat 9 (Statement-to-Owner), Beat 8 is no longer the
    terminal beat, so we match by directive rather than by index.
    """
    mod = _load_orchestrator()
    _path, plans, _raw = mod.load_scenario_plan("install-arc-7beat")
    beat8_candidates = [p for p in plans if p.failure_recovery == "beat8-script"]
    assert len(beat8_candidates) == 1, (
        f"expected exactly one beat with beat8-script recovery; got "
        f"{len(beat8_candidates)}"
    )


def test_write_single_beat_scenario_strips_failure_recovery(tmp_path: Path) -> None:
    """Slices fed to the engine should not carry the orchestrator-only field."""
    mod = _load_orchestrator()
    _path, plans, raw = mod.load_scenario_plan("install-arc-7beat")
    beat = plans[2]  # bob.drop.sales-q3 — has failure_recovery: adapter-restart
    out = tmp_path / "slice.yml"
    mod.write_single_beat_scenario(
        out_path=out,
        scenario_dict=raw,
        beat=beat,
    )
    text = out.read_text()
    # The slice must not carry the orchestrator directive; the engine
    # ignores extras but a clean YAML is easier to debug.
    assert "failure_recovery" not in text


# ── end-to-end (sandbox) tests on the orchestrator script ─────────────


def _run_orchestrator(env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    base_env = os.environ.copy()
    # Sandbox mode: no docker compose, no make target invocations.
    base_env["WORMBASE_DEMO_SKIP_RUN"] = "1"
    base_env["NO_COLOR"] = "1"
    base_env.update(env_extra)
    return subprocess.run(
        [
            sys.executable,
            str(ORCHESTRATOR),
            "--scenario", "install-arc-7beat",
            "--pace", "virtual",
        ],
        env=base_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.integration
def test_happy_path_all_beats_pass_in_sandbox() -> None:
    """No forced failures → every beat reports first-try success."""
    result = _run_orchestrator(env_extra={})
    assert result.returncode == 0, (
        f"expected exit 0 on happy path, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "all" in result.stdout and "beats passed" in result.stdout
    # Every beat should report "first-try" as the final path.
    assert "via first-try" in result.stdout
    assert "halted" not in result.stdout.lower()


@pytest.mark.integration
def test_recovery_path_runs_when_first_attempt_stalls() -> None:
    """Force beat 3's first attempt to time out; recovery must succeed.

    Beat 3 is the file-drop beat (adapter-restart recovery). The
    orchestrator must run `make adapter-restart` and re-execute the beat.
    """
    result = _run_orchestrator(env_extra={"WORMBASE_DEMO_FAIL_BEAT": "3"})
    assert result.returncode == 0, (
        f"expected exit 0 (recovery succeeds), got {result.returncode}\n"
        f"stdout:\n{result.stdout}"
    )
    assert "first try failed" in result.stdout
    # Beat 3's directive is adapter-restart; the orchestrator must log it.
    assert "adapter-restart" in result.stdout
    assert "✓ beat 3" in result.stdout
    # The summary line for beat 3 must name the path it recovered via.
    assert "via adapter-restart" in result.stdout


@pytest.mark.integration
def test_wire_replay_fallback_when_recovery_fails() -> None:
    """First attempt + recovery both fail → wire-replay backstops the beat.

    Beat 3 (file drop) has matching events in the canonical fixture, so
    wire-replay can land them. Adapter-restart is the declared recovery,
    so the orchestrator must announce wire-replay AFTER attempting that.
    """
    result = _run_orchestrator(env_extra={
        "WORMBASE_DEMO_FAIL_BEAT": "3",
        "WORMBASE_DEMO_FAIL_RECOVERY": "1",
    })
    assert result.returncode == 0, (
        f"expected exit 0 (wire-replay succeeds), got {result.returncode}\n"
        f"stdout:\n{result.stdout}"
    )
    assert "wire-replay" in result.stdout.lower()
    # The orchestrator must announce it's reaching for wire-replay AFTER
    # the recovery attempt — never as a flow-bypass shortcut.
    stdout_lower = result.stdout.lower()
    # Use the declared recovery directive's first appearance vs the
    # first time wire-replay is attempted on the beat.
    second_attempt_idx = stdout_lower.find("second attempt after adapter-restart failed")
    replay_idx = stdout_lower.find("recovered via wire-replay")
    assert 0 < second_attempt_idx < replay_idx, (
        "expected adapter-restart attempt to precede wire-replay fallback"
    )
    # And the beat must succeed via wire-replay, not "first-try".
    assert "via wire-replay" in result.stdout


@pytest.mark.integration
def test_halt_when_wire_replay_also_fails() -> None:
    """All three paths fail → orchestrator halts with a clear message."""
    result = _run_orchestrator(env_extra={
        "WORMBASE_DEMO_FAIL_BEAT": "3",
        "WORMBASE_DEMO_FAIL_RECOVERY": "1",
        "WORMBASE_DEMO_FAIL_REPLAY": "1",
    })
    assert result.returncode == 1, (
        f"expected exit 1 on halted demo, got {result.returncode}\n"
        f"stdout:\n{result.stdout}"
    )
    # The error message must name the specific beat + recovery paths.
    assert "HALTED on beat 3" in result.stdout
    assert "wire-replay fallback failed" in result.stdout
    assert "human-in-the-loop required" in result.stdout
    # State preservation note is part of the halt copy.
    assert "stack state preserved" in result.stdout


@pytest.mark.integration
def test_orchestrator_reports_attempts_per_beat() -> None:
    """The summary names every recovery path attempted on each beat."""
    result = _run_orchestrator(env_extra={
        "WORMBASE_DEMO_FAIL_BEAT": "4",
    })
    assert result.returncode == 0
    # Beat 4 (bob.say.stripe-mention) has adapter-restart recovery, and
    # the summary line should list "first-try, recovery:adapter-restart".
    assert "✓ beat 4" in result.stdout
    assert "first-try, recovery:adapter-restart" in result.stdout


@pytest.mark.integration
def test_orchestrator_writes_json_report(tmp_path: Path) -> None:
    """``--report PATH`` produces a machine-readable run summary."""
    report_path = tmp_path / "run.json"
    base_env = os.environ.copy()
    base_env["WORMBASE_DEMO_SKIP_RUN"] = "1"
    base_env["NO_COLOR"] = "1"
    result = subprocess.run(
        [
            sys.executable, str(ORCHESTRATOR),
            "--scenario", "install-arc-7beat",
            "--pace", "virtual",
            "--report", str(report_path),
        ],
        env=base_env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout
    assert report_path.is_file()
    payload = json.loads(report_path.read_text())
    assert payload["scenario"] == "install-arc-7beat"
    assert payload["passed"] is True
    assert len(payload["beats"]) >= 8
    for beat in payload["beats"]:
        assert beat["succeeded"] is True
        assert beat["final_path"] in {
            "first-try", "worm-restart", "adapter-restart",
            "wire-replay", "beat8-script",
        }
