"""L5 integration: demo orchestrator's ``--skip-installed`` mode (W7.A3).

Beat 1 of the install-arc scenario waits for ``emit_install_completed``,
which is only emitted after a human clicks through the OAuth consent
screen at ``/onboarding``. The orchestrator cannot script the click,
so when an install row already exists for the target tenant we
short-circuit straight to Beat 2 — letting ``make demo`` run
unattended after a one-time OAuth seed.

These tests exercise the skip decision-tree in **sandbox mode**
(``WORMBASE_DEMO_SKIP_RUN=1``) so the docker-compose stack and
worm-core HTTP API are not required. The
``WORMBASE_DEMO_SKIP_INSTALLED_FAKE`` env switch drives the install
probe deterministically:

  - ``absent``   → no install row found → run every beat normally
  - ``present``  → an active install row → skip
                   ``skippable_if_pre_installed: true`` beats
  - ``unknown``  → probe failure → run every beat with a warning

Quality bar: only beats explicitly marked
``skippable_if_pre_installed: true`` in the YAML may be skipped. The
``--no-skip-installed`` flag must override the auto-detection. Errors
during the probe must NOT cause a silent skip — they fall through to
the full arc with a logged warning.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = REPO_ROOT / "scripts" / "demo-orchestrator.py"
SCENARIO_YAML = (
    REPO_ROOT / "apps" / "sim-harness" / "scenarios"
    / "install-arc-7beat.yml"
)


# ── module load helper (mirrors test_demo_orchestrator.py) ────────────


def _load_orchestrator():
    """Import the orchestrator script as a module without requiring
    that ``scripts/`` be on sys.path.
    """
    if "demo_orchestrator" in sys.modules:
        return sys.modules["demo_orchestrator"]
    spec = importlib.util.spec_from_file_location(
        "demo_orchestrator", ORCHESTRATOR,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["demo_orchestrator"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_orchestrator(
    *,
    env_extra: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
    report_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the orchestrator script in sandbox mode with extra args."""
    base_env = os.environ.copy()
    base_env["WORMBASE_DEMO_SKIP_RUN"] = "1"
    base_env["NO_COLOR"] = "1"
    if env_extra:
        base_env.update(env_extra)
    cmd: list[str] = [
        sys.executable,
        str(ORCHESTRATOR),
        "--scenario", "install-arc-7beat",
        "--pace", "virtual",
    ]
    if extra_args:
        cmd.extend(extra_args)
    if report_path is not None:
        cmd.extend(["--report", str(report_path)])
    return subprocess.run(
        cmd, env=base_env, capture_output=True, text=True, timeout=60,
    )


# ── YAML wiring ───────────────────────────────────────────────────────


def test_scenario_yaml_marks_only_oauth_beats_skippable() -> None:
    """Only Beats 1a/1b carry ``skippable_if_pre_installed: true``.

    The OAuth-click beat (1a) and its companion default-lake source
    wait_for (1b) are the only beats that an active-install row makes
    redundant. Every other beat MUST run regardless of install state.
    """
    raw = yaml.safe_load(SCENARIO_YAML.read_text(encoding="utf-8"))
    beats = raw.get("beats") or []
    skippable_indices = [
        idx for idx, b in enumerate(beats, start=1)
        if bool(b.get("skippable_if_pre_installed"))
    ]
    assert skippable_indices == [1, 2], (
        f"expected only Beats 1+2 (the OAuth-click pair) to be skippable; "
        f"got {skippable_indices}"
    )


def test_load_scenario_plan_carries_skippable_flag() -> None:
    """``BeatPlan`` must surface the YAML's ``skippable_if_pre_installed``."""
    mod = _load_orchestrator()
    _path, plans, _raw = mod.load_scenario_plan("install-arc-7beat")
    skippable = [p for p in plans if p.skippable_if_pre_installed]
    assert len(skippable) == 2, (
        f"expected exactly 2 skippable beats; got {len(skippable)}"
    )
    assert {p.index for p in skippable} == {1, 2}
    # And conversely: every non-1/2 beat must NOT be skippable. A stray
    # ``skippable_if_pre_installed`` on a non-OAuth beat would let
    # `--skip-installed` silently drop legitimate work.
    for plan in plans:
        if plan.index not in {1, 2}:
            assert plan.skippable_if_pre_installed is False, (
                f"beat {plan.index} unexpectedly marked skippable"
            )


