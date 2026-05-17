"""Local conftest for L3 contract tests — pure-Python, no Docker."""

from __future__ import annotations

import pytest


# Ensure every test in this directory carries the contract marker so
# `make test-contract` (or `pytest -m contract`) selects them cleanly,
# even if individual files forget to declare it.
def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    contract_marker = pytest.mark.contract
    for item in items:
        if "tests/contract/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(contract_marker)
