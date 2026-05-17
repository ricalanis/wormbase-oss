"""v2.B Phase 3b — embedding-similarity clustering integration tests.

Axes 1 (template promotion) + 3 (bad-pattern) now swap their substring
canonicalisation for cosine ≥ 0.85 clustering when entries carry an
embedding. Pre-3b entries (embedding=None) fall back to substring.

These tests pin:

  * 3 outcomes with similar embeddings + DIFFERENT NL substrings →
    cluster + promote (axis 1)
  * 3 failures with similar embeddings + DIFFERENT NL substrings →
    cluster + propose bad_pattern (axis 3)
  * Mixed (embedded + non-embedded) entries cluster via the hybrid
    path (embedded → cosine; non-embedded → substring)
  * Backward-compat: 3 entries without embeddings still cluster via
    substring (existing v2.B Phase 1+2 contract)
  * The embedding_threshold factory parameter wires through
  * v1-legacy vs v2-vectorized byte-identical partition across 5+
    seeded fixtures (2026-05-14 carry-forward #3)
  * Pre-bucketing by ``_resolved_domain`` reduces the per-bucket
    matrix size (auditable shape check)

Uses InMemoryLedger + real ReactivityRegistry/Runner — no mocks.
"""
from __future__ import annotations

import random
from uuid import UUID, uuid4

import pytest
from wormbase_ledger import InMemoryLedger
from wormbase_reactivities.registry import ReactivityRegistry
from wormbase_reactivities.runner import ReactivityRunner

from wormbase_agent_gateway.reactivities import (
    OutcomeToTemplatePromotionReactivity,
    _batch_cosine_matrix,
    _cluster_by_embedding_similarity_legacy,
    _cluster_by_embedding_similarity_v2,
    make_query_failure_to_bad_pattern_reactivity,
)


_COMPANY_ID = UUID("00000000-0000-0000-0000-0000000eb001")


def _vec_near(base: list[float], delta: float = 0.005) -> list[float]:
    """Build a vector close to ``base`` so cosine ≥ 0.85."""
    return [b + delta for b in base]


def _vec_orthogonal(dim: int = 8) -> list[float]:
    """Build an orthogonal vector — cosine 0 against the unit basis."""
    return [0.0] * (dim - 1) + [1.0]


async def _write_outcome(
    ledger: InMemoryLedger,
    *,
    company_id: UUID,
    nl_question: str,
    quality_score: str = "0.95",
    used: bool = True,
    useful: bool = True,
    domain_id: str = "dom-finance",
    embedding: list[float] | None = None,
    agent_query_id: str | None = None,
) -> dict:
    """Drive the canonical PEVR shape ``lake.query.record_outcome`` emits.

    Optionally stamps an ``embedding`` field on the payload's ``args``
    (matching v2.B Phase 3b write-time wire).
    """
    aqi = agent_query_id or str(uuid4())
    spec: dict = {"metric": "revenue", "domain_id": domain_id}
    outcome_dict: dict = {
        "agent_query_id": aqi,
        "nl_question": nl_question,
        "final_query_spec": spec,
        "result_summary": {"row_count": 1},
        "used": used,
        "useful": useful,
        "user_correction": None,
        "quality_score": quality_score,
    }
    if embedding is not None:
        outcome_dict["embedding"] = embedding
    await ledger.write(
        company_id=company_id,
        propose={
            "target_kind": "query_outcome_recorded",
            "ref_id": aqi,
            "reason": f"test outcome aqi={aqi}",
            "proposed_by": "test",
        },
        execute_fn=lambda: {
            "tool": "emit_query_outcome_recorded",
            "args": outcome_dict,
            "result_ref": aqi,
        },
        verify_fn=lambda _r: {
            "checks": [{"name": "outcome_recorded", "ok": True}],
            "passed": True,
        },
        resolve_fn=lambda _v: {
            "outcome": "keep",
            "rationale": "outcome_recorded",
        },
        quadrant="active_deterministic",
    )
    rows = await ledger.fetch(company_id)
    executes = [
        r for r in rows
        if r["kind"] == "execute"
        and (r["payload"] or {}).get("tool") == "emit_query_outcome_recorded"
        and ((r["payload"] or {}).get("args") or {}).get("agent_query_id") == aqi
    ]
    return executes[-1]


def _fetch_template_promotions(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "propose"
        and "nl_intent" in (r.get("payload") or {})
        and "promoted_from_outcome_ids" in (r.get("payload") or {})
    ]


def _fetch_bad_pattern_proposeds(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if r["kind"] == "propose"
        and (r.get("payload") or {}).get("target_kind") == "bad_pattern_proposed"
    ]


