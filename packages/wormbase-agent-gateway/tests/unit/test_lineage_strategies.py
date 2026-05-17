"""L3 Sub-wave B — strategy tests.

Per-strategy behaviour pinned independently:

  * :class:`NamingHeuristicStrategy` — exact / edit-distance / substring
    matching, stop-list filtering, confidence tiers.
  * :class:`SampleOverlapStrategy` — Jaccard threshold, value-richness
    minimum, table-size cap.
  * :class:`DbtManifestStrategy` — only fires for ``source_kind="dbt"``,
    walks ``ref()`` + ``source()`` calls, whole-table edges only.
"""
from __future__ import annotations

import pytest

from wormbase_agent_gateway.lineage import (
    CatalogTable,
    DbtManifestStrategy,
    NamingHeuristicStrategy,
    SampleOverlapStrategy,
)


# ---------------------------------------------------------------------------
# NamingHeuristicStrategy
# ---------------------------------------------------------------------------


def _table(table_id: str, columns: tuple[str, ...], kind: str = "postgres") -> CatalogTable:
    return CatalogTable(
        table_id=table_id,
        columns=columns,
        source_kind=kind,
        metadata={},
    )


@pytest.mark.asyncio
async def test_naming_heuristic_exact_match_outside_stop_list() -> None:
    """Exact non-stop-list match → 0.85 confidence ``exact`` tag."""
    strategy = NamingHeuristicStrategy()
    src = _table("src.public.orders", ("customer_id",))
    tgt = _table("tgt.public.customers", ("customer_id",))

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert len(edges) == 1
    edge = edges[0]
    assert edge.confidence == 0.85
    assert edge.strategy == "naming_heuristic"
    assert edge.src_column == "customer_id"
    assert edge.tgt_column == "customer_id"
    assert edge.evidence["match_kind"] == "exact"


@pytest.mark.asyncio
async def test_naming_heuristic_stop_list_rejects_common_columns() -> None:
    """``id`` is in the stop list → no edge proposed even on exact match."""
    strategy = NamingHeuristicStrategy()
    src = _table("src.public.orders", ("id",))
    tgt = _table("tgt.public.customers", ("id",))

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert edges == [], "id in stop_list must NOT propose an edge"


@pytest.mark.asyncio
async def test_naming_heuristic_edit_distance_handles_abbreviations() -> None:
    """``cust_id`` ↔ ``customer_id`` — too far for default edit-distance,
    but close enough by substring fallback."""
    strategy = NamingHeuristicStrategy()
    src = _table("src.public.orders", ("cust_id",))
    tgt = _table("tgt.public.customers", ("cust_id",))

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert len(edges) == 1
    assert edges[0].confidence == 0.85


@pytest.mark.asyncio
async def test_naming_heuristic_edit_distance_one_char_typo() -> None:
    """One-char typo (edit distance 1) → 0.7 ``edit_distance`` tag."""
    strategy = NamingHeuristicStrategy()
    src = _table("src.public.orders", ("customer_idx",))
    tgt = _table("tgt.public.customers", ("customer_id",))

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert len(edges) >= 1
    edge = next(
        (e for e in edges if e.evidence.get("match_kind") == "edit_distance"),
        None,
    )
    assert edge is not None
    assert edge.confidence == 0.7


@pytest.mark.asyncio
async def test_naming_heuristic_substring_fallback() -> None:
    """One column is a prefix/suffix of the other → 0.6 substring."""
    strategy = NamingHeuristicStrategy()
    src = _table("src.public.orders", ("customer",))
    tgt = _table("tgt.public.customers", ("customer_full_name",))

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    substring_edges = [
        e for e in edges if e.evidence.get("match_kind") == "substring"
    ]
    assert len(substring_edges) >= 1
    assert all(e.confidence == 0.6 for e in substring_edges)


