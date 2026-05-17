"""Block A — package scaffolding sanity.

Verifies the workspace registers ``wormbase-inference-router`` and the
public surface exposed at the current block boundary is importable.
The full surface (Block B/C/D/E/F/G symbols) gets re-asserted in
``test_full_surface.py`` once Blocks E + G land.
"""
from __future__ import annotations


def test_package_imports_cleanly() -> None:
    import wormbase_inference  # noqa: F401


def test_block_b_surface_present() -> None:
    import wormbase_inference as I

    expected = {"RouteRequest", "RouteResponse", "Router", "default_backend"}
    assert expected.issubset(set(I.__all__))
    for name in expected:
        assert hasattr(I, name), name


def test_block_cd_surface_present() -> None:
    import wormbase_inference as I

    expected = {
        "DEFAULT_GEMMA_MODEL",
        "DEFAULT_KIMI_MODEL",
        "DEFAULT_OLLAMA_BASE",
        "DEFAULT_OLLAMA_OWN_BASE",
        "GemmaClient",
        "InferenceClient",
        "InferenceError",
        "KimiClient",
    }
    assert expected.issubset(set(I.__all__))
    for name in expected:
        assert hasattr(I, name), name


def test_block_e_surface_present() -> None:
    import wormbase_inference as I

    expected = {
        "CachedRouter",
        "InferenceCache",
        "NullInferenceCache",
        "SqliteInferenceCache",
        "build_default_router",
        "make_cache_key",
    }
    assert expected.issubset(set(I.__all__))
    for name in expected:
        assert hasattr(I, name), name


def test_block_g_surface_present() -> None:
    import wormbase_inference as I

    assert "DecisionLLMClient" in I.__all__
    assert hasattr(I, "DecisionLLMClient")
