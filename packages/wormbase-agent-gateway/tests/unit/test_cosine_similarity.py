"""Pure-math unit tests for ``_cosine_similarity``.

v2.B Phase 3b adds embedding-similarity clustering to axes 1 (template
promotion) + 3 (bad-pattern). The cosine fn is the substrate — these
tests pin its determinism + numerical stability so cluster behaviour
stays predictable across re-runs.
"""
from __future__ import annotations

from math import sqrt

import pytest

from wormbase_agent_gateway.reactivities import (
    _cluster_by_embedding_similarity,
    _cosine_similarity,
    _entry_embedding,
    _split_by_embedding_presence,
)


# ---------------------------------------------------------------------------
# Identity / orthogonal / opposite — the corner cases of cosine math
# ---------------------------------------------------------------------------


def test_cosine_identity_is_one() -> None:
    """Identical non-zero vectors → cosine 1.0 (within FP eps)."""
    v = [1.0, 2.0, 3.0, 4.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero() -> None:
    """Orthogonal unit vectors → cosine 0.0 exactly."""
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert _cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_opposite_is_minus_one() -> None:
    """Opposite-direction vectors → cosine -1.0."""
    a = [1.0, 2.0, 3.0]
    b = [-1.0, -2.0, -3.0]
    assert _cosine_similarity(a, b) == pytest.approx(-1.0)


def test_cosine_scale_invariant() -> None:
    """Cosine ignores magnitude — scaling doesn't change the result."""
    a = [1.0, 2.0, 3.0]
    b = [10.0, 20.0, 30.0]  # 10× scale, same direction
    assert _cosine_similarity(a, b) == pytest.approx(1.0)


def test_cosine_at_60_degrees() -> None:
    """Two 2-D unit vectors at 60° apart → cosine 0.5."""
    a = [1.0, 0.0]
    b = [0.5, sqrt(3.0) / 2.0]  # 60° rotation
    assert _cosine_similarity(a, b) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Numerical stability
# ---------------------------------------------------------------------------


def test_cosine_zero_vector_returns_zero() -> None:
    """Zero vector → cosine is undefined; we return 0.0 (entries don't
    cluster). Documented in the docstring."""
    z = [0.0, 0.0, 0.0]
    nz = [1.0, 2.0, 3.0]
    assert _cosine_similarity(z, nz) == 0.0
    assert _cosine_similarity(nz, z) == 0.0
    assert _cosine_similarity(z, z) == 0.0


def test_cosine_near_zero_magnitude_returns_zero() -> None:
    """Floating-point near-zero — still returns 0.0 (no NaN escape)."""
    tiny = [1e-310, 1e-310, 1e-310]
    big = [1.0, 1.0, 1.0]
    result = _cosine_similarity(tiny, big)
    # tiny squared is denormalized 0 → norm = 0 → 0.0 by contract.
    assert result == 0.0


def test_cosine_dim_mismatch_raises() -> None:
    """Different-length vectors raise ValueError (catches model swaps)."""
    with pytest.raises(ValueError, match="dim mismatch"):
        _cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])


# ---------------------------------------------------------------------------
# _cluster_by_embedding_similarity — the per-axis clustering primitive
# ---------------------------------------------------------------------------


def _make_outcome_entry(vec: list[float]) -> dict:
    """Build a minimal entry dict matching the cluster_fn's payload
    contract."""
    return {
        "kind": "execute",
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": {
                "nl_question": "test",
                "embedding": vec,
            },
        },
    }


def test_three_similar_embeddings_cluster() -> None:
    """3 vectors with cosine ≥ 0.85 against the first → one cluster of 3."""
    base = [1.0] + [0.0] * 767
    near_a = [1.0, 0.01] + [0.0] * 766
    near_b = [1.0, 0.02] + [0.0] * 766
    entries = [
        _make_outcome_entry(base),
        _make_outcome_entry(near_a),
        _make_outcome_entry(near_b),
    ]
    clusters = _cluster_by_embedding_similarity(entries, threshold=0.85)
    assert len(clusters) == 1
    assert len(clusters[0]) == 3


