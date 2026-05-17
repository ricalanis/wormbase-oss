"""H.1 Regression test: process-worm has no static dep on wormbase_core.

Per **D3** synthesis (see
``docs/superpowers/plans/2026-05-03-process-worm-extraction.md``):
``data_product_actions`` stays in ``wormbase_core``. Process-worm uses
**lazy imports inside Reactivity ``fire()`` bodies** (mirrors
``apps/worm-core/src/wormbase_core/reactivities/phenomenon_gaps.py:431``)
to avoid a circular dependency.

This test catches a future regression where someone adds a top-level
``from wormbase_core import ...`` to a process-worm module — which would
re-introduce the circular dependency that motivated the extraction.

A subprocess is used for hermetic isolation: pytest's session-wide
``sys.modules`` may already contain ``wormbase_core`` because other
tests imported it. A fresh subprocess gives a clean module cache.
"""

import subprocess
import sys


def test_process_worm_has_no_static_dep_on_worm_core() -> None:
    """Importing ``wormbase_process_extractor`` MUST NOT pull
    ``wormbase_core`` into ``sys.modules``.

    Lazy imports inside ``fire()`` bodies are sanctioned (mirrors the
    ``phenomenon_gaps.py:431`` pattern). Static imports create a
    circular dependency: worm-core imports process-worm Reactivities
    via the factory, and a static back-edge would deadlock import
    resolution.
    """
    probe = (
        "import wormbase_process_extractor; "
        "import sys; "
        "leaked = [m for m in sys.modules if m == 'wormbase_core' "
        "or m.startswith('wormbase_core.')]; "
        "assert not leaked, "
        "f'static dep on wormbase_core: {sorted(leaked)}'; "
        "print('OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"subprocess failed:\nstdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )
    assert "OK" in result.stdout
