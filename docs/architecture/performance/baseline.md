# Performance Baseline

This baseline measures five hot paths in the WormBase semantic-layer
pipeline. The numbers are an empirical reference for "what is fast,
what is slow, and where the next bottleneck lives." Use them to guide
performance-sensitive design decisions and to detect regressions.

**Scope:** five hot paths
**Methodology:** custom timeit-style harness under `tests/perf/`;
SQLite for SQL paths (Postgres caveat below); mocked Ollama
**Hardware:** macOS / Apple Silicon (darwin 24.6.0, Python 3.12.8)
**Reproduce:** `uv run --extra dev pytest tests/perf/ -v -m perf -s`

---

## TL;DR

1. **Cosine clustering is the dominant per-fire cost** for
   embedding-rich firings. At N=1000 entries, cosine clustering takes
   ~715ms wall-clock — three orders of magnitude slower than the
   substring fallback (~3.2ms). Cosine clustering is the next
   bottleneck to tackle when cluster cardinality climbs.

2. **Path A (in-memory ledger-scan gather) is shockingly cheap.** Even
   at N=5000 entries the gather completes in ~3.4ms mean with ~80KB
   peak allocation. The "promote to projection" intuition was right in
   posture but wrong in urgency — Path A scales fine into tens of
   thousands of entries per tenant.

3. **Path B (SQLite projection-promoted gather) is 100-2000× slower
   than Path A on SQLite** because the Python-cosine step deserializes
   JSON-embedded vectors row-by-row. At N=5000 SQLite rows, Path B mean
   is ~7.3 seconds. The Postgres + pgvector + HNSW path almost
   certainly inverts this — but it is unmeasured here. A real-Postgres
   benchmark is urgent before flipping `WORMBASE_GATHER_VIA_PROJECTION`
   on in any tenant.

4. **EmbeddingService concurrency is correctly parallel.** Twenty
   in-flight cache-miss embed calls complete in ~56ms total — one
   network latency, not twenty. The asyncio path is not accidentally
   serialized.

5. **Reactivity dispatch is sublinear in registered-reactivity count
   under non-matching predicates.** 25 non-matching + 1 matching
   reactivities dispatched against 100 `chat_received` entries: ~29ms
   total. The predicate short-circuit pays off.

---

## Path A — Ledger-scan gather

**Code:** `_make_gather_lookback_outcomes` (in-memory iteration over
ledger entries).

### Methodology

N outcome-execute entries seeded with embeddings, timestamps spread
across the 14-day lookback window. Built the gather closure at
`lookback_days=14`. Timed `gather_fn(triggering_entry, ctx)` over 20
samples with 2 warmup iterations.

The ledger fixture mirrors `InMemoryLedger.fetch` — returns a fresh
list copy per call — so the measurement includes the list-copy cost a
production InMemoryLedger pays. Memory measured via `tracemalloc.start()`
/ `get_traced_memory()` around a single post-warmup call.

### Results

| N entries | mean (ms) | p50 (ms) | p95 (ms) | min (ms) | max (ms) | peak mem (KB) |
|---|---|---|---|---|---|---|
| 100 | 0.153 | 0.037 | 0.711 | 0.034 | 1.52 | 2.0 |
| 1000 | 0.620 | 0.388 | 1.533 | 0.348 | 2.18 | 16.8 |
| 5000 | 3.423 | 3.240 | 4.566 | 2.43 | 5.25 | 80.3 |

### Interpretation

- **Scaling: linear in N.** From N=100 → N=5000 (50×), mean walltime
  grows from 0.15ms → 3.42ms (~22×) and memory from 2.0KB → 80.3KB
  (40×). The slightly-sublinear walltime is the warm-up effect at
  small N.
- **Bottleneck:** linear list scan + per-entry `payload.get("tool")`
  dict lookup. No JSON parse, no I/O.
- **Cost-per-entry:** ~0.7 μs walltime, ~16 bytes peak. At p99 the
  cost-per-entry is ~1.0 μs.

### Recommendation

Path A is **acceptable at < 50K entries per tenant.** At realistic
SaaS scale (a few thousand `query_outcome_recorded` execute rows per
active tenant per month), Path A is well under the 10ms-per-fire
human-perceptible bound.