# ---------------------------------------------------------------------------
# Axis 1 — Template promotion via embedding clustering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_axis1_embedding_clusters_despite_different_substrings() -> None:
    """3 high-quality outcomes with similar embeddings but DIFFERENT
    NL substrings → one template promotion via cosine clustering.

    This is the headline v2.B Phase 3b behaviour: substring
    canonicalisation would NOT cluster these (the strings disagree
    after lowercasing), but cosine similarity does (embeddings live
    in the same neighbourhood).
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(OutcomeToTemplatePromotionReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    base = [1.0, 0.5, 0.3, 0.2, 0.1, 0.0, 0.0, 0.0]
    o1 = await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What is revenue this quarter?",
        embedding=base,
    )
    o2 = await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="How much money did we make in Q3?",
        embedding=_vec_near(base, 0.01),
    )
    o3 = await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="Show me quarterly revenue numbers",
        embedding=_vec_near(base, 0.02),
    )

    fired = await runner.run_once()
    assert fired >= 1

    rows = await ledger.fetch(_COMPANY_ID)
    promotions = _fetch_template_promotions(rows)
    assert len(promotions) == 1, (
        f"expected 1 promotion via embedding clustering, got "
        f"{len(promotions)}"
    )
    src_ids = set(promotions[0]["payload"]["promoted_from_outcome_ids"])
    assert src_ids == {
        str(o1["entry_id"]),
        str(o2["entry_id"]),
        str(o3["entry_id"]),
    }


@pytest.mark.asyncio
async def test_axis1_orthogonal_embeddings_dont_cluster() -> None:
    """3 outcomes with orthogonal embeddings → no cluster of size 3 →
    no template promotion (each is its own cluster of 1)."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(OutcomeToTemplatePromotionReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="revenue question",
        embedding=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    )
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="users question",
        embedding=[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    )
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="cohort question",
        embedding=[0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    promotions = _fetch_template_promotions(rows)
    assert promotions == []


@pytest.mark.asyncio
async def test_axis1_backward_compat_substring_fallback() -> None:
    """3 outcomes WITHOUT embeddings still cluster via substring — the
    pre-3b contract is preserved for legacy / opt-out installations."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(OutcomeToTemplatePromotionReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    # No embedding field on any of these — falls through to substring.
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What is revenue this quarter?",
    )
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="what is revenue THIS quarter?",  # canonical match
    )
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What is revenue this quarter?",
    )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    promotions = _fetch_template_promotions(rows)
    assert len(promotions) == 1


@pytest.mark.asyncio
async def test_axis1_hybrid_mixed_entries_cluster_independently() -> None:
    """3 outcomes with similar embeddings + 3 outcomes with different
    embeddings but matching substrings → TWO promotions:

      1. embedded cluster of 3
      2. substring cluster of 3 (the non-embedded fallback path)
    """
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(OutcomeToTemplatePromotionReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    base = [1.0, 0.5, 0.3, 0.2, 0.1, 0.0, 0.0, 0.0]
    # Embedded cluster
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="alpha embedded one",
        embedding=base,
        domain_id="dom-emb",
    )
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="beta embedded two",
        embedding=_vec_near(base, 0.005),
        domain_id="dom-emb",
    )
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="gamma embedded three",
        embedding=_vec_near(base, 0.01),
        domain_id="dom-emb",
    )
    # Non-embedded substring cluster (different domain so it's a
    # distinct group from the embedded one).
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What is DAU?",
        domain_id="dom-product",
    )
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="what is dau?",
        domain_id="dom-product",
    )
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What is DAU?",
        domain_id="dom-product",
    )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    promotions = _fetch_template_promotions(rows)
    assert len(promotions) == 2, (
        f"expected 2 promotions (1 embedded + 1 substring); got "
        f"{len(promotions)}"
    )


# ---------------------------------------------------------------------------
# Axis 3 — Bad-pattern via embedding clustering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_axis3_embedding_clusters_failures_despite_different_substrings() -> None:
    """2 failed outcomes (used=True AND useful=False) with similar
    embeddings but DIFFERENT substrings → one bad_pattern_proposed via
    cosine clustering (threshold = 2 for axis 3)."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_query_failure_to_bad_pattern_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    base = [0.7, 0.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What is the revenue trend?",
        used=True, useful=False, quality_score="0.91",
        embedding=base,
    )
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="Where is revenue going this month?",
        used=True, useful=False, quality_score="0.95",
        embedding=_vec_near(base, 0.005),
    )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_bad_pattern_proposeds(rows)
    assert len(proposed) == 1, (
        f"expected 1 bad_pattern_proposed via embedding clustering; "
        f"got {len(proposed)}"
    )


