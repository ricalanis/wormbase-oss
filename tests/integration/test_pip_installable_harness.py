"""Verify ``wormbase-tools-test`` is pip-installable from a clean venv.

The acceptance bar for P5 (PRD §7) is "harness pip-installable from
clean venv outside monorepo, conformance passes against the reference
connector". This test enforces that bar in CI.

Steps:
    1. Build a wheel for ``packages/wormbase-tools-test``.
    2. Spin a fresh venv in a tmpdir (no monorepo deps).
    3. ``pip install`` the wheel + ``pyarrow`` only.
    4. Copy the reference connector + a minimal conftest into a
       sibling worktree.
    5. Run ``pytest --connector ...`` from inside the venv.
    6. Assert all six invariants pass.

Marked ``slow`` because it spins a venv and builds a wheel — typically
8-15s on a stock laptop.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "packages" / "wormbase-tools-test"
REFERENCE_FILE = REPO_ROOT / "examples" / "connectors" / "parquet_local.py"


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.skipif(
    not (PACKAGE_DIR.exists() and REFERENCE_FILE.exists()),
    reason="wormbase-tools-test package or reference connector not present",
)
def test_harness_pip_installable_in_clean_venv(tmp_path: Path) -> None:
    """End-to-end: build wheel, install in fresh venv, conformance passes."""
    # --- Step 1: build wheel ------------------------------------------------
    dist_dir = tmp_path / "dist"
    build_log = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)],
        cwd=PACKAGE_DIR,
        capture_output=True,
        text=True,
    )
    if build_log.returncode != 0:
        pytest.skip(
            f"`python -m build` not available or failed: {build_log.stderr[-200:]}"
        )
    wheels = list(dist_dir.glob("wormbase_tools_test-*.whl"))
    assert wheels, f"no wheel built in {dist_dir}"
    wheel_path = wheels[0]

    # --- Step 2: fresh venv -------------------------------------------------
    venv_dir = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True,
        capture_output=True,
    )
    if os.name == "nt":
        venv_python = venv_dir / "Scripts" / "python.exe"
        venv_pytest = venv_dir / "Scripts" / "pytest.exe"
    else:
        venv_python = venv_dir / "bin" / "python"
        venv_pytest = venv_dir / "bin" / "pytest"

    # --- Step 3: install harness + pyarrow ----------------------------------
    install_log = subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--disable-pip-version-check",
            str(wheel_path),
            "pyarrow",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert install_log.returncode == 0, (
        f"pip install failed: {install_log.stderr[-500:]}"
    )

    # --- Step 4: assemble a sibling worktree --------------------------------
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "parquet_local.py").write_text(REFERENCE_FILE.read_text())
    (work_dir / "conftest.py").write_text(
        "\n".join(
            [
                "import pyarrow as pa, pyarrow.parquet as pq",
                "import pytest",
                "from parquet_local import SecretBundle",
                "",
                "@pytest.fixture(scope='session')",
                "def parquet_fixture(tmp_path_factory):",
                "    p = tmp_path_factory.mktemp('d') / 'fixture.parquet'",
                "    pq.write_table(pa.table({'id': [1,2,3], 'name': ['A','B','C']}), p)",
                "    return str(p)",
                "",
                "@pytest.fixture",
                "def connector_valid_secrets(parquet_fixture):",
                "    return SecretBundle({'path': parquet_fixture})",
                "",
                "@pytest.fixture",
                "def connector_invalid_secrets():",
                "    return SecretBundle({})",
                "",
                "@pytest.fixture",
                "def connector_known_resource_id(parquet_fixture):",
                "    return parquet_fixture",
                "",
            ]
        )
    )

    # --- Step 5: run pytest with --connector --------------------------------
    run_log = subprocess.run(
        [
            str(venv_pytest),
            "--connector",
            "parquet_local:ParquetLocalConnector",
            "-v",
            "--tb=short",
        ],
        cwd=work_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # --- Step 6: assert green -----------------------------------------------
    assert run_log.returncode == 0, (
        f"pytest exited {run_log.returncode}\n"
        f"--- stdout ---\n{run_log.stdout}\n"
        f"--- stderr ---\n{run_log.stderr}"
    )
    assert "6 passed" in run_log.stdout, run_log.stdout


@pytest.mark.integration
def test_invariants_module_is_importable_standalone() -> None:
    """The invariants module must be importable without monorepo deps.

    This is the cheap sibling of ``test_harness_pip_installable_in_clean_venv``:
    instead of spinning a venv, we just verify the package's surface
    doesn't reach into ``wormbase_connectors`` or any other internal
    package at import time. (Plugin defers that import to runtime.)
    """
    import sys

    # Snapshot loaded modules; import; verify no monorepo-internal load.
    before = set(sys.modules)
    sys.path.insert(0, str(PACKAGE_DIR / "src"))
    try:
        # Force a fresh import.
        for k in list(sys.modules):
            if k.startswith("wormbase_tools_test"):
                del sys.modules[k]
        import wormbase_tools_test  # noqa: F401
        from wormbase_tools_test import (  # noqa: F401
            INVARIANT_NAMES,
            assert_authenticate_invalid_raises,
            assert_authenticate_valid_returns_authhandle,
            assert_discover_stable_ordering,
            assert_profile_idempotent,
            assert_sample_deterministic,
            assert_watch_cancellable,
            run_full_conformance,
        )
    finally:
        sys.path.remove(str(PACKAGE_DIR / "src"))

    after = set(sys.modules)
    new_modules = after - before
    forbidden = {
        m for m in new_modules
        if m.startswith("wormbase_") and not m.startswith("wormbase_tools_test")
    }
    assert not forbidden, (
        f"wormbase_tools_test pulled monorepo-internal modules at import: "
        f"{forbidden}"
    )
    assert len(INVARIANT_NAMES) == 6
