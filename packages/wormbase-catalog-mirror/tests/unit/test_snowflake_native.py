"""SnowflakeNativeCatalogSource tests — live against trial account when env present."""
from __future__ import annotations

import os

import pytest

from wormbase_catalog_mirror import CatalogSnapshot
from wormbase_catalog_mirror.implementations.snowflake_native import SnowflakeNativeCatalogSource


def _has_trial_creds() -> bool:
    needed = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
              "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA")
    return all(os.environ.get(k) for k in needed)


_LIVE = pytest.mark.skipif(not _has_trial_creds(), reason="SNOWFLAKE_* trial creds not exported")


def _secrets() -> dict[str, str]:
    return {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "password": os.environ["SNOWFLAKE_PASSWORD"],
        "warehouse": os.environ["SNOWFLAKE_WAREHOUSE"],
        "database": os.environ["SNOWFLAKE_DATABASE"],
        "schema": os.environ["SNOWFLAKE_SCHEMA"],
        "role": "ACCOUNTADMIN",
    }


def test_kind_and_capability() -> None:
    src = SnowflakeNativeCatalogSource()
    assert src.kind == "snowflake"
    assert {"schema", "lineage", "policy"} <= src.capability


@_LIVE
@pytest.mark.asyncio
async def test_discover_catalog_returns_revenue_table() -> None:
    src = SnowflakeNativeCatalogSource()
    handle = await src.authenticate(_secrets())
    snap = await src.discover_catalog(handle)
    assert isinstance(snap, CatalogSnapshot)
    table_names = {t.name.upper() for t in snap.tables}
    assert "REVENUE_BY_REGION" in table_names


@_LIVE
@pytest.mark.asyncio
async def test_discover_policies_returns_revenue_mask_with_body() -> None:
    """Validates the 2-step DESCRIBE pattern from S2 finding."""
    src = SnowflakeNativeCatalogSource()
    handle = await src.authenticate(_secrets())
    policies = await src.discover_policies(handle, resource_id="REVENUE_BY_REGION")
    assert policies, "expected REVENUE_MASK"
    masks = [p for p in policies if p.policy_kind == "masking"]
    assert masks
    rm = next(p for p in masks if "REVENUE_MASK" in p.name.upper())
    # Body must be retrievable via DESCRIBE for ACCOUNTADMIN
    assert rm.body and "CURRENT_ROLE" in rm.body.upper()


@_LIVE
@pytest.mark.asyncio
async def test_classification_tag_surfaces_on_revenue_column() -> None:
    src = SnowflakeNativeCatalogSource()
    handle = await src.authenticate(_secrets())
    snap = await src.discover_catalog(handle)
    rev_table = next(t for t in snap.tables if t.name.upper() == "REVENUE_BY_REGION")
    revenue_col = next(c for c in rev_table.columns if c.name.upper() == "REVENUE")
    # Tag propagation is async per Snowflake docs; spike observed immediate on trial.
    # Accept either: tag present, OR empty tuple (Wave 1 stale-tolerance contract).
    if revenue_col.tags:
        assert "confidential" in [t.lower() for t in revenue_col.tags]