@pytest.mark.asyncio
async def test_naming_heuristic_no_match_returns_empty() -> None:
    """Wholly different column names → no edges proposed."""
    strategy = NamingHeuristicStrategy()
    src = _table("src.public.orders", ("alpha",))
    tgt = _table("tgt.public.customers", ("omega",))

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert edges == []


@pytest.mark.asyncio
async def test_naming_heuristic_self_table_skipped() -> None:
    """Source table compared to itself → no edges (would be self-loop)."""
    strategy = NamingHeuristicStrategy()
    src = _table("src.public.orders", ("customer_id",))

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[src],
    )
    assert edges == []


@pytest.mark.asyncio
async def test_naming_heuristic_custom_stop_list_override() -> None:
    """Custom ``stop_list`` replaces defaults."""
    custom_stop = frozenset({"customer_id"})
    strategy = NamingHeuristicStrategy(stop_list=custom_stop)
    src = _table("src.public.orders", ("customer_id", "amount"))
    tgt = _table("tgt.public.customers", ("customer_id", "amount"))

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    # customer_id rejected; amount allowed
    matched_cols = {(e.src_column, e.tgt_column) for e in edges}
    assert ("amount", "amount") in matched_cols
    assert ("customer_id", "customer_id") not in matched_cols


@pytest.mark.asyncio
async def test_naming_heuristic_multiple_targets() -> None:
    """Walks all candidate targets, returns edges from each."""
    strategy = NamingHeuristicStrategy()
    src = _table("src.public.orders", ("customer_id",))
    tgt_a = _table("tgt.public.customers", ("customer_id",))
    tgt_b = _table("tgt.public.profiles", ("customer_id",))

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt_a, tgt_b],
    )
    targets = {e.tgt_table_id for e in edges}
    assert "tgt.public.customers" in targets
    assert "tgt.public.profiles" in targets


# ---------------------------------------------------------------------------
# SampleOverlapStrategy
# ---------------------------------------------------------------------------


class _FakeSampler:
    """Test double: canned per-table-column samples + size estimates."""

    def __init__(
        self,
        *,
        samples: dict[tuple[str, str], set[str]] | None = None,
        sizes: dict[str, int] | None = None,
        default_size: int = 100,
    ) -> None:
        self.samples = samples or {}
        self.sizes = sizes or {}
        self.default_size = default_size
        self.sample_calls: list[tuple[str, str, int]] = []
        self.size_calls: list[str] = []

    async def sample_column(self, table_id: str, column: str, n: int) -> set[str]:
        self.sample_calls.append((table_id, column, n))
        return self.samples.get((table_id, column), set())

    async def estimate_table_size(self, table_id: str) -> int:
        self.size_calls.append(table_id)
        return self.sizes.get(table_id, self.default_size)


@pytest.mark.asyncio
async def test_sample_overlap_high_jaccard_proposes_edge() -> None:
    """Jaccard ~0.9 → confidence ~0.87."""
    src = _table("src.public.orders", ("user_id",))
    tgt = _table("tgt.public.users", ("uid",))
    src_sample = {f"u{i}" for i in range(100)}
    tgt_sample = ({f"u{i}" for i in range(100)} | {"extra1", "extra2", "extra3"})
    sampler = _FakeSampler(samples={
        ("src.public.orders", "user_id"): src_sample,
        ("tgt.public.users", "uid"): tgt_sample,
    })
    strategy = SampleOverlapStrategy(sampler=sampler)

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert len(edges) == 1
    edge = edges[0]
    assert edge.strategy == "sample_overlap"
    assert edge.confidence >= 0.85
    assert edge.evidence["sample_overlap_ratio"] >= 0.9