# ── probe helper unit-tests ───────────────────────────────────────────


def test_probe_returns_present_in_sandbox_when_fake_present(caplog) -> None:
    mod = _load_orchestrator()
    # Sandbox + FAKE=present → InstallProbeResult(state="present").
    os.environ["WORMBASE_DEMO_SKIP_INSTALLED_FAKE"] = "present"
    try:
        import logging
        log = logging.getLogger("test.probe")
        result = mod._probe_existing_install(
            log=log, sandbox=True, runner=None,
        )
    finally:
        del os.environ["WORMBASE_DEMO_SKIP_INSTALLED_FAKE"]
    assert result.state == "present"
    assert len(result.installs) == 1
    assert result.installs[0]["status"] == "active"


def test_probe_returns_absent_in_sandbox_when_fake_absent() -> None:
    mod = _load_orchestrator()
    os.environ["WORMBASE_DEMO_SKIP_INSTALLED_FAKE"] = "absent"
    try:
        import logging
        log = logging.getLogger("test.probe")
        result = mod._probe_existing_install(
            log=log, sandbox=True, runner=None,
        )
    finally:
        del os.environ["WORMBASE_DEMO_SKIP_INSTALLED_FAKE"]
    assert result.state == "absent"
    assert result.installs == []


def test_probe_returns_unknown_in_sandbox_when_fake_unknown() -> None:
    mod = _load_orchestrator()
    os.environ["WORMBASE_DEMO_SKIP_INSTALLED_FAKE"] = "unknown"
    try:
        import logging
        log = logging.getLogger("test.probe")
        result = mod._probe_existing_install(
            log=log, sandbox=True, runner=None,
        )
    finally:
        del os.environ["WORMBASE_DEMO_SKIP_INSTALLED_FAKE"]
    assert result.state == "unknown"
    assert "forced" in result.detail


# ── end-to-end (sandbox) tests ────────────────────────────────────────


