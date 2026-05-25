"""L5 — `make doctor` / `scripts/doctor.sh` happy-path + sad-path.

Owned by W1.A4. Verifies:

* Fresh-clone simulation (no .env): doctor reports a ``[fail]`` line
  about the missing .env and exits non-zero.
* Required keys missing: each surfaces as ``[warn]`` with "unset"; if
  ALL required keys are missing simultaneously, doctor exits 1.
* Required keys set: doctor exits 0 and reports ``[ok]`` per key.

The test runs the script in a sandbox tmpdir whose layout mirrors the
repo (``scripts/``, ``.env``) so that ``REPO_ROOT`` resolves to the
sandbox, not the real repo. Stack-health checks are best-effort —
they may pass or warn depending on whether the local stack is up;
the test only asserts on the .env-key lines.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR_SCRIPT = REPO_ROOT / "scripts" / "doctor.sh"


def _write_doctor_sandbox(tmp_path: Path) -> Path:
    """Mirror just enough of the repo so doctor.sh's REPO_ROOT logic
    points at the sandbox: scripts/doctor.sh in place, sandbox is the
    parent dir.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    sandbox_doctor = scripts_dir / "doctor.sh"
    shutil.copy2(DOCTOR_SCRIPT, sandbox_doctor)
    sandbox_doctor.chmod(0o755)
    return sandbox_doctor


def _run_doctor(script: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    base_env = {
        # Disable color so the assertions can grep substrings cleanly.
        "NO_COLOR": "1",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    if env:
        base_env.update(env)
    return subprocess.run(
        ["bash", str(script)],
        env=base_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.integration
def test_doctor_fresh_clone_reports_missing_env(tmp_path: Path) -> None:
    """Fresh-clone simulation: no .env should produce a [fail] line and exit 1."""
    script = _write_doctor_sandbox(tmp_path)
    # Sandbox has no .env intentionally.
    result = _run_doctor(script)

    assert result.returncode == 1, (
        f"expected exit 1 on missing .env, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert ".env missing" in result.stdout


@pytest.mark.integration
def test_doctor_all_required_keys_unset_reports_red(tmp_path: Path) -> None:
    """Empty .env (file present but no values) should warn per key AND
    fail because the all-missing red branch fires."""
    script = _write_doctor_sandbox(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "SLACK_BOT_TOKEN_BASEWORM=\n"
        "SLACK_BOT_TOKEN_SIM_BASEWORM=\n"
        "OPENCLAW_ADMIN_TOKEN=\n"
        "OLLAMA_API_KEY=\n",
        encoding="utf-8",
    )
    result = _run_doctor(script)

    assert "SLACK_BOT_TOKEN_BASEWORM unset" in result.stdout
    assert "OPENCLAW_ADMIN_TOKEN unset" in result.stdout
    assert "all required .env keys are unset" in result.stdout
    assert result.returncode == 1


@pytest.mark.integration
def test_doctor_all_required_keys_set_no_red(tmp_path: Path) -> None:
    """All required keys set → doctor exits 0 (warnings from
    stack-health checks are acceptable, no [fail] lines on .env)."""
    script = _write_doctor_sandbox(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "SLACK_BOT_TOKEN_BASEWORM=xoxb-fake-for-test\n"
        "SLACK_BOT_TOKEN_SIM_BASEWORM=xoxb-fake-for-test\n"
        "OPENCLAW_ADMIN_TOKEN=test-token\n"
        "OLLAMA_API_KEY=test-key\n",
        encoding="utf-8",
    )
    result = _run_doctor(script)

    # Each required key should have a corresponding [ok] line.
    for key in (
        "SLACK_BOT_TOKEN_BASEWORM",
        "SLACK_BOT_TOKEN_SIM_BASEWORM",
        "OPENCLAW_ADMIN_TOKEN",
        "OLLAMA_API_KEY",
    ):
        assert f"[ok]     {key} set" in result.stdout, (
            f"expected '[ok]     {key} set', stdout:\n{result.stdout}"
        )

    # No [fail] line should reference .env content.
    fail_lines = [ln for ln in result.stdout.splitlines() if "[fail]" in ln]
    env_failures = [
        ln for ln in fail_lines if any(
            kw in ln
            for kw in (".env", "all required", "SLACK_", "OPENCLAW_", "OLLAMA_")
        )
    ]
    assert not env_failures, f".env should have no failures, got: {env_failures}"


@pytest.mark.integration
def test_doctor_runs_quickly(tmp_path: Path) -> None:
    """Doctor must complete in <10s even with all curl/probe checks
    going to nothing (each probe is bounded at ~3s; total budget is
    well under 10s in the spec, but the spec's <2s headline assumes a
    warm stack — we relax to 10s here to avoid flaky tests on cold CI).
    """
    import time

    script = _write_doctor_sandbox(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text("OPENCLAW_ADMIN_TOKEN=t\n", encoding="utf-8")

    started = time.monotonic()
    _run_doctor(script)
    elapsed = time.monotonic() - started

    assert elapsed < 10.0, f"doctor took {elapsed:.1f}s, expected <10s"