@pytest.mark.asyncio
async def test_sample_overlap_below_threshold_no_edge() -> None:
    """Jaccard < ``jaccard_threshold`` → no edge."""
    src = _table("src.public.orders", ("user_id",))
    tgt = _table("tgt.public.events", ("session_id",))
    sampler = _FakeSampler(samples={
        ("src.public.orders", "user_id"): {"a", "b", "c", "d", "e", "f", "g", "h", "i", "j"},
        ("tgt.public.events", "session_id"): {"x", "y", "z", "w", "v", "u", "t", "s", "r", "q"},
    })
    strategy = SampleOverlapStrategy(sampler=sampler, jaccard_threshold=0.5)

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert edges == []


@pytest.mark.asyncio
async def test_sample_overlap_value_richness_minimum_enforced() -> None:
    """Source column with fewer than ``value_richness_min`` distinct
    values → skipped (sample too thin)."""
    src = _table("src.public.orders", ("flag",))
    tgt = _table("tgt.public.users", ("flag",))
    sampler = _FakeSampler(samples={
        ("src.public.orders", "flag"): {"true", "false"},  # only 2 distinct
        ("tgt.public.users", "flag"): {"true", "false"},
    })
    strategy = SampleOverlapStrategy(
        sampler=sampler, value_richness_min=10,
    )

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert edges == []


@pytest.mark.asyncio
async def test_sample_overlap_max_table_size_skips_huge_source() -> None:
    """Source table > ``max_table_size`` → early-out, no edges."""
    src = _table("src.public.huge", ("user_id",))
    tgt = _table("tgt.public.users", ("uid",))
    sampler = _FakeSampler(
        sizes={"src.public.huge": 100_000_001},
        default_size=1000,
    )
    strategy = SampleOverlapStrategy(
        sampler=sampler, max_table_size=10_000_000,
    )

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt],
    )
    assert edges == []
    # sample_column never called for huge source
    assert sampler.sample_calls == []


@pytest.mark.asyncio
async def test_sample_overlap_max_table_size_skips_huge_target() -> None:
    """Target table > ``max_table_size`` → skipped for that target."""
    src = _table("src.public.orders", ("user_id",))
    huge_tgt = _table("tgt.public.huge", ("user_id",))
    sampler = _FakeSampler(
        sizes={"tgt.public.huge": 100_000_001},
        samples={
            ("src.public.orders", "user_id"): {f"u{i}" for i in range(20)},
        },
        default_size=1000,
    )
    strategy = SampleOverlapStrategy(
        sampler=sampler, max_table_size=10_000_000,
    )

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[huge_tgt],
    )
    assert edges == []


@pytest.mark.asyncio
async def test_sample_overlap_self_table_skipped() -> None:
    """Same table_id source + target → not proposed."""
    src = _table("src.public.orders", ("user_id",))
    sampler = _FakeSampler(samples={
        ("src.public.orders", "user_id"): {f"u{i}" for i in range(50)},
    })
    strategy = SampleOverlapStrategy(sampler=sampler)

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[src],
    )
    assert edges == []


@pytest.mark.asyncio
async def test_sample_overlap_evidence_carries_intersection_metadata() -> None:
    """Edge evidence carries Jaccard + intersection + union counts."""
    src = _table("src.public.orders", ("user_id",))
    tgt = _table("tgt.public.users", ("uid",))
    src_sample = {f"u{i}" for i in range(20)}
    tgt_sample = {f"u{i}" for i in range(15)}  # overlap = 15
    sampler = _FakeSampler(samples={
        ("src.public.orders", "user_id"): src_sample,
        ("tgt.public.users", "uid"): tgt_sample,
    })
    strategy = SampleOverlapStrategy(sampler=sampler)

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[tgt], sample_size=500,
    )
    assert len(edges) == 1
    ev = edges[0].evidence
    assert ev["intersection_n"] == 15
    assert ev["union_n"] == 20
    assert ev["sampled_n"] == 500
    assert ev["src_sample_richness"] == 20


# ---------------------------------------------------------------------------
# DbtManifestStrategy
# ---------------------------------------------------------------------------


