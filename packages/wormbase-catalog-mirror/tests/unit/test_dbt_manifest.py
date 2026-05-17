"""DbtManifestCatalogSource tests — production-quality dbt manifest parsing."""
from __future__ import annotations

from pathlib import Path

import pytest

from wormbase_catalog_mirror import (
    CatalogSnapshot,
    ColumnMeta,
    ManifestVersionUnsupportedError,
)
from wormbase_catalog_mirror.implementations.dbt_manifest import (
    DbtManifestCatalogSource,
    parse_dbt_manifest,
)


def test_kind_and_capability() -> None:
    src = DbtManifestCatalogSource(manifest_path=Path("/dev/null"))
    assert src.kind == "dbt"
    assert {"schema", "lineage", "semantic_layer"} <= src.capability


@pytest.mark.asyncio
async def test_authenticate_returns_handle() -> None:
    src = DbtManifestCatalogSource(manifest_path=Path("/dev/null"))
    h = await src.authenticate({})
    assert h is not None  # opaque handle


def test_parse_yields_nonempty_snapshot(jaffle_shop_manifest_path: Path) -> None:
    snap = parse_dbt_manifest(jaffle_shop_manifest_path)
    assert isinstance(snap, CatalogSnapshot)
    assert len(snap.tables) >= 8, f"expected 8+ tables (5 model + 3 seed), got {len(snap.tables)}"


def test_includes_both_model_and_seed_nodes(jaffle_shop_manifest_path: Path) -> None:
    """Per S1 finding: parser must whitelist tableshaped resource types, not 'model' only."""
    snap = parse_dbt_manifest(jaffle_shop_manifest_path)
    kinds = {t.external_id.split(".")[0] for t in snap.tables}
    assert "model" in kinds, f"missing model.*; got {kinds}"
    assert "seed" in kinds, f"missing seed.*; got {kinds}"


def test_column_meta_handles_null_type(jaffle_shop_manifest_path: Path) -> None:
    """Per S1 finding: data_type may be null when dbt docs generate hasn't run."""
    snap = parse_dbt_manifest(jaffle_shop_manifest_path)
    for t in snap.tables:
        for c in t.columns:
            assert isinstance(c, ColumnMeta)
            # type may be None — should not raise


def test_lineage_includes_both_kinds(jaffle_shop_manifest_path: Path) -> None:
    snap = parse_dbt_manifest(jaffle_shop_manifest_path)
    assert snap.lineage.edges, "jaffle_shop has staging->mart deps; lineage must be nonempty"
    table_ids = {t.external_id for t in snap.tables}
    for edge in snap.lineage.edges:
        assert edge.upstream in table_ids or edge.upstream.startswith("source."), \
            f"unexpected upstream {edge.upstream}"
        assert edge.downstream in table_ids


def test_snapshot_hash_is_deterministic(jaffle_shop_manifest_path: Path) -> None:
    a = parse_dbt_manifest(jaffle_shop_manifest_path)
    b = parse_dbt_manifest(jaffle_shop_manifest_path)
    assert a.snapshot_hash == b.snapshot_hash


def test_unsupported_manifest_version_raises(tmp_path: Path) -> None:
    p = tmp_path / "bogus.json"
    p.write_text('{"metadata": {"dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v3.json"}, "nodes": {}}')
    with pytest.raises(ManifestVersionUnsupportedError):
        parse_dbt_manifest(p)


def test_metrics_extracted_when_present(tmp_path: Path) -> None:
    """When the manifest carries metrics, extract them. jaffle_shop_classic has none — synthesize a metric-bearing fixture inline."""
    p = tmp_path / "with_metrics.json"
    p.write_text("""
    {
      "metadata": {"dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"},
      "nodes": {},
      "metrics": {
        "metric.x.revenue_q3": {
          "name": "revenue_q3",
          "description": "Q3 revenue",
          "type_params": {"measure": {"name": "sum_revenue"}},
          "filter": {"where_sql_template": "quarter = 'Q3'"}
        }
      },
      "semantic_models": {}
    }
    """)
    snap = parse_dbt_manifest(p)
    assert any(m.name == "revenue_q3" for m in snap.metrics)


@pytest.mark.asyncio
async def test_discover_catalog_async(jaffle_shop_manifest_path: Path) -> None:
    src = DbtManifestCatalogSource(manifest_path=jaffle_shop_manifest_path)
    handle = await src.authenticate({})
    snap = await src.discover_catalog(handle)
    assert isinstance(snap, CatalogSnapshot)
    assert len(snap.tables) >= 8
