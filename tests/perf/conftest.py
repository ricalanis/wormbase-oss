"""Shared fixtures + helpers for the perf benchmark suite.

Keeps fixture construction predictable so measurements aren't polluted
by ledger-seeding cost. Seeding helpers run OUTSIDE the timed region;
the timed region only calls the function-under-test.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import time
import tracemalloc
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
#
# Benchmarks should be deterministic at fixture level so memory + LOC
# overhead is the same across runs. Vector content uses a seeded PRNG.

TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000fbe17")
EMBEDDING_DIM = 768
_PRNG_SEED = 0xBEEF


@pytest.fixture
def company_id() -> UUID:
    return TEST_COMPANY_ID


# ---------------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------------


def make_seeded_rng(seed: int = _PRNG_SEED) -> random.Random:
    """Return a fresh seeded PRNG so vector content is reproducible."""
    return random.Random(seed)


def make_vector(rng: random.Random, dim: int = EMBEDDING_DIM) -> list[float]:
    """Build a random unit-length-ish vector for cosine tests.

    Not unit-normalized — `_cosine_similarity` normalizes on the fly,
    so feeding raw gaussian noise exercises the same code path that
    Ollama-served vectors do.
    """
    return [rng.gauss(0.0, 1.0) for _ in range(dim)]


def near_duplicate_vector(
    base: list[float], rng: random.Random, jitter: float = 0.01,
) -> list[float]:
    """Return a small-perturbation copy of ``base``.

    Used for cosine-cluster fixtures: we need a bunch of vectors that
    DO cluster (so the cluster_fn actually does work), not just
    independent gaussians (which never cluster at threshold 0.85).
    """
    return [v + rng.gauss(0.0, jitter) for v in base]


# ---------------------------------------------------------------------------
# Outcome execute-entry shape (used by Paths A + B + C)
# ---------------------------------------------------------------------------


def make_outcome_execute_entry(
    *,
    seq: int,
    nl_question: str,
    quality_score: str = "0.95",
    used: bool = True,
    useful: bool = True,
    domain_id: str = "domain.demo",
    embedding: list[float] | None = None,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a canonical ``query_outcome_recorded`` execute entry.

    Mirrors the shape that ``ChannelAdapter`` writes through the
    ledger; specifically the fields the gather + cluster functions
    in ``wormbase_agent_gateway.reactivities`` read.
    """
    if recorded_at is None:
        recorded_at = datetime.now(UTC)
    args: dict[str, Any] = {
        "agent_query_id": str(uuid4()),
        "nl_question": nl_question,
        "final_query_spec": {"domain_id": domain_id, "sql": "SELECT 1"},
        "result_summary": {"row_count": 1},
        "used": used,
        "useful": useful,
        "quality_score": quality_score,
        "domain_id": domain_id,
    }
    if embedding is not None:
        args["embedding"] = embedding
    return {
        "entry_id": uuid4(),
        "company_id": TEST_COMPANY_ID,
        "seq": seq,
        "ts": recorded_at,
        "kind": "execute",
        "quadrant": "active_deterministic",
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": args,
            "result_ref": str(args["agent_query_id"]),
            "propose_entry_id": str(uuid4()),
        },
        "prev_hash": b"\x00" * 32,
        "hash": b"\x00" * 32,
    }


def seed_outcome_entries(
    n: int,
    *,
    n_clusters: int = 5,
    with_embedding: bool = True,
    days_window: int = 14,
) -> list[dict[str, Any]]:
    """Generate ``n`` outcome-execute entries grouped into ``n_clusters``
    near-duplicate clusters when ``with_embedding=True``.

    Spread timestamps evenly across the last ``days_window`` days so
    the gather's cutoff filter has work to do (entries near the cutoff
    boundary force the time comparison).
    """
    rng = make_seeded_rng()
    cluster_centers: list[list[float] | None] = []
    if with_embedding:
        for _ in range(max(n_clusters, 1)):
            cluster_centers.append(make_vector(rng))
    else:
        cluster_centers = [None] * max(n_clusters, 1)

    cluster_intents = [f"how many orders today batch_{i}" for i in range(n_clusters)]

    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for i in range(n):
        cluster_ix = i % max(n_clusters, 1)
        emb: list[float] | None = None
        if cluster_centers[cluster_ix] is not None:
            emb = near_duplicate_vector(
                cluster_centers[cluster_ix],  # type: ignore[arg-type]
                rng,
                jitter=0.005,
            )
        # Spread evenly across the window
        age_s = (days_window * 24 * 3600) * (i / max(n - 1, 1))
        ts = now - timedelta(seconds=age_s)
        out.append(
            make_outcome_execute_entry(
                seq=i + 1,
                nl_question=cluster_intents[cluster_ix],
                embedding=emb,
                recorded_at=ts,
            ),
        )
    return out


