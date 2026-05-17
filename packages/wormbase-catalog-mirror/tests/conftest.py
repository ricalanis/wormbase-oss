"""Catalog-mirror test fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).parent


@pytest.fixture
def jaffle_shop_manifest_path() -> Path:
    return TESTS_ROOT / "fixtures" / "jaffle_shop_manifest.json"