**Path A → B promotion threshold should be raised.** The intuition that
"ledger scan is too expensive at scale" was correct in posture but the
actual breakpoint is much higher than the v2.B Phase 3c plan implied.
Keep `WORMBASE_GATHER_VIA_PROJECTION=0` (default OFF) until ledger
entry counts per tenant exceed ~50K, and even then only flip to a
tested-Postgres deployment.

---

## Path B — Projection-promoted gather (SQLite reader)

**Code:** `_make_gather_via_projection` against
`SqliteQueryOutcomeProjectionReader`.

### Methodology

Fresh `sqlite+aiosqlite:///:memory:` engine with the v016 migration
applied. Batch-inserted N rows (500-row chunks). Triggering entry
carries a known random 768-dim embedding so the cosine ranking branch
runs. 10 samples per measurement with 2 warmup iterations.

### Results — varying N at topk_limit=100

| N projection rows | mean (ms) | p50 (ms) | p95 (ms) | min (ms) | max (ms) |
|---|---|---|---|---|---|
| 100 | 252 | 270 | 293 | 193 | 296 |
| 1000 | 1,379 | 1,288 | 1,954 | 1,077 | 2,046 |
| 5000 | 7,303 | 7,215 | 8,964 | 5,672 | 8,983 |

### Results — N=2000, varying topk_limit

| topk_limit | mean (ms) | p50 (ms) | p95 (ms) |
|---|---|---|---|
| 10 | 3,090 | 2,946 | 4,459 |
| 50 | 2,637 | 2,480 | 3,625 |
| 100 | 2,877 | 2,718 | 3,826 |
| 500 | 4,351 | 4,112 | 5,970 |

### Results — N=1000, triggering_embedding=None (non-cosine fallback)

| label | mean (ms) | p50 (ms) | p95 (ms) |
|---|---|---|---|
| no_embedding_n=1000 | 322 | 271 | 604 |

### Interpretation

- **Scaling: linear in N — but at a fixed ~1.5ms per row.** The SQLite
  reader's full-table SELECT is fast; the Python cosine loop over every
  row dominates. Per-row cost ≈ JSON-parse-768-floats + dot-product =
  ~1.5ms in CPython.
- **`topk_limit` does NOT control row-scoring cost.** It only bounds
  the output list size.
- **No-embedding fallback is ~4× cheaper.** When the triggering entry
  has no embedding, the per-row cosine scoring step disappears entirely.

### Recommendation

| Action | Trigger |
|---|---|
| Do not flip `WORMBASE_GATHER_VIA_PROJECTION=1` on SQLite-backed installs | Now (default OFF is correct) |
| Benchmark Postgres + pgvector + HNSW path before flipping anywhere | Before any production flip |
| Consider a fast-path: skip cosine scoring when N is small | When projection wire ships |

Real-Postgres p95 with HNSW is the actual answer; SQLite numbers do
not represent it.

---

## Path C — Cosine vs substring clustering

**Code:** `_cluster_by_embedding_similarity(threshold=0.85)` vs
`_cluster_by_canonical_intent()`.

### Methodology

`n_entries` outcome-execute fixtures with embeddings drawn from 5
cluster centers + small gaussian jitter (0.005). 10-20 samples per N.
Worst case generated 200 all-distinct gaussian vectors so every entry
starts a new cluster — exercises the O(N²) regime.

### Results — cosine clustering, 5 seed clusters

| N entries | mean (ms) | p50 (ms) | p95 (ms) | min (ms) | max (ms) |
|---|---|---|---|---|---|
| 10 | 4.85 | 4.97 | 6.25 | 3.41 | 6.36 |
| 50 | 49.4 | 33.2 | 106.3 | 22.1 | 122.8 |
| 100 | 92.2 | 60.0 | 226.0 | 51.0 | 233.3 |
| 500 | 314.8 | 286.6 | 416.2 | 262.2 | 450.9 |
| 1000 | 714.8 | 673.2 | 895.5 | 615.5 | 932.5 |

### Results — substring clustering