@pytest.mark.asyncio
async def test_axis3_backward_compat_substring_fallback() -> None:
    """Failures without embeddings still cluster via substring — pre-3b
    behaviour preserved."""
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(make_query_failure_to_bad_pattern_reactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="What is Q3 EMEA revenue?",
        used=True, useful=False, quality_score="0.91",
    )
    await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="what is q3 EMEA revenue?",  # substring match
        used=True, useful=False, quality_score="0.95",
    )

    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    proposed = _fetch_bad_pattern_proposeds(rows)
    assert len(proposed) == 1


# ---------------------------------------------------------------------------
# Factory tunable parameter — verify embedding_threshold flows through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_axis1_embedding_threshold_factory_parameter_lowers_recall() -> None:
    """A high embedding_threshold (0.99) drops a cluster that lower
    threshold (0.85) would have kept — verifies factory plumbing."""
    base = [1.0, 0.5, 0.3, 0.2, 0.1, 0.0, 0.0, 0.0]
    # cosine(base, base + delta) drops with larger delta. delta=0.05
    # on a length-1.3 vector → cosine ≈ 0.93.

    # First, with default threshold (0.85): cluster happens.
    ledger = InMemoryLedger()
    registry = ReactivityRegistry(ledger=ledger, company_id=_COMPANY_ID)
    registry.register(OutcomeToTemplatePromotionReactivity())
    runner = ReactivityRunner(
        ledger=ledger, company_id=_COMPANY_ID, registry=registry,
        poll_interval_s=0.01,
    )

    for delta in (0.0, 0.04, 0.05):
        await _write_outcome(
            ledger, company_id=_COMPANY_ID,
            nl_question=f"q-{delta}",
            embedding=_vec_near(base, delta),
        )
    await runner.run_once()
    rows = await ledger.fetch(_COMPANY_ID)
    promotions_default = _fetch_template_promotions(rows)
    assert len(promotions_default) == 1

    # Now with a strict threshold (0.99): the cluster splits.
    ledger2 = InMemoryLedger()
    registry2 = ReactivityRegistry(ledger=ledger2, company_id=_COMPANY_ID)
    registry2.register(
        OutcomeToTemplatePromotionReactivity(embedding_threshold=0.999),
    )
    runner2 = ReactivityRunner(
        ledger=ledger2, company_id=_COMPANY_ID, registry=registry2,
        poll_interval_s=0.01,
    )
    for delta in (0.0, 0.04, 0.05):
        await _write_outcome(
            ledger2, company_id=_COMPANY_ID,
            nl_question=f"q-{delta}",
            embedding=_vec_near(base, delta),
        )
    await runner2.run_once()
    rows2 = await ledger2.fetch(_COMPANY_ID)
    promotions_strict = _fetch_template_promotions(rows2)
    # At threshold 0.999 the points no longer pass; clusters split → no
    # cluster reaches threshold=3.
    assert promotions_strict == []


# ---------------------------------------------------------------------------
# Wire-replay determinism — embedding survives round-trip
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2026-05-14 carry-forward #3 — v1-legacy vs v2-vectorized byte-identity
# ---------------------------------------------------------------------------


def _build_outcome_for_partition_test(
    *, domain_id: str, embedding: list[float], intent_suffix: str,
) -> dict:
    """Build a minimal outcome execute entry for direct cluster_fn calls.

    Mirrors the payload shape ``lake.query.record_outcome`` writes —
    domain in ``final_query_spec.domain_id``, embedding under args.
    """
    return {
        "kind": "execute",
        "payload": {
            "tool": "emit_query_outcome_recorded",
            "args": {
                "nl_question": f"q-{intent_suffix}",
                "embedding": embedding,
                "final_query_spec": {"domain_id": domain_id},
            },
        },
    }


def _partition_signature(clusters: list[list[dict]]) -> set[frozenset[int]]:
    """Set-of-frozensets keyed on Python ``id`` — partition equality
    regardless of cluster ordering."""
    return {frozenset(id(e) for e in c) for c in clusters}


@pytest.mark.parametrize("seed", [10, 11, 12, 13, 14, 15])
def test_v1_legacy_vs_v2_vectorized_partition_byte_identical(seed: int) -> None:
    """Across 6 seeded fixtures (one resolved-domain bucket, 5 seed
    cluster centers, 30 entries with light jitter), the v1-legacy and
    v2-vectorized impls produce the same partition.

    This is the contract the perf optimization ships on: the speedup
    is silent — clustering behaviour is unchanged.
    """
    rng = random.Random(seed)
    centers = [[rng.gauss(0.0, 1.0) for _ in range(32)] for _ in range(5)]

    entries: list[dict] = []
    for i in range(30):
        c = i % 5
        vec = [v + rng.gauss(0.0, 0.005) for v in centers[c]]
        entries.append(
            _build_outcome_for_partition_test(
                domain_id="dom-shared",
                embedding=vec,
                intent_suffix=f"{c}-{i}",
            ),
        )

    v1 = _cluster_by_embedding_similarity_legacy(entries, threshold=0.85)
    v2 = _cluster_by_embedding_similarity_v2(entries, threshold=0.85)
    assert _partition_signature(v1) == _partition_signature(v2), (
        f"seed={seed}: v1 had {len(v1)} clusters, v2 had {len(v2)}; "
        f"partition diverges"
    )