def test_two_dissimilar_embeddings_dont_cluster() -> None:
    """2 orthogonal vectors → 2 clusters (each its own)."""
    a = [1.0] + [0.0] * 767
    b = [0.0] * 384 + [1.0] + [0.0] * 383  # orthogonal to a
    clusters = _cluster_by_embedding_similarity(
        [_make_outcome_entry(a), _make_outcome_entry(b)],
        threshold=0.85,
    )
    assert len(clusters) == 2
    assert all(len(c) == 1 for c in clusters)


def test_threshold_above_match_threshold_drops_cluster() -> None:
    """Raising the threshold past the actual similarity splits the cluster.

    Lets us verify the `embedding_threshold` factory parameter wires
    through — the same input clusters at 0.85 but not at 0.99.
    """
    a = [1.0, 0.0, 0.0, 0.0]
    b = [0.9, 0.1, 0.0, 0.0]  # cosine ≈ 0.994
    c = [0.5, 0.5, 0.0, 0.0]  # cosine ≈ 0.707
    entries = [_make_outcome_entry(a), _make_outcome_entry(b), _make_outcome_entry(c)]

    # At 0.85 → a+b cluster, c alone.
    clusters_loose = _cluster_by_embedding_similarity(entries, threshold=0.85)
    sizes_loose = sorted(len(c) for c in clusters_loose)
    assert sizes_loose == [1, 2]

    # At 0.99 → a+b still cluster (0.994 > 0.99), c alone.
    clusters_strict = _cluster_by_embedding_similarity(entries, threshold=0.99)
    sizes_strict = sorted(len(c) for c in clusters_strict)
    assert sizes_strict == [1, 2]

    # At 0.999 → all three alone (0.994 < 0.999).
    clusters_strictest = _cluster_by_embedding_similarity(entries, threshold=0.999)
    assert all(len(c) == 1 for c in clusters_strictest)


def test_cluster_skips_entries_without_embedding() -> None:
    """Entries with embedding=None are absent from the embedding clusters."""
    a = [1.0, 0.0]
    entries = [
        _make_outcome_entry(a),
        # No-embedding entry — should be skipped by the embedding cluster_fn
        {
            "kind": "execute",
            "payload": {
                "tool": "emit_query_outcome_recorded",
                "args": {"nl_question": "no embedding here"},
            },
        },
    ]
    clusters = _cluster_by_embedding_similarity(entries, threshold=0.85)
    # Only the embedded entry made it into a cluster.
    flat = [e for c in clusters for e in c]
    assert len(flat) == 1


# ---------------------------------------------------------------------------
# _entry_embedding + _split_by_embedding_presence
# ---------------------------------------------------------------------------


def test_entry_embedding_extracts_vector_as_tuple() -> None:
    """_entry_embedding returns a tuple[float, ...] for hashability."""
    e = _make_outcome_entry([0.1, 0.2, 0.3])
    out = _entry_embedding(e)
    assert out == (0.1, 0.2, 0.3)
    assert isinstance(out, tuple)


def test_entry_embedding_returns_none_when_missing() -> None:
    """Missing / non-list embedding → None."""
    no_emb = {
        "kind": "execute",
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": {"nl_question": "x"},
        },
    }
    assert _entry_embedding(no_emb) is None


def test_split_partitions_by_embedding_presence() -> None:
    """_split returns (embedded, non_embedded) lists in input order."""
    with_emb = _make_outcome_entry([1.0, 0.0])
    no_emb = {
        "kind": "execute",
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": {"nl_question": "x"},
        },
    }
    embedded, non_embedded = _split_by_embedding_presence([with_emb, no_emb, with_emb])
    assert len(embedded) == 2
    assert len(non_embedded) == 1