| N entries | mean (ms) | p50 (ms) | p95 (ms) |
|---|---|---|---|
| 10 | 0.020 | 0.019 | 0.022 |
| 50 | 0.097 | 0.095 | 0.099 |
| 100 | 0.267 | 0.219 | 0.505 |
| 500 | 1.27 | 1.19 | 1.63 |
| 1000 | 3.23 | 2.67 | 5.65 |

### Results — cosine worst case (all-distinct vectors, N=200)

| label | mean (ms) | p50 (ms) |
|---|---|---|
| cosine_worst_case_n=200 | 3,030 | 2,961 |

### Results — `_cosine_similarity` primitive

| dim | mean (ms) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|
| 768 | 0.145 | 0.100 | 0.263 | 0.944 |
| 1536 | 0.273 | 0.206 | 0.502 | 1.301 |

### Interpretation

- **Cosine scales nearly linearly with N when cluster count is
  bounded.** At N=1000 with 5 clusters, per-entry cost is ~0.7ms — 5
  cosine calls × ~0.14ms — exactly what the primitive cost predicts.
  First-fit + low cluster count keeps the algorithm out of the O(N²)
  regime.
- **Worst case is genuinely quadratic.** 200 all-distinct vectors take
  ~3 seconds — that's ~15M ops of cosine arithmetic. A real workload
  that produces no clusters would be unworkable.
- **Substring clustering is ~220× faster** at N=1000 (3.2ms vs 715ms).
  Dict-grouping with no float math is a different cost class.
- **Cosine primitive at 768 dim:** ~145μs mean, ~944μs p99. Doubling
  dim to 1536 ~doubles cost as expected.

### Recommendation

| Action | Trigger |
|---|---|
| Document cosine clustering as the next bottleneck above N≈100 entries per fire | When per-fire walltime > 100ms is a regression signal |
| Pre-filter cluster candidates with a substring `(domain, canonical_intent)` bucket before cosine | When average per-tenant cluster cardinality exceeds 50 |
| Replace Python cosine with numpy vectorized batch | Same trigger |
| Add LSH or hierarchical clustering | When cluster count climbs to a few hundred per window |

---

## Path D — EmbeddingService cache + concurrency

**Code:** `EmbeddingService.embed()` with LRU cache.

### Methodology

`FakeEmbeddingService` honoring the `EmbeddingService` Protocol: per-
instance LRU cache, deterministic vector via SHA-256 expansion,
configurable `miss_latency_s` mocking the HTTP round-trip. **No real
Ollama call.** 500 samples for cache-hit, 20 samples for cache-miss,
5 samples per concurrency level.

### Results — cache hit vs miss

| label | mean (ms) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|
| cache_hit (warm) | <0.1 | — | — | — |
| cache_miss (50ms mock network) | ~55-60 | ~55 | ~60 | ~62 |
| cache_miss_zero_latency | ~0.7 | ~0.7 | ~1.2 | ~1.5 |
| at_capacity_eviction (1000 entries) | 0.465 | 0.182 | 2.447 | 3.869 |

### Results — concurrent cache miss (50ms mock)

| concurrency | total ms (mean of 5 samples) | per-call equivalent (ms) |
|---|---|---|
| 1 | 54.3 | 54.3 |
| 5 | 53.0 | 10.6 |
| 10 | 54.7 | 5.5 |
| 20 | 56.4 | 2.8 |

### Interpretation

- **Concurrency works.** All 20 in-flight embed calls complete in
  ~56ms — one mock-network latency. The asyncio path is properly
  parallel.
- **Cache-miss CPU cost is ~0.7ms at 768 dim.** Real-Ollama p95
  (~300-500ms typical) dominates this entirely.
- **LRU eviction adds ~30% overhead at capacity** vs zero-latency
  miss. Negligible in a real workload where network dominates.
- **Cache hit is essentially free** — sub-microsecond.

### Recommendation

| Action | Trigger |
|---|---|
| Run a real-Ollama benchmark before declaring p95 numbers | Before publishing customer-facing SLA on embed latency |
| Share one `EmbeddingService` instance across all reactivities in a process | Already done; verify cache hit rate > 30% steady-state in production logs |
| Bump LRU cap to 2000-4000 | If cache-hit rate < 30% in production telemetry |

