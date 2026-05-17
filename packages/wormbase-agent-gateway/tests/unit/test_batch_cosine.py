"""Unit tests for the numpy-vectorized batch cosine + v2 clustering.

2026-05-14 carry-forward #3 — pins ``_batch_cosine_matrix`` and
``_cluster_by_embedding_similarity_v2`` against the same numerical
contract as the scalar ``_cosine_similarity`` primitive, plus the
byte-identical-partition guarantee against the v1 legacy impl.

The byte-identity tests are the contract that the perf optimization
ships without changing clustering semantics. They use seeded inputs
that share a single resolved-domain bucket (the v1 → v2 invariant
holds within a bucket; cross-bucket divergence is intentional and
documented on ``_cluster_by_embedding_similarity_v2``).
"""
from __future__ import annotations

import random
from math import sqrt

import numpy as np
import pytest

from wormbase_agent_gateway.reactivities import (
    _batch_cosine_matrix,
    _cluster_by_embedding_similarity,
    _cluster_by_embedding_similarity_legacy,
    _cluster_by_embedding_similarity_v2,
    _CLUSTERING_IMPL,
    _cosine_similarity,
)


# ---------------------------------------------------------------------------
# _batch_cosine_matrix — numerical contract
# ---------------------------------------------------------------------------


def test_batch_cosine_empty_returns_empty_matrix() -> None:
    """No embeddings → 0x0 matrix, no exception."""
    out = _batch_cosine_matrix([])
    assert out.shape == (0, 0)
    assert out.dtype == np.float32


def test_batch_cosine_identity_diagonal_is_one() -> None:
    """Self-similarity of every non-zero row is 1.0 (within float32 eps)."""
    embeddings = [
        [1.0, 2.0, 3.0],
        [0.5, 0.5, 0.5],
        [-1.0, 2.0, -3.0],
    ]
    out = _batch_cosine_matrix(embeddings)
    diag = np.diag(out)
    np.testing.assert_allclose(diag, [1.0, 1.0, 1.0], atol=1e-6)


def test_batch_cosine_orthogonal_pair_is_zero() -> None:
    """Two orthogonal unit vectors → cosine 0.0 in the off-diagonal."""
    out = _batch_cosine_matrix([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    assert out[0, 1] == pytest.approx(0.0, abs=1e-6)
    assert out[1, 0] == pytest.approx(0.0, abs=1e-6)


def test_batch_cosine_opposite_pair_is_minus_one() -> None:
    """Two opposite-direction vectors → cosine -1.0 in the off-diagonal."""
    out = _batch_cosine_matrix([[1.0, 2.0, 3.0], [-1.0, -2.0, -3.0]])
    assert out[0, 1] == pytest.approx(-1.0, abs=1e-6)
    assert out[1, 0] == pytest.approx(-1.0, abs=1e-6)


def test_batch_cosine_60_degree_gives_half() -> None:
    """Two 2-D unit vectors at 60° apart → cosine 0.5."""
    a = [1.0, 0.0]
    b = [0.5, sqrt(3.0) / 2.0]
    out = _batch_cosine_matrix([a, b])
    assert out[0, 1] == pytest.approx(0.5, abs=1e-6)


def test_batch_cosine_zero_row_returns_zero_to_everyone() -> None:
    """Zero-norm vector → cosine 0.0 to every other row AND to itself.

    Documented Phase-3b semantics: zero vectors don't cluster.
    """
    out = _batch_cosine_matrix([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]])
    assert out[0, 0] == 0.0
    assert out[0, 1] == 0.0
    assert out[1, 0] == 0.0
    # Non-zero row's self-similarity is still 1.0
    assert out[1, 1] == pytest.approx(1.0, abs=1e-6)


def test_batch_cosine_scale_invariant() -> None:
    """Cosine ignores magnitude — scaled-up vectors give 1.0."""
    out = _batch_cosine_matrix([[1.0, 2.0, 3.0], [10.0, 20.0, 30.0]])
    assert out[0, 1] == pytest.approx(1.0, abs=1e-6)


def test_batch_cosine_dim_mismatch_raises() -> None:
    """Ragged input → ValueError (matches scalar primitive contract)."""
    with pytest.raises(ValueError, match="dim mismatch|inhomogeneous"):
        _batch_cosine_matrix([[1.0, 2.0], [1.0, 2.0, 3.0]])


def test_batch_cosine_matches_scalar_pairwise_on_random_input() -> None:
    """For random seeded vectors, batch matrix matches scalar pairwise
    cosines within float32 precision (~1e-6)."""
    rng = random.Random(0xBEEF)
    vecs = [
        [rng.gauss(0.0, 1.0) for _ in range(64)] for _ in range(8)
    ]
    matrix = _batch_cosine_matrix(vecs)
    for i in range(len(vecs)):
        for j in range(len(vecs)):
            scalar = _cosine_similarity(vecs[i], vecs[j])
            np.testing.assert_allclose(matrix[i, j], scalar, atol=1e-5)


def test_batch_cosine_scales_to_500_vectors() -> None:
    """500 vectors of 768-dim → 500x500 matrix in milliseconds. Sanity
    that BLAS is doing the heavy lifting; no exception, finite output."""
    rng = random.Random(0xC0DE)
    vecs = [[rng.gauss(0.0, 1.0) for _ in range(768)] for _ in range(500)]
    out = _batch_cosine_matrix(vecs)
    assert out.shape == (500, 500)
    assert np.isfinite(out).all()


# ---------------------------------------------------------------------------
# v2 clustering — first-fit assignment correctness
# ---------------------------------------------------------------------------


def _make_outcome_entry(
    vec: list[float] | None,
    *,
    domain_id: str = "d",
    nl_question: str = "test",
) -> dict:
    """Build a minimal entry dict matching the cluster_fn's payload."""
    args: dict = {"nl_question": nl_question}
    if vec is not None:
        args["embedding"] = vec
    args["final_query_spec"] = {"domain_id": domain_id}
    return {
        "kind": "execute",
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": args,
        },
    }


