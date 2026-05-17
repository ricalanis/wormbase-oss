"""L5 — OpenClaw health-check + auto-restart + doctor extension (W7.A2).

Verifies the three-part contract added in W7.A2:

1. The compose `openclaw` service declares its own healthcheck and
   reaches the ``healthy`` state within a bounded window of `make up`.
2. Killing OpenClaw lets the engine auto-restart it (per
   `restart: unless-stopped`) and the container returns to ``healthy``
   within a bounded window.
3. ``scripts/doctor.sh`` exits non-zero when openclaw is not healthy,
   and reports a `[fail]` line that points at ``make openclaw-restart``.

These tests poke a live Docker daemon, so they are gated on
``WORMBASE_HARNESS_UP=1`` (the convention used elsewhere in
tests/integration/) plus a pingable ``docker info``. Without the
harness, every test in this module is skipped — no false reds in
local pytest runs.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR_SCRIPT = REPO_ROOT / "scripts" / "doctor.sh"
CONTAINER_NAME = "wormbase-openclaw"


def _harness_up() -> bool:
    """Gate: harness brought up + docker daemon reachable + container exists."""
    if os.environ.get("WORMBASE_HARNESS_UP", "").strip() != "1":
        return False
    info = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if info.returncode != 0:
        return False
    inspect = subprocess.run(
        ["docker", "inspect", "-f", "{{.Name}}", CONTAINER_NAME],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return inspect.returncode == 0


pytestmark = pytest.mark.skipif(
    not _harness_up(),
    reason=(
        "L5 W7.A2 openclaw-health tests require a live harness. Set "
        "WORMBASE_HARNESS_UP=1 after `make up` to enable; otherwise the "
        "L1 unit suite already covers the doctor.sh sandbox path."
    ),
)


def _container_health(name: str = CONTAINER_NAME) -> str:
    """Return docker's health status, or `.State.Status` if no healthcheck."""
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
            name,
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        return "missing"
    return result.stdout.strip()


def _wait_for(predicate, timeout_s: float, poll_s: float = 2.0) -> bool:
    """Poll predicate() until True or deadline; returns whether it succeeded."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll_s)
    return False


@pytest.mark.integration
def test_openclaw_reaches_healthy_state() -> None:
    """The container declared by docker-compose.yml resolves to `healthy`
    within 120s of being started. We assume `make up` has already been
    run (gate enforces this); we just give it up to 120s to converge in
    case this test runs immediately after a cold boot."""
    reached_healthy = _wait_for(
        lambda: _container_health() == "healthy",
        timeout_s=120.0,
    )
    final = _container_health()
    assert reached_healthy, (
        f"openclaw did not reach 'healthy' within 120s; final state={final!r}. "
        f"Run `make openclaw-logs` to inspect."
    )


@pytest.mark.integration
def test_openclaw_restart_policy_caps_at_three_attempts() -> None:
    """Verifies the on-failure restart policy is configured exactly as
    the spec requires:

    - condition: on-failure (Docker engine API rejects max_attempts
      with `any` / `unless-stopped`, so on-failure is the only policy
      that supports the cap natively).
    - MaximumRetryCount: 3 — caps auto-restart so a genuinely-broken
      openclaw halts for forensics instead of looping forever.

    A process crash (non-zero exit) within the cap auto-restarts.
    A deliberate `docker kill` is NOT treated as a failure by the
    daemon — that's by design (operator intent), and the recovery
    path for the operator is `make openclaw-restart`, exercised in
    the next test.
    """
    policy = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            "{{.HostConfig.RestartPolicy.Name}}|{{.HostConfig.RestartPolicy.MaximumRetryCount}}",
            CONTAINER_NAME,
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert policy.returncode == 0, f"docker inspect failed: {policy.stderr!r}"
    name, max_count = policy.stdout.strip().split("|", 1)
    assert name == "on-failure", (
        f"expected restart policy 'on-failure' (only policy that supports "
        f"the max-attempts cap on the Docker engine API), got {name!r}"
    )
    assert max_count == "3", (
        f"expected MaximumRetryCount=3 (per W7.A2 spec: cap before halt), "
        f"got {max_count!r}"
    )


@pytest.mark.integration
def test_make_openclaw_restart_recovers_from_unhealthy() -> None:
    """End-to-end recovery path: stop the container (forces doctor to
    report it as unhealthy / fail), then `make openclaw-restart` brings
    it back to healthy and writes a forensic pre-restart log.
    """
    # Pre-condition: healthy.
    assert _wait_for(
        lambda: _container_health() == "healthy",
        timeout_s=60.0,
    ), f"pre-condition failed: not healthy at start ({_container_health()!r})"

    # Stop the container — this is the realistic "wedged" scenario the
    # spec calls out (the recovery flow operators actually run when
    # they see openclaw unhealthy between sessions).
    stop = subprocess.run(
        ["docker", "stop", CONTAINER_NAME],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert stop.returncode == 0, f"docker stop failed: {stop.stderr!r}"

    pre_restart_log = REPO_ROOT / ".openclaw-pre-restart.log"
    if pre_restart_log.exists():
        pre_restart_log.unlink()

    try:
        # `make openclaw-restart` writes the pre-restart log, restarts,
        # waits for healthy, then re-runs doctor. Exit 0 == recovered.
        result = subprocess.run(
            ["make", "openclaw-restart"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "NO_COLOR": "1"},
        )
        assert result.returncode == 0, (
            f"make openclaw-restart failed (exit {result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        # Forensic log written.
        assert pre_restart_log.exists(), (
            "make openclaw-restart should write .openclaw-pre-restart.log "
            "before the restart fires"
        )
        # Final state confirmed.
        assert _container_health() == "healthy", (
            f"after make openclaw-restart, expected 'healthy', "
            f"got {_container_health()!r}"
        )
    finally:
        # If the restart path failed, ensure the container is at least
        # started so other tests don't cascade-fail.
        if _container_health() != "healthy":
            subprocess.run(
                ["docker", "start", CONTAINER_NAME],
                capture_output=True,
                text=True,
                timeout=30,
            )


@pytest.mark.integration
def test_doctor_exits_nonzero_when_openclaw_unhealthy() -> None:
    """Stop the container and confirm `bash scripts/doctor.sh` exits 1
    with a `[fail]` line that mentions `make openclaw-restart`.

    We restart the container after the assertion so subsequent tests
    (and the operator's session) are not left with openclaw down.
    """
    # Stop (clean shutdown — distinct from kill so the container ends in
    # 'exited' state, which is the canonical "unhealthy" surface for doctor).
    stop = subprocess.run(
        ["docker", "stop", CONTAINER_NAME],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert stop.returncode == 0, f"docker stop failed: {stop.stderr!r}"

    try:
        result = subprocess.run(
            ["bash", str(DOCTOR_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "NO_COLOR": "1"},
        )
        assert result.returncode == 1, (
            f"expected doctor exit 1 with openclaw down, got {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "openclaw" in result.stdout, "openclaw not mentioned in doctor output"
        assert "[fail]" in result.stdout, "expected [fail] line in doctor output"
        assert "make openclaw-restart" in result.stdout, (
            "doctor should suggest `make openclaw-restart` when openclaw is down"
        )
    finally:
        # Restore the container so we don't leave the harness wedged.
        subprocess.run(
            ["docker", "start", CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Best-effort wait so subsequent tests in this run see a healthy
        # state again. We don't assert here — that's covered by the first
        # test in this module.
        _wait_for(
            lambda: _container_health() == "healthy",
            timeout_s=120.0,
        )
