# Performance

Performance baselines and operator runbooks for the load-bearing hot
paths in WormBase. Use these documents to detect regressions, to make
performance-sensitive design decisions, and to operate the indices and
embeddings the substrate depends on.

## Index

- [baseline.md](baseline.md) — Performance baseline across five hot
  paths: ledger-scan gather, projection-promoted gather, cosine vs
  substring clustering, EmbeddingService cache + concurrency, and the
  ReactivityRunner dispatch loop. Includes prioritized recommendations
  and open follow-up.
- [hnsw-tuning-runbook.md](hnsw-tuning-runbook.md) — Operator runbook
  for the HNSW index on `projection_query_outcomes.embedding`. When
  to tune, parameter trade-offs, the drop-and-rebuild procedure, and
  the per-tenant override model under engine-per-tenant routing.
- [cross-model-embedding-migration.md](cross-model-embedding-migration.md)
  — Operator runbook for swapping the embedding model between
  `nomic-embed-text` (768 dim) and `mxbai-embed-large` (1024 dim).
  Pre-migration checklist, 7-step procedure, validation queries, and
  rollback.
