"""Local conftest for chaos tests.

Auto-tags every test in this directory with the ``chaos`` marker so
``pytest -m chaos`` works even if individual files forget to declare it.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    chaos_marker = pytest.mark.chaos
    for item in items:
        if "tests/chaos/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(chaos_marker)