---

## Path E — ReactivityRunner dispatch loop

**Code:** `ReactivityRunner.run_once()` against seeded `InMemoryLedger`.

### Methodology

Seeded N `chat_received` PEVR cycles (4 entries per cycle).
`ReactivityRegistry` + N reactivities, all matching
`EntryKind("chat_received")` with `AlwaysAllow` condition + `fired=False`
action. Cold = first call (cursor=0, processes all N entries); warm =
subsequent call (cursor at tail, no new rows).

### Results — base scenario (5 reactivities)

| N new chat_received PEVR cycles | total entries | cold (ms) | warm (ms, p50/p95) |
|---|---|---|---|
| 100 | 400 | 4.25 | 0.28 / 0.88 |
| 1000 | 4000 | 121.4 | 5.6 / 18.1 |

### Results — dispatch cost scaling (N=100 new entries)

| reactivities registered | total (ms) |
|---|---|
| 1 | 1.54 |
| 5 | 10.66 |
| 10 | 13.72 |
| 25 | 43.34 |

### Results — non-matching predicates (25 nm + 1 matching, N=100)

| label | total (ms) |
|---|---|
| nonmatching_n_reacs=26 | 28.65 |

### Results — steady state (5000 entries, no new rows)

| label | mean (ms) | p50 (ms) | p95 (ms) |
|---|---|---|---|
| steady_state_n_entries=5000 | 6.47 | 6.04 | 8.20 |

### Interpretation

- **Cold cost is dominated by per-entry dispatch.** At 1000 new
  `chat_received` cycles + 5 reactivities, the runner is doing 5000
  predicate matches + 1000 fires = 121ms (~120μs per matching dispatch).
- **Warm cost is just two `ledger.fetch` calls + sort + cursor check.**
  With 4000 entries in the ledger and no new rows: ~0.4-8ms depending on
  entry count. The double-fetch (one pre-cycle, one post-cycle for
  tail-hash bookkeeping) is the dominant cost.
- **Dispatch cost is linear in (reactivities × matching_entries).** The
  non-matching short-circuit pays off (28.7ms vs an estimated 78ms if
  all 25 matched).
- **Steady state at 5000 entries:** ~6.5ms per poll cycle. With 1s poll
  interval, that's 0.65% CPU overhead — acceptable.

### Recommendation

| Action | Trigger |
|---|---|
| Skip the second `ledger.fetch` when no new rows fired | When per-tenant ledger entries cross ~10K |
| Add per-reactivity dispatch time to the trace | When a customer reports "reactivities feel slow" |
| Consider cursor-based `fetch_since(seq)` on the Ledger Protocol | When per-tenant ledger > 10K entries |

---

## Cross-path observations

1. **Path A is dramatically cheaper than expected.** The "ledger scan
   doesn't scale" intuition is wrong at SaaS-realistic N. The
   projection-promoted gather (Path B) is a Postgres+pgvector story;
   on SQLite it is a regression, not an improvement.

2. **Path C (cosine clustering) is the silent dominant cost** when
   embeddings are present. At realistic N (a few hundred outcomes per
   window per company) it's 50-100ms; at unexpected N (a few thousand)
   it jumps to seconds. This is the next bottleneck — Path A is fine.

3. **Path B at N=5000 SQLite (7.3 sec) is the most alarming number in
   this baseline.** A misconfigured tenant (env flag flipped on against
   a SQLite-backed install) would experience multi-second per-fire
   latency. The default-OFF gating is correct; tighten it with a
   runtime assertion that refuses to enable when the engine is SQLite.

4. **Network latency (Path D) dwarfs everything else.** A single embed
   cache-miss (~150-300ms real-world) is ~30-60× the entire Path C
   cosine-clustering cost at N=100. Cache warming + hit-rate
   observability is higher leverage than micro-optimizing the
   clustering loop.

5. **Path E steady-state (~6.5ms/cycle at N=5000) is negligible.** The
   runner is not a bottleneck and won't be at 10× this scale.

---

## Prioritized recommendations