def test_v2_empty_input_returns_empty_partition() -> None:
    assert _cluster_by_embedding_similarity_v2([]) == []


def test_v2_skips_no_embedding_entries() -> None:
    """Entries without an embedding are excluded (hybrid handles them)."""
    entries = [
        _make_outcome_entry([1.0, 0.0, 0.0]),
        _make_outcome_entry(None),
    ]
    clusters = _cluster_by_embedding_similarity_v2(entries, threshold=0.85)
    flat = [e for c in clusters for e in c]
    assert len(flat) == 1


def test_v2_clusters_near_duplicate_vectors() -> None:
    """3 nearly-identical vectors at threshold 0.85 → one cluster."""
    base = [1.0, 0.0, 0.0, 0.0]
    entries = [
        _make_outcome_entry(base),
        _make_outcome_entry([1.0, 0.01, 0.0, 0.0]),
        _make_outcome_entry([1.0, 0.02, 0.0, 0.0]),
    ]
    clusters = _cluster_by_embedding_similarity_v2(entries, threshold=0.85)
    assert len(clusters) == 1
    assert len(clusters[0]) == 3


def test_v2_orthogonal_vectors_dont_cluster() -> None:
    entries = [
        _make_outcome_entry([1.0, 0.0, 0.0]),
        _make_outcome_entry([0.0, 1.0, 0.0]),
        _make_outcome_entry([0.0, 0.0, 1.0]),
    ]
    clusters = _cluster_by_embedding_similarity_v2(entries, threshold=0.85)
    assert len(clusters) == 3
    assert all(len(c) == 1 for c in clusters)


def test_v2_buckets_by_domain() -> None:
    """Two near-duplicate vectors in DIFFERENT domains → two clusters.

    This is the documented intentional divergence vs v1: v1 would have
    merged them; v2 keeps them separate, matching the downstream
    ``(domain, intent)`` partition key.
    """
    vec = [1.0, 0.0, 0.0]
    entries = [
        _make_outcome_entry(vec, domain_id="dom-a"),
        _make_outcome_entry(vec, domain_id="dom-b"),
    ]
    clusters = _cluster_by_embedding_similarity_v2(entries, threshold=0.85)
    # Two singleton clusters, NOT one cluster of two.
    assert len(clusters) == 2
    assert all(len(c) == 1 for c in clusters)


def test_v2_dispatcher_routes_to_vectorized() -> None:
    """``_CLUSTERING_IMPL = 'vectorized'`` (the default) routes the public
    dispatcher to the v2 implementation."""
    assert _CLUSTERING_IMPL == "vectorized"
    # Behavioural check: dispatcher result == v2 result on a fixed input.
    entries = [
        _make_outcome_entry([1.0, 0.0]),
        _make_outcome_entry([0.99, 0.05]),
    ]
    dispatcher_out = _cluster_by_embedding_similarity(entries, threshold=0.85)
    v2_out = _cluster_by_embedding_similarity_v2(entries, threshold=0.85)
    assert _partition_signature(dispatcher_out) == _partition_signature(v2_out)


