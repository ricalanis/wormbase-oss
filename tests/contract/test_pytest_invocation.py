"""Contract test for O-B6 — cross-package pytest collection from repo root.

Each package has its own `tests/conftest.py` and its tests live under a
`tests/` namespace. Running `pytest packages/` from the workspace root
collides on the `tests.conftest` module name (44 collection errors as of
2026-05-04), so cross-package collection from root is unsupported by
design.

This test pins the contract:

1. Calling `uv run pytest packages/ --collect-only` from the workspace
   root must NOT silently succeed-with-collisions. It must either:
     - exit 0 (no collision — collection actually clean), or
     - exit 4 (no tests collected — explicit "use the per-package
       invocation"), or
     - exit non-zero with a clear collision message AND the documented
       workaround (`make test-all`) is available.

2. The Makefile must expose a `test-all` target that loops package-by-
   package so the full Python suite is reachable from a single command.

3. `CLAUDE.md` (workspace root) must document the per-package invocation
   pattern so future contributors don't burn time rediscovering it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pytest_packages_collection_is_documented() -> None:
    """`pytest packages/ --collect-only` must not be silently broken.

    Either the collection works (exit 0), or the workspace must surface
    a documented workaround. We accept exit code 4 (no tests collected)
    as the "explicit no-op" signal, and we accept any non-zero exit as
    long as `make test-all` exists in the Makefile.
    """
    result = subprocess.run(
        ["uv", "run", "pytest", "packages/", "--collect-only", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # Acceptable: clean collection, OR explicit no-op, OR documented workaround.
    if result.returncode in (0, 4):
        return

    # Non-zero exit is acceptable IFF `make test-all` is documented as
    # the workaround. We assert both the Makefile target and the
    # CLAUDE.md note exist.
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert re.search(r"^test-all:", makefile, re.MULTILINE), (
        "pytest packages/ collection failed with exit "
        f"{result.returncode}, but Makefile has no `test-all` target. "
        "Either fix the collision or add `make test-all` per the "
        "deferred-backlog plan O-B6.\n\n"
        f"stderr tail:\n{result.stderr[-2000:]}"
    )

    claude_md = (REPO_ROOT / "CLAUDE.md").read_text()
    assert "test-all" in claude_md or "per-package" in claude_md.lower(), (
        "Makefile has `test-all` but CLAUDE.md does not document the "
        "per-package pytest invocation. Add a `Test invocation` note "
        "per the deferred-backlog plan O-B6."
    )


def test_makefile_has_test_all_target() -> None:
    """Makefile must expose a `test-all` target loop-running per-package tests."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert re.search(r"^test-all:", makefile, re.MULTILINE), (
        "Makefile is missing the `test-all` target documented by O-B6."
    )
    # Sanity: target body should iterate `packages/*/`.
    assert "packages/*/" in makefile, (
        "`test-all` target is present but doesn't loop over `packages/*/`."
    )


def test_claude_md_documents_pytest_invocation() -> None:
    """CLAUDE.md must surface the per-package pytest invocation pattern."""
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text()
    # Either a section header or a clear directive about per-package tests.
    has_marker = (
        "Test invocation" in claude_md
        or "test-all" in claude_md
        or "per-package" in claude_md.lower()
    )
    assert has_marker, (
        "CLAUDE.md is missing the O-B6 note documenting that "
        "`pytest packages/` from the workspace root is unsupported and "
        "the supported alternatives are `make test-all` or "
        "`uv run pytest packages/<name>/tests/`."
    )
