"""Performance baseline benchmarks for WormBase semantic-layer hot paths.

This package is **opt-in**. The `perf` pytest marker is excluded from
default runs at the workspace root. Invoke explicitly:

    uv run --extra dev pytest tests/perf/ -v -m perf

Goal: capture wall-clock + memory baselines so future refactors can be
graded against measurable regressions, and so the gather-promotion
threshold (Path A → Path B) is calibrated against real numbers instead
of guesses.

Hot paths covered (see `docs/superpowers/notes/2026-05-27-perf-baseline.md`
for interpretation):

* Path A — ledger-scan gather (`_make_gather_lookback_outcomes`)
* Path B — projection-promoted gather (SqliteQueryOutcomeProjectionReader)
* Path C — cosine cluster_fn vs substring fallback
* Path D — EmbeddingService.embed() — cache hit vs miss, concurrency
* Path E — ReactivityRunner.run_once dispatch loop

Methodology limits (intentional, documented per measurement):

* SQLite proxies Postgres (no pgvector in the test rig)
* Mocked Ollama (no real network)
* Single-process (no multi-tenant concurrent load)
"""