# ---------------------------------------------------------------------------
# Byte-identical-partition vs v1 legacy — the core contract
# ---------------------------------------------------------------------------


def _partition_signature(
    clusters: list[list[dict]],
) -> set[frozenset[int]]:
    """Convert a list-of-list-of-entries to a set-of-frozensets keyed on
    Python object identity. Two equivalent partitions yield equal
    signatures regardless of cluster ordering."""
    return {frozenset(id(e) for e in c) for c in clusters}


def _seeded_outcomes_one_domain(
    n: int,
    *,
    n_clusters: int,
    seed: int,
    jitter: float = 0.005,
    domain_id: str = "dom-shared",
) -> list[dict]:
    """Generate ``n`` outcomes split into ``n_clusters`` near-duplicate
    clusters, all under ONE resolved domain so v1/v2 byte-identity
    holds. Mirrors the perf-suite seed shape."""
    rng = random.Random(seed)
    centers = [[rng.gauss(0.0, 1.0) for _ in range(64)] for _ in range(n_clusters)]
    entries: list[dict] = []
    for i in range(n):
        c = i % n_clusters
        vec = [v + rng.gauss(0.0, jitter) for v in centers[c]]
        entries.append(
            _make_outcome_entry(
                vec,
                domain_id=domain_id,
                nl_question=f"q-{c}-{i}",  # varied intents to confirm
                                            # bucketing is by domain only
            ),
        )
    return entries


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6, 7, 8])
def test_v2_partition_byte_identical_to_legacy_seeded(seed: int) -> None:
    """Across 8 seeded fixtures, v2 partition equals v1 partition.

    Same-domain bucketing → both impls walk all entries in the same
    first-fit order → identical partition. Numerical precision diff
    (float32 vs float64) is far below the 0.85 threshold.
    """
    entries = _seeded_outcomes_one_domain(
        n=50, n_clusters=5, seed=seed,
    )
    v1 = _cluster_by_embedding_similarity_legacy(entries, threshold=0.85)
    v2 = _cluster_by_embedding_similarity_v2(entries, threshold=0.85)
    assert _partition_signature(v1) == _partition_signature(v2), (
        f"seed={seed}: v1 had {len(v1)} clusters, v2 had {len(v2)}; "
        f"partitions diverge"
    )


def test_v2_partition_byte_identical_under_high_threshold() -> None:
    """At threshold 0.99 (most entries isolated) v1 == v2."""
    entries = _seeded_outcomes_one_domain(n=30, n_clusters=10, seed=42)
    v1 = _cluster_by_embedding_similarity_legacy(entries, threshold=0.99)
    v2 = _cluster_by_embedding_similarity_v2(entries, threshold=0.99)
    assert _partition_signature(v1) == _partition_signature(v2)


def test_v2_partition_byte_identical_under_worst_case_distinct_vectors() -> None:
    """All-distinct random vectors (no jitter) → every entry its own
    cluster in both v1 + v2 (the worst-case scaling regime)."""
    rng = random.Random(0xFACE)
    entries = [
        _make_outcome_entry(
            [rng.gauss(0.0, 1.0) for _ in range(64)],
            domain_id="dom-distinct",
            nl_question=f"q-{i}",
        )
        for i in range(40)
    ]
    v1 = _cluster_by_embedding_similarity_legacy(entries, threshold=0.85)
    v2 = _cluster_by_embedding_similarity_v2(entries, threshold=0.85)
    assert _partition_signature(v1) == _partition_signature(v2)
    # And: every entry is its own cluster
    assert all(len(c) == 1 for c in v2)
    assert len(v2) == len(entries)


def test_v2_partition_byte_identical_with_mixed_dim_skipping() -> None:
    """Entries with mismatched embedding dims → v1 starts a new cluster
    (skips the rep compare); v2 splits them into per-dim sub-buckets.
    Both produce the same partition: each dim-incompatible entry is
    isolated unless others share its dim."""
    base_a = [1.0, 0.0, 0.0]
    base_b = [1.0, 0.01, 0.0]  # near-dup of base_a
    odd_dim = [1.0, 1.0, 1.0, 1.0]  # different dim → can't compare
    entries = [
        _make_outcome_entry(base_a, domain_id="d"),
        _make_outcome_entry(base_b, domain_id="d"),
        _make_outcome_entry(odd_dim, domain_id="d"),
    ]
    v1 = _cluster_by_embedding_similarity_legacy(entries, threshold=0.85)
    v2 = _cluster_by_embedding_similarity_v2(entries, threshold=0.85)
    assert _partition_signature(v1) == _partition_signature(v2)