class _FakeManifestReader:
    def __init__(
        self,
        *,
        refs: dict[str, list[str]] | None = None,
        sources: dict[str, list[str]] | None = None,
    ) -> None:
        self.refs = refs or {}
        self.sources = sources or {}

    async def get_refs_for_model(self, model_id: str) -> list[str]:
        return self.refs.get(model_id, [])

    async def get_source_refs(self, model_id: str) -> list[str]:
        return self.sources.get(model_id, [])


@pytest.mark.asyncio
async def test_dbt_manifest_strategy_only_fires_for_dbt_source_kind() -> None:
    """Non-dbt source kinds → no edges (manifest strategy is dbt-only)."""
    reader = _FakeManifestReader(refs={"any": ["other"]})
    strategy = DbtManifestStrategy(manifest_reader=reader)

    pg_src = _table("src.public.orders", ("id",), kind="postgres")
    tgt = _table("tgt.public.customers", ("id",), kind="postgres")
    edges = await strategy.infer_edges(
        source_table=pg_src, candidate_targets=[tgt],
    )
    assert edges == []


@pytest.mark.asyncio
async def test_dbt_manifest_strategy_emits_edge_for_ref_call() -> None:
    """``ref()`` upstream → edge from upstream to this model with conf 0.99."""
    src = _table("dbt.staging.orders", ("id",), kind="dbt")
    upstream = _table("dbt.raw.orders_raw", ("id",), kind="dbt")
    reader = _FakeManifestReader(
        refs={"dbt.staging.orders": ["dbt.raw.orders_raw"]},
    )
    strategy = DbtManifestStrategy(manifest_reader=reader)

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[upstream],
    )
    assert len(edges) == 1
    edge = edges[0]
    assert edge.strategy == "dbt_manifest"
    assert edge.confidence == 0.99
    assert edge.src_table_id == "dbt.raw.orders_raw"
    assert edge.tgt_table_id == "dbt.staging.orders"
    # Whole-table — no column-grain pin from manifest
    assert edge.src_column is None
    assert edge.tgt_column is None
    assert edge.evidence["ref_kind"] == "ref"


@pytest.mark.asyncio
async def test_dbt_manifest_strategy_emits_edge_for_source_call() -> None:
    """``source()`` raw → edge from raw to model with ``ref_kind=source``."""
    src = _table("dbt.staging.events", ("id",), kind="dbt")
    raw = _table("dbt.raw.events", ("id",), kind="dbt")
    reader = _FakeManifestReader(
        sources={"dbt.staging.events": ["dbt.raw.events"]},
    )
    strategy = DbtManifestStrategy(manifest_reader=reader)

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[raw],
    )
    assert len(edges) == 1
    assert edges[0].evidence["ref_kind"] == "source"
    assert edges[0].confidence == 0.99


@pytest.mark.asyncio
async def test_dbt_manifest_strategy_skips_unknown_upstream() -> None:
    """A ``ref()`` referencing a table NOT in candidate_targets → skipped."""
    src = _table("dbt.staging.orders", ("id",), kind="dbt")
    reader = _FakeManifestReader(
        refs={"dbt.staging.orders": ["dbt.raw.NEVER_HEARD_OF"]},
    )
    strategy = DbtManifestStrategy(manifest_reader=reader)

    # No matching candidate
    other = _table("dbt.staging.products", ("id",), kind="dbt")
    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[other],
    )
    assert edges == []


@pytest.mark.asyncio
async def test_dbt_manifest_strategy_self_loop_filtered() -> None:
    """A manifest that lists the model as its own upstream → filtered out."""
    src = _table("dbt.staging.orders", ("id",), kind="dbt")
    reader = _FakeManifestReader(
        refs={"dbt.staging.orders": ["dbt.staging.orders"]},
    )
    strategy = DbtManifestStrategy(manifest_reader=reader)

    edges = await strategy.infer_edges(
        source_table=src, candidate_targets=[src],
    )
    assert edges == []