| # | Action | Trigger | Priority |
|---|---|---|---|
| 1 | Real-Postgres + real-Ollama benchmarks | Before publishing SLA or flipping env flags | HIGH |
| 2 | Runtime guard refusing `WORMBASE_GATHER_VIA_PROJECTION=1` on SQLite engines | Now (cheap safety) | HIGH |
| 3 | Pre-bucket cluster candidates by `(domain, canonical_intent)` before cosine | When per-fire walltime > 100ms | MED |
| 4 | numpy-vectorized batch cosine in `_cluster_by_embedding_similarity` | Same trigger as #3 | MED |
| 5 | `Ledger.fetch_since(seq)` to slim per-cycle work | Per-tenant ledger > 10K entries | MED |
| 6 | Skip post-cycle `ledger.fetch` when no fires happened | Same trigger as #5 | LOW |
| 7 | Embedding-cache hit-rate observability | Now | LOW |
| 8 | LSH / hierarchical clustering | When traces reveal worst-case scenarios | LOW |

---

## Open follow-up

- **Real-Postgres + pgvector + HNSW Path B numbers.** SQLite results are
  not predictive. Need a testcontainers-Postgres harness with pgvector
  image + v016/v018/v019 migrations applied. Expected: Postgres + HNSW
  path is 10-100× faster than the SQLite baseline at N≥1000.
- **Real-Ollama Cloud Path D numbers.** Mock=50ms; production p50/p95/
  p99 unmeasured. Need an env-gated test that calls
  `OllamaCloudEmbeddingService.embed()` against the live endpoint.
- **Multi-tenant concurrent load.** All benchmarks here are single-
  process, single-tenant. Effective production load involves N parallel
  tenants polling on the same Postgres and sharing the same
  `EmbeddingService` cache (which is per-process, not per-tenant).
  Locking and contention behavior at concurrent fire is unmeasured.
- **Cold-cache vs warm-cache LRU behavior under real query
  distribution.** The mock models miss latency cleanly, but the question
  of "what hit rate does a real workload sustain?" is empirical.
  Surfacing the hit-rate metric in production telemetry is the
  actionable follow-up.
- **Cosine clustering with all-distinct vectors at production
  cardinality (N≈500-1000).** The worst case measured was N=200 (~3s).
  At N=1000 the worst-case extrapolates to ~75 seconds. Verify whether
  any real tenant produces this distribution.

---

## Methodology limitations

- **SQLite proxies Postgres for Path B.** The SQLite reader's Python-
  cosine loop is its own algorithm class; the Postgres + pgvector +
  HNSW path uses a different code path entirely
  (`PostgresQueryOutcomeProjectionReader`, not benchmarked here).
- **Ollama is mocked for Path D.** Real network latency varies by
  region, API load, and model size; 50ms is a placeholder.
- **Single-process measurement.** Multi-tenant concurrent traffic is
  not modeled.
- **CPython only.** PyPy or a Rust extension would change Path C
  dramatically.
- **macOS / Apple Silicon hardware.** Linux x86_64 production hosts
  will differ; relative ordering of paths should be stable; absolute
  numbers will shift.
- **tracemalloc adds ~5-10% overhead** to the Path A memory
  measurement; treat the memory column as indicative within ±10%.

---

## Reproducing this baseline

```bash
# All perf tests:
uv run --extra dev pytest tests/perf/ -v -m perf -s

# Per path:
uv run --extra dev pytest tests/perf/test_gather_paths.py -v -m perf -s    # A + B
uv run --extra dev pytest tests/perf/test_cluster_paths.py -v -m perf -s   # C
uv run --extra dev pytest tests/perf/test_embedding_paths.py -v -m perf -s # D
uv run --extra dev pytest tests/perf/test_runner_paths.py -v -m perf -s    # E

# Capture as JSON for regression diffing:
uv run --extra dev pytest tests/perf/ -v -m perf -s 2>&1 \
    | grep -E "^\[PERF:[a-z_]+\]" \
    | sed 's/^\[PERF:[a-z_]*\] //' \
    > /tmp/perf-baseline-$(date +%Y%m%d).jsonl
```

The `[PERF:<label>]` log lines are stable JSON dicts keyed by label;
future runs can diff against the captured baseline to catch regressions.
