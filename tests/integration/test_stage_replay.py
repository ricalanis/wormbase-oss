"""L5 integration: P14 two-tenant determinism stage demo.

Drives ``scripts/stage_replay_demo.py`` through ``make stage-replay-
demo`` (and equivalent bash wrapper) and asserts:

* Exit 0 — the byte-identical determinism proof carried.
* Both terminal hashes appear in stdout, and they are equal.
* Wall-clock <120s on a stock laptop.
* Re-running on a clean process produces the same hash (idempotent
  determinism — the canonical fixture replays bit-for-bit each time).

Council Q8 (McKinney) is the load-bearing acceptance: this test is
what proves the stage demo will land. PRD §6 Q8 + §7 P14.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "stage_replay_demo.sh"
PY_DRIVER = REPO_ROOT / "scripts" / "stage_replay_demo.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "install_arc.jsonl"


# A 64-char hex blob, optionally split by whitespace (the script
# renders the hash in 16-char chunks for projector readability).
_HASH_LINE_RE = re.compile(
    r"^\s*hash\s*│\s*([0-9a-f\s]+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_hashes(stdout: str) -> list[str]:
    """Return the list of hex hashes found in the stage banner output.

    The driver prints two ``hash │ <chunked-hex>`` lines (one per
    tenant). We compress whitespace so the chunked rendering folds
    back into a 64-char hex string for comparison.
    """
    hashes: list[str] = []
    for m in _HASH_LINE_RE.finditer(stdout):
        compact = re.sub(r"\s+", "", m.group(1))
        hashes.append(compact.lower())
    return hashes


def _run_stage_demo() -> tuple[int, str, str, float]:
    """Invoke the bash wrapper; return (rc, stdout, stderr, elapsed_s)."""
    assert SCRIPT.exists(), f"missing stage demo script: {SCRIPT}"
    started = time.perf_counter()
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "PYTHONPATH": ""},
    )
    elapsed = time.perf_counter() - started
    return proc.returncode, proc.stdout, proc.stderr, elapsed


def test_stage_demo_assets_present() -> None:
    """Pre-flight: the script + fixture are checked in.

    A presenter cloning the repo should find this turnkey on the
    demo machine. If any of these is missing, the demo will fail
    on stage, so guard explicitly.
    """
    assert SCRIPT.exists(), f"missing wrapper: {SCRIPT}"
    assert SCRIPT.stat().st_mode & 0o111, f"wrapper not executable: {SCRIPT}"
    assert PY_DRIVER.exists(), f"missing driver: {PY_DRIVER}"
    assert FIXTURE.exists(), f"missing canonical fixture: {FIXTURE}"
    assert FIXTURE.stat().st_size > 0, "fixture is empty"


def test_stage_demo_exits_zero_with_matching_hashes() -> None:
    """`make stage-replay-demo` returns 0 and shows two equal hashes."""
    rc, stdout, stderr, _elapsed = _run_stage_demo()
    assert rc == 0, (
        f"stage-replay-demo exited {rc}\n"
        f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    )
    assert "BYTE-IDENTICAL DETERMINISM CONFIRMED" in stdout, (
        f"verdict banner missing\nstdout:\n{stdout}"
    )

    hashes = _extract_hashes(stdout)
    assert len(hashes) == 2, (
        f"expected exactly two hash lines, got {len(hashes)}; stdout:\n{stdout}"
    )
    assert all(len(h) == 64 for h in hashes), (
        f"hashes wrong length: {[len(h) for h in hashes]}; lines: {hashes}"
    )
    assert hashes[0] == hashes[1], (
        f"hashes diverged: tenant_a={hashes[0]} tenant_b={hashes[1]}"
    )


def test_stage_demo_runs_under_two_minutes() -> None:
    """PRD §7 P14 quality bar: <2 min on a stock laptop."""
    rc, _stdout, _stderr, elapsed = _run_stage_demo()
    assert rc == 0
    assert elapsed < 120.0, f"stage demo took {elapsed:.1f}s, exceeds 120s budget"


def test_stage_demo_is_idempotent_across_runs() -> None:
    """Re-running on a clean process yields the same hash (the whole
    point of C2 determinism — no per-process clock or RNG leaks)."""
    rc1, stdout1, _e1, _t1 = _run_stage_demo()
    rc2, stdout2, _e2, _t2 = _run_stage_demo()
    assert rc1 == 0 and rc2 == 0

    h1 = _extract_hashes(stdout1)
    h2 = _extract_hashes(stdout2)
    assert h1 and h2
    assert h1[0] == h2[0], (
        f"hash drifted across runs: run1={h1[0]} run2={h2[0]}"
    )


def test_stage_demo_python_driver_directly() -> None:
    """Sanity: the python driver runs without the bash wrapper too.

    Useful when an operator wants to embed it in another harness
    (e.g. a CI gate) without a shell.
    """
    proc = subprocess.run(
        [sys.executable, str(PY_DRIVER), "--fixture", str(FIXTURE)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"driver exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    hashes = _extract_hashes(proc.stdout)
    assert len(hashes) == 2 and hashes[0] == hashes[1]


def test_stage_demo_fails_closed_on_missing_fixture(tmp_path: Path) -> None:
    """Pre-flight: a non-existent fixture should exit 2, not 0.

    Guards against silent passes if the canonical JSONL goes missing.
    """
    missing = tmp_path / "does_not_exist.jsonl"
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--fixture", str(missing)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2, (
        f"expected rc=2 on missing fixture, got {proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )


@pytest.mark.parametrize(
    "label",
    ["TENANT A", "TENANT B"],
)
def test_stage_demo_renders_per_tenant_banner(label: str) -> None:
    """Stage frame must visibly name each tenant — back-row readability."""
    rc, stdout, _stderr, _t = _run_stage_demo()
    assert rc == 0
    assert label in stdout, (
        f"expected banner '{label}' in stdout; got:\n{stdout}"
    )