# ---------------------------------------------------------------------------
# In-memory ledger fixture for Path A
# ---------------------------------------------------------------------------


class StubLedger:
    """Minimal ledger that returns a pre-seeded entry list on ``fetch``.

    The real ``InMemoryLedger.fetch`` returns ``list(self._entries[cid])``
    (a fresh list copy each call). We do the same so the gather sees
    the same per-call allocation cost as production.
    """

    def __init__(self, entries: Sequence[dict[str, Any]]) -> None:
        self._entries = list(entries)

    async def fetch(
        self,
        company_id: UUID,
        until_ts: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if until_ts is None:
            return list(self._entries)
        return [r for r in self._entries if r["ts"] <= until_ts]


@dataclass
class StubContext:
    """ReactivityContext shape — duck-typed for the gather functions."""

    ledger: Any
    company_id: UUID
    registry: Any = None
    now: Any = None
    extras: dict[str, Any] = field(default_factory=dict)
    replay_mode: bool = False

    def __post_init__(self) -> None:
        if self.now is None:
            t = datetime.now(UTC)
            self.now = lambda: t


# ---------------------------------------------------------------------------
# Measurement helpers — minimal, no pytest-benchmark dependency
# ---------------------------------------------------------------------------


@dataclass
class TimingResult:
    label: str
    n_samples: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    mem_peak_kb: float | None = None

    def as_row(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "n_samples": self.n_samples,
            "mean_ms": round(self.mean_ms, 4),
            "p50_ms": round(self.p50_ms, 4),
            "p95_ms": round(self.p95_ms, 4),
            "p99_ms": round(self.p99_ms, 4),
            "min_ms": round(self.min_ms, 4),
            "max_ms": round(self.max_ms, 4),
            "mem_peak_kb": (
                round(self.mem_peak_kb, 2) if self.mem_peak_kb is not None else None
            ),
        }


def percentile(samples: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile. Avoids numpy dependency."""
    if not samples:
        return 0.0
    s = sorted(samples)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def summarize(label: str, samples_ms: Sequence[float], mem_kb: float | None = None) -> TimingResult:
    if not samples_ms:
        raise ValueError("summarize: no samples")
    return TimingResult(
        label=label,
        n_samples=len(samples_ms),
        mean_ms=statistics.mean(samples_ms),
        p50_ms=percentile(samples_ms, 0.50),
        p95_ms=percentile(samples_ms, 0.95),
        p99_ms=percentile(samples_ms, 0.99),
        min_ms=min(samples_ms),
        max_ms=max(samples_ms),
        mem_peak_kb=mem_kb,
    )


async def time_async(
    fn: Callable[[], Any], *, warmup: int = 2, n_samples: int = 20,
) -> list[float]:
    """Run an async callable repeatedly and return per-iteration ms."""
    for _ in range(warmup):
        await fn()
    samples: list[float] = []
    for _ in range(n_samples):
        t0 = time.perf_counter()
        await fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def time_sync(
    fn: Callable[[], Any], *, warmup: int = 2, n_samples: int = 20,
) -> list[float]:
    """Run a sync callable repeatedly and return per-iteration ms."""
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(n_samples):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def measure_memory_async(fn: Callable[[], Any]) -> float:
    """Return peak KB allocated during one async invocation of ``fn``.

    Caller is responsible for executing the coroutine; this is the
    raw allocation peak as reported by ``tracemalloc``. Includes
    fixture-internal allocations made inside the call, not the seed.
    """
    import asyncio
    tracemalloc.start()
    try:
        asyncio.get_event_loop().run_until_complete(fn())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak / 1024.0


def format_table(rows: list[dict[str, Any]], headers: list[str]) -> str:
    """Format a list of dicts as a markdown table."""
    if not rows:
        return "(no data)"
    out = ["| " + " | ".join(headers) + " |"]
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        out.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
    return "\n".join(out)


def emit_report_line(label: str, msg: str, capsys: Any | None = None) -> None:
    """Print a tagged line to stdout for log capture.

    ``pytest -s`` surfaces these immediately; ``pytest -v`` collects
    them through capsys for assertion. Either way the report doc
    references the line tags.
    """
    print(f"[PERF:{label}] {msg}")


__all__ = [
    "EMBEDDING_DIM",
    "TEST_COMPANY_ID",
    "TimingResult",
    "StubContext",
    "StubLedger",
    "company_id",
    "emit_report_line",
    "format_table",
    "make_outcome_execute_entry",
    "make_seeded_rng",
    "make_vector",
    "measure_memory_async",
    "near_duplicate_vector",
    "percentile",
    "seed_outcome_entries",
    "summarize",
    "time_async",
    "time_sync",
]