@pytest.mark.integration
def test_pre_existing_install_skips_oauth_beats(tmp_path: Path) -> None:
    """Sandbox + FAKE=present → Beats 1+2 skipped, Beats 3+ run normally.

    The orchestrator must:
      - log ``skipping beat 1`` and ``skipping beat 2`` with a reason
        naming ``skippable_if_pre_installed=true`` plus an install id;
      - print the summary line ``skipped 2 beats due to pre-existing
        install``;
      - record ``final_path=skipped-pre-installed`` in the JSON report
        for Beats 1 and 2 (and ``first-try`` for the rest);
      - exit 0.
    """
    report_path = tmp_path / "run.json"
    result = _run_orchestrator(
        env_extra={"WORMBASE_DEMO_SKIP_INSTALLED_FAKE": "present"},
        report_path=report_path,
    )
    assert result.returncode == 0, (
        f"expected exit 0 with skip-installed; got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    # Each skip must emit a clear, parseable log line.
    assert "skipping beat 1" in result.stdout
    assert "skipping beat 2" in result.stdout
    assert "skippable_if_pre_installed=true" in result.stdout
    # The summary tally lands at the bottom of the run.
    assert "skipped 2 beats due to pre-existing install" in result.stdout
    # And no false skips: Beat 3 (file drop, NOT skippable) must run.
    assert "skipping beat 3" not in result.stdout
    assert "✓ beat 3" in result.stdout

    # Report shape: the two skipped beats land as
    # ``final_path=skipped-pre-installed`` with succeeded=True.
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    by_idx = {b["beat_index"]: b for b in payload["beats"]}
    assert by_idx[1]["final_path"] == "skipped-pre-installed"
    assert by_idx[1]["succeeded"] is True
    assert by_idx[1]["skip_reason"]
    assert "install" in by_idx[1]["skip_reason"]
    assert by_idx[2]["final_path"] == "skipped-pre-installed"
    assert by_idx[2]["succeeded"] is True
    # Beat 3 must NOT be skipped.
    assert by_idx[3]["final_path"] != "skipped-pre-installed"
    assert by_idx[3]["succeeded"] is True


@pytest.mark.integration
def test_no_existing_install_runs_every_beat() -> None:
    """Sandbox + FAKE=absent → Beats 1+2 run normally, no skip messages.

    This is the fresh-install path. The probe returns ``absent``, so the
    orchestrator must NOT log any ``skipping beat`` lines and must
    record first-try success for every beat.
    """
    result = _run_orchestrator(
        env_extra={"WORMBASE_DEMO_SKIP_INSTALLED_FAKE": "absent"},
    )
    assert result.returncode == 0, result.stdout
    # No skip log lines on a fresh-install run.
    assert "skipping beat" not in result.stdout
    assert "skipped 0 beats" not in result.stdout
    assert "skipped" not in (
        result.stdout.split("─── summary ───")[-1].lower()
    ), (
        "fresh-install run must not advertise any skips in the summary "
        "tally"
    )
    # The probe should report explicitly that no install was found.
    assert "no active install" in result.stdout
    # All beats reach execute_beat — every visible beat line is "✓ beat N"
    # (the existing test suite already asserts the canonical 8+ beats).
    assert "✓ beat 1" in result.stdout
    assert "✓ beat 2" in result.stdout


@pytest.mark.integration
def test_no_skip_installed_flag_overrides_detection() -> None:
    """``--no-skip-installed`` forces every beat to run even when an
    install exists.

    Even with FAKE=present in the env, the explicit override must
    short-circuit the probe and run the full arc — operators may want
    to exercise the OAuth-click beats against a pre-seeded tenant for
    regression testing.
    """
    result = _run_orchestrator(
        env_extra={"WORMBASE_DEMO_SKIP_INSTALLED_FAKE": "present"},
        extra_args=["--no-skip-installed"],
    )
    assert result.returncode == 0, result.stdout
    # The flag must be acknowledged in the startup line and no skip
    # messages should appear.
    assert "--no-skip-installed set" in result.stdout
    assert "skipping beat" not in result.stdout
    # Every beat ran via the normal path.
    assert "✓ beat 1" in result.stdout
    assert "✓ beat 2" in result.stdout


@pytest.mark.integration
def test_probe_unknown_falls_through_to_running_all_beats() -> None:
    """Probe failure (network flake / 5xx) → run every beat + warn.

    Quality bar: errors during the probe must NOT cause silent skips.
    The orchestrator must run every beat with a logged warning so the
    operator can investigate the probe failure post-run.
    """
    result = _run_orchestrator(
        env_extra={"WORMBASE_DEMO_SKIP_INSTALLED_FAKE": "unknown"},
    )
    assert result.returncode == 0, result.stdout
    # No skip lines — the probe failure must NOT be misinterpreted as
    # "install present".
    assert "skipping beat" not in result.stdout
    # The orchestrator must log the probe failure explicitly.
    assert "install probe state=unknown" in result.stdout
    assert "running every beat normally to be safe" in result.stdout
    # Every beat ran.
    assert "✓ beat 1" in result.stdout
    assert "✓ beat 2" in result.stdout


@pytest.mark.integration
def test_skipped_beats_count_toward_report_passed() -> None:
    """A run that skips Beats 1+2 still reports ``passed=True``."""
    result = _run_orchestrator(
        env_extra={"WORMBASE_DEMO_SKIP_INSTALLED_FAKE": "present"},
    )
    assert result.returncode == 0, result.stdout
    # The orchestrator's "all beats passed" line still fires when some
    # beats skipped (skipped beats are counted as succeeded — their
    # invariant is upheld by the seeded data).
    assert "all" in result.stdout and "beats passed" in result.stdout
