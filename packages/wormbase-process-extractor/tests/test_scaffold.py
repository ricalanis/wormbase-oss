"""Smoke tests for A.1 scaffold of wormbase-process-extractor."""


def test_module_importable() -> None:
    import wormbase_process_extractor

    assert wormbase_process_extractor is not None


def test_module_docstring_present() -> None:
    import wormbase_process_extractor

    assert wormbase_process_extractor.__doc__
    assert "Process-worm" in wormbase_process_extractor.__doc__


def test_all_includes_block_b1_predicate() -> None:
    """B.1 populates __all__ with the first public re-export.

    Subsequent blocks append to ``__all__``; this test asserts the B.1
    contract — the predicate is exposed at the package surface.
    """
    import wormbase_process_extractor

    assert "MatchesDecisionPattern" in wormbase_process_extractor.__all__
