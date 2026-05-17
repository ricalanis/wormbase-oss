"""Smoke test that the package is importable as a workspace member."""
from __future__ import annotations


def test_package_importable() -> None:
    import wormbase_lake_maintainer

    assert wormbase_lake_maintainer.__name__ == "wormbase_lake_maintainer"
