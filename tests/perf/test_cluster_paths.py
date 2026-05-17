"""Path C benchmarks — cosine cluster_fn vs substring cluster_fn.

Path C measures clustering throughput of the two production cluster
functions in ``wormbase_agent_gateway.reactivities``:

* ``_cluster_by_embedding_similarity`` — single-pass first-fit cosine
  clustering at threshold 0.85. O(N · clusters_so_far · dim).
* ``_cluster_by_canonical_intent`` — substring grouping by
  ``(domain_id, canonical_intent)``. O(N).

The cosine path is the dominant Phase 3b code path; the substring
path is the legacy fallback for entries that lack an embedding. The
benchmark establishes both absolute cost and the cosine vs substring
ratio so a future Phase-4 optimization (e.g. LSH, hierarchical
clustering, batched cosine) can be graded against a real baseline.

Key questions:

* Does cosine scale O(N²) as expected, or does first-fit + cluster-cap
  keep it linear-ish in practice?
* What is the cost ratio at N=100, 500, 1000?
* Where does cosine become the dominant cost relative to gather?

Methodology limits:

* 768-dim embeddings (current production model).
* All clusters fall under the 0.85 threshold (jitter < 0.01) — this
  is a CLUSTERING workload, not a NO-CLUSTERING workload. A different
  fixture with all-distinct vectors would measure the worst case.
"""

from __future__ import annotations

import json

import pytest

from wormbase_agent_gateway.reactivities import (
    _cluster_by_canonical_intent,
    _cluster_by_embedding_similarity,
    _cosine_similarity,
)

from .conftest import (
    EMBEDDING_DIM,
    emit_report_line,
    make_seeded_rng,
    make_vector,
    seed_outcome_entries,
    summarize,
    time_sync,
)


# ---------------------------------------------------------------------------
# Path C — cosine cluster_fn scaling
# ---------------------------------------------------------------------------


@pytest.mark.perf
@pytest.mark.parametrize("n_entries", [10, 50, 100, 500, 1000])
def test_path_c_cosine_cluster_walltime(n_entries: int) -> None:
    """Wall-clock for cosine clustering N entries.

    Five seed clusters → at threshold 0.85 + jitter 0.005 the
    expected cluster count is 5 regardless of N, so cluster_so_far
    stays bounded and the algorithm is essentially O(N · 5 · 768).
    """
    entries = seed_outcome_entries(
        n_entries, n_clusters=5, with_embedding=True,
    )

    def _run() -> None:
        _cluster_by_embedding_similarity(entries, threshold=0.85)

    samples = time_sync(_run, warmup=2, n_samples=10)
    result = summarize(f"path_c_cosine_n={n_entries}", samples)
    emit_report_line("path_c_cosine", json.dumps(result.as_row()))

    # Sanity: with 5 seed clusters + jitter < 0.01, we expect ≤ ~10 clusters.
    out = _cluster_by_embedding_similarity(entries, threshold=0.85)
    total_clustered = sum(len(c) for c in out)
    assert total_clustered == n_entries  # all placed
    assert len(out) <= 20  # bounded cluster count


@pytest.mark.perf
@pytest.mark.parametrize("n_entries", [10, 50, 100, 500, 1000])
def test_path_c_substring_cluster_walltime(n_entries: int) -> None:
    """Wall-clock for substring (canonical_intent) clustering N entries.

    O(N) dict-grouping. The reference baseline against which the
    cosine path is judged.
    """
    entries = seed_outcome_entries(
        n_entries, n_clusters=5, with_embedding=False,
    )

    def _run() -> None:
        _cluster_by_canonical_intent(entries)

    samples = time_sync(_run, warmup=2, n_samples=20)
    result = summarize(f"path_c_substring_n={n_entries}", samples)
    emit_report_line("path_c_substring", json.dumps(result.as_row()))


@pytest.mark.perf
def test_path_c_cosine_worst_case_no_clusters() -> None:
    """Cosine clustering when NO entries match — worst case scaling.

    With all-distinct vectors (no jitter), every entry starts a new
    cluster. ``cluster_so_far`` grows linearly with N → cost per
    iteration is O(N · dim), total cost O(N² · dim). This is the
    quadratic regime the v2.B Phase 3b plan flagged for future
    optimization (LSH / hierarchical / batched cosine).
    """
    n_entries = 200
    rng = make_seeded_rng()
    # All-distinct: every vector is fresh gaussian, no jitter.
    entries: list[dict] = []
    for i in range(n_entries):
        vec = make_vector(rng)
        entries.append(
            {
                "kind": "execute",
                "payload": {
                    "tool": "emit_query_outcome_recorded",
                    "args": {
                        "agent_query_id": f"aq-{i}",
                        "nl_question": f"q{i}",
                        "quality_score": "0.95",
                        "used": True,
                        "useful": True,
                        "domain_id": "d",
                        "embedding": vec,
                    },
                },
            },
        )

    def _run() -> None:
        _cluster_by_embedding_similarity(entries, threshold=0.85)

    samples = time_sync(_run, warmup=1, n_samples=5)
    result = summarize("path_c_cosine_worst_case_n=200", samples)
    emit_report_line("path_c_worst_case", json.dumps(result.as_row()))

    out = _cluster_by_embedding_similarity(entries, threshold=0.85)
    # Each vector is its own cluster — verify the worst-case posture.
    assert len(out) == n_entries


# ---------------------------------------------------------------------------
# Cosine primitive itself — per-call cost
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_path_c_cosine_primitive_walltime() -> None:
    """Per-call cost of ``_cosine_similarity`` at 768 dims.

    Bounds the inner-loop cost. Total cluster cost ≈ N · k · cosine
    where k is the average cluster_so_far at the time of placement.
    """
    rng = make_seeded_rng()
    a = make_vector(rng)
    b = make_vector(rng)

    def _run() -> None:
        _cosine_similarity(a, b)

    samples = time_sync(_run, warmup=100, n_samples=10000)
    result = summarize("path_c_cosine_primitive_768dim", samples)
    emit_report_line("path_c_cosine_primitive", json.dumps(result.as_row()))


@pytest.mark.perf
def test_path_c_cosine_primitive_walltime_1536() -> None:
    """Per-call cost of ``_cosine_similarity`` at 1536 dims (next-model size)."""
    rng = make_seeded_rng()
    a = make_vector(rng, dim=1536)
    b = make_vector(rng, dim=1536)

    def _run() -> None:
        _cosine_similarity(a, b)

    samples = time_sync(_run, warmup=100, n_samples=5000)
    result = summarize("path_c_cosine_primitive_1536dim", samples)
    emit_report_line("path_c_cosine_primitive_1536", json.dumps(result.as_row()))
