"""L6 demo-gate conftest.

Auto-tags every test in `tests/demo/` with the `demo` marker so
`pytest -m demo` and `make demo-gates` select them. Each demo gate
file maps 1:1 to a PRD §6 acceptance criterion (F1-F9, Q1-Q4, N1-N4).
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    demo_marker = pytest.mark.demo
    for item in items:
        if "tests/demo/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(demo_marker)
