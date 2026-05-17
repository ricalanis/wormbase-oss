"""Smoke test that the package is importable as a workspace member."""
from __future__ import annotations


def test_package_importable() -> None:
    import wormbase_research_loop

    assert wormbase_research_loop.__name__ == "wormbase_research_loop"
