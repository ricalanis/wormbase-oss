"""Smoke test that the package is importable as a workspace member."""
from __future__ import annotations


def test_package_importable() -> None:
    import wormbase_chat_presence

    assert wormbase_chat_presence.__name__ == "wormbase_chat_presence"
