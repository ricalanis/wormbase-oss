"""L5 smoke — `make tutorial` / `scripts/tutorial.sh` static checks.

Owned by W1.A4. The tutorial orchestrates a multi-minute cold-start
flow (docker compose up, image pulls, seeds, browser open). Booting
a sandbox compose project just to assert "ledger has install row
within 90s" would make this test environmental and slow.

Instead we verify the contracts the spec actually owns:

* The script halts cleanly when doctor fails (fresh-clone simulation).
* The script's structure references the documented commands —
  `bash scripts/doctor.sh`, `make up` / docker compose up, `wormbase
  demo seed --reset-first`, and a browser-open of `/onboarding`.
* The script propagates `WORMBASE_INSTALLER_EMAIL_OVERRIDE` for
  xoxb-token installs (the spec's "fallback for xoxb tokens" behavior).
* The script is idempotent in shape — uses `--reset-first` on every
  seed so a re-run produces the same end-state.

End-to-end behavioral validation (90s install row in ledger) is
covered by `tests/integration/test_install_60s_sla.py` and the live
demo gates; that gate is the canonical source of truth and this
smoke test deliberately stays static.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TUTORIAL_SCRIPT = REPO_ROOT / "scripts" / "tutorial.sh"
DOCTOR_SCRIPT = REPO_ROOT / "scripts" / "doctor.sh"


@pytest.mark.integration
def test_tutorial_script_exists_and_executable() -> None:
    assert TUTORIAL_SCRIPT.exists(), "scripts/tutorial.sh missing"
    assert os.access(TUTORIAL_SCRIPT, os.X_OK), (
        "scripts/tutorial.sh not executable; run chmod +x"
    )


@pytest.mark.integration
def test_tutorial_calls_doctor_first() -> None:
    """Step 1 of the tutorial spec: run doctor, halt on red."""
    text = TUTORIAL_SCRIPT.read_text(encoding="utf-8")
    assert "scripts/doctor.sh" in text, "tutorial must invoke doctor.sh"
    # The halt-on-red path must exit 1 + tell the user to fix.
    assert "doctor reported red" in text


@pytest.mark.integration
def test_tutorial_brings_stack_up_with_retry() -> None:
    """Step 2: docker compose up with retry-on-EOF / network flake."""
    text = TUTORIAL_SCRIPT.read_text(encoding="utf-8")
    assert "compose" in text and "up -d" in text
    # Retry loop guarded by max_attempts.
    assert "max_attempts" in text
    # EOF / network-flake heuristics from spec.
    assert "EOF" in text


@pytest.mark.integration
def test_tutorial_seeds_two_tenants_with_reset() -> None:
    """Steps 4-5: baseworm + democorp, both with --reset-first."""
    text = TUTORIAL_SCRIPT.read_text(encoding="utf-8")
    assert "--tenant baseworm" in text
    assert "--domain-pack saas" in text
    assert "--tenant democorp" in text
    assert "--domain-pack marketplace" in text
    # Idempotency: every seed call uses --reset-first.
    seed_invocations = [
        ln for ln in text.splitlines()
        if "wormbase demo seed" in ln or "demo seed" in ln
    ]
    assert seed_invocations, "tutorial must call wormbase demo seed"
    for ln in seed_invocations:
        # Allow trailing-line continuations; check the surrounding block.
        block_start = text.find(ln)
        block_end = text.find("\n\n", block_start)
        if block_end == -1:
            block_end = block_start + 500
        block = text[block_start:block_end]
        assert "--reset-first" in block, (
            f"seed without --reset-first breaks idempotency:\n{ln}"
        )


@pytest.mark.integration
def test_tutorial_propagates_email_override_for_xoxb_install() -> None:
    """xoxb tokens carry no profile email; the override is required."""
    text = TUTORIAL_SCRIPT.read_text(encoding="utf-8")
    assert "WORMBASE_INSTALLER_EMAIL_OVERRIDE" in text
    assert "--install-from-env" in text


@pytest.mark.integration
def test_tutorial_opens_onboarding_url() -> None:
    """Step 6: open the browser at /onboarding/welcome (or /onboarding)."""
    text = TUTORIAL_SCRIPT.read_text(encoding="utf-8")
    assert "localhost:3000" in text
    assert "/onboarding" in text
    # Uses macOS `open` with xdg-open as Linux fallback.
    assert "open " in text
    assert "xdg-open" in text


@pytest.mark.integration
def test_tutorial_halts_when_doctor_fails(tmp_path: Path) -> None:
    """Sandbox: stub doctor.sh that always exits 1; run tutorial.sh in
    that sandbox; assert tutorial exits non-zero before reaching the
    `make up` step. Validates the halt-on-red contract end-to-end.
    """
    sandbox_scripts = tmp_path / "scripts"
    sandbox_scripts.mkdir()

    # Stub doctor that always reports red.
    stub_doctor = sandbox_scripts / "doctor.sh"
    stub_doctor.write_text(
        "#!/usr/bin/env bash\n"
        "echo '  [fail]   stub doctor (forced red)'\n"
        "exit 1\n",
        encoding="utf-8",
    )
    stub_doctor.chmod(0o755)

    # Real tutorial.sh — copies into sandbox so REPO_ROOT resolves to
    # tmp_path (not the real wormbase repo).
    sandbox_tutorial = sandbox_scripts / "tutorial.sh"
    shutil.copy2(TUTORIAL_SCRIPT, sandbox_tutorial)
    sandbox_tutorial.chmod(0o755)

    # Need a docker shim so the script does not actually try to reach
    # the daemon. Tutorial halts at step 1 anyway, but a paranoid guard
    # in case PATH is ever inherited differently.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_shim = bin_dir / "docker"
    docker_shim.write_text(
        "#!/usr/bin/env bash\necho 'docker shim — should not be reached'\nexit 99\n",
        encoding="utf-8",
    )
    docker_shim.chmod(0o755)

    env = {
        "NO_COLOR": "1",
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path),
    }

    result = subprocess.run(
        ["bash", str(sandbox_tutorial)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 1, (
        f"tutorial should halt on doctor red; got exit {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # Should have halted BEFORE attempting docker compose up.
    assert "Step 2/6" not in result.stdout, (
        "tutorial advanced past step 1 even though doctor failed"
    )
    assert "doctor reported red" in result.stdout