def test_v2_prebucketing_isolates_per_domain_matrices() -> None:
    """Verify the v2 path actually buckets by domain.

    Construct entries split across three domains; the resulting
    partition must keep cross-domain entries in separate clusters
    even when their embeddings are identical.

    Side effect: this is the documented intentional divergence from
    v1 — v1 would merge two near-duplicate vectors across domains,
    v2 keeps them in their own buckets so the downstream
    ``(domain, intent)`` key shape lines up.
    """
    vec = [1.0, 0.5, 0.3, 0.2]
    entries = [
        _build_outcome_for_partition_test(
            domain_id=f"dom-{d}", embedding=vec, intent_suffix=str(i),
        )
        for d in ("a", "b", "c")
        for i in range(4)
    ]
    v2 = _cluster_by_embedding_similarity_v2(entries, threshold=0.85)
    # Three buckets, one cluster of 4 in each.
    assert len(v2) == 3
    for c in v2:
        # All entries in a v2 cluster share one resolved domain.
        domains = {
            ((e["payload"] or {}).get("args") or {})
            .get("final_query_spec", {})
            .get("domain_id")
            for e in c
        }
        assert len(domains) == 1
        assert len(c) == 4


def test_v2_prebucketing_reduces_per_bucket_matrix_size() -> None:
    """When inputs split N=60 entries across 3 domains, the per-bucket
    cosine matrix is 20x20 (not 60x60).

    We verify this by reproducing the bucketing inline and asserting
    the per-bucket call shape matches what v2 would compute. This is
    a structural / shape-of-the-compute check, not a wall-clock test.
    """
    rng = random.Random(0xABCD)
    entries: list[dict] = []
    for d in ("alpha", "beta", "gamma"):
        for i in range(20):
            entries.append(
                _build_outcome_for_partition_test(
                    domain_id=f"dom-{d}",
                    embedding=[rng.gauss(0.0, 1.0) for _ in range(16)],
                    intent_suffix=f"{d}-{i}",
                ),
            )

    # Reproduce the bucketing v2 does internally to confirm matrix sizes.
    by_domain: dict[str, list[list[float]]] = {}
    for e in entries:
        args = (e["payload"] or {}).get("args") or {}
        domain = (args.get("final_query_spec") or {}).get("domain_id") or "_no_domain"
        by_domain.setdefault(domain, []).append(args["embedding"])

    # Each per-bucket BLAS call is 20x20 — 1200x cheaper than a single
    # 60x60 matrix would be at scale.
    for domain, embs in by_domain.items():
        matrix = _batch_cosine_matrix(embs)
        assert matrix.shape == (20, 20)

    # And the public v2 result has 3 buckets' worth of clusters
    # (each bucket itself producing ~20 singleton clusters since
    # random gaussian inputs don't cluster at threshold 0.85).
    v2 = _cluster_by_embedding_similarity_v2(entries, threshold=0.85)
    # All entries placed; one cluster per entry since random gaussians
    # don't cluster.
    assert sum(len(c) for c in v2) == 60
    # Every cluster's members share one domain — bucketing held.
    for c in v2:
        domains = {
            ((e["payload"] or {}).get("args") or {})
            .get("final_query_spec", {})
            .get("domain_id")
            for e in c
        }
        assert len(domains) == 1


@pytest.mark.asyncio
async def test_embedding_field_round_trips_through_ledger() -> None:
    """A recorded outcome with embedding=<vec> round-trips through
    ledger.fetch — the cluster_fn sees the same vector it was given.

    This pins write-once + replay-safe semantics: the embedding is
    stamped at write time, never recomputed at replay.
    """
    ledger = InMemoryLedger()
    vec = [0.001 * i for i in range(768)]
    written = await _write_outcome(
        ledger, company_id=_COMPANY_ID,
        nl_question="round-trip me",
        embedding=vec,
    )
    rows = await ledger.fetch(_COMPANY_ID)
    found = [
        r for r in rows
        if r.get("entry_id") == written["entry_id"]
    ]
    assert len(found) == 1
    args = ((found[0].get("payload") or {}).get("args") or {})
    assert isinstance(args.get("embedding"), list)
    assert len(args["embedding"]) == 768
    assert args["embedding"][100] == pytest.approx(0.1)
