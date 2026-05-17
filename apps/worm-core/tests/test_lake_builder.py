"""Tests for the medallion lake (Step 2 of the canonical product arc).

Covers:
  * Bronze profiling on a 5-row CSV.
  * Silver type inference + PII classification.
  * Gold aggregate derivation (sum / mean / count_distinct).
  * Medallion cascade end-to-end ledger writes.
  * LakeDiscoveryFlow mock catalog walks for snowflake / postgres / s3.
  * KPI proposal emitted when gold detects a revenue + date table.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from wormbase_core.flows import LakeDiscoveryFlow
from wormbase_core.medallion import (
    MedallionCascade,
    derive_gold,
    find_join_candidates,
    infer_columns,
    profile_bronze,
)
from wormbase_core.source_builder import SourceBuilder, SourceProposal


# -- bronze ----------------------------------------------------------


CSV_FIVE_ROWS = (
    "id,revenue,created_at\n"
    "1,100.00,2026-04-01\n"
    "2,200.50,2026-04-02\n"
    "3,300.75,2026-04-03\n"
    "4,400.00,2026-04-04\n"
    "5,500.25,2026-04-05\n"
)


def test_profile_bronze_csv_counts_rows_and_cols(tmp_path: Path) -> None:
    f = tmp_path / "sales.csv"
    f.write_text(CSV_FIVE_ROWS)
    profile = profile_bronze(str(f), mime="text/csv")
    assert profile.row_count == 5
    assert profile.col_count == 3
    assert profile.columns == ["id", "revenue", "created_at"]
    assert profile.byte_count > 0
    assert profile.mime == "text/csv"
    # schema_hash must be deterministic given the same column header.
    again = profile_bronze(str(f), mime="text/csv")
    assert profile.schema_hash == again.schema_hash


def test_profile_bronze_handles_missing_uri() -> None:
    profile = profile_bronze("file:///does/not/exist.csv")
    assert profile.row_count == 0
    assert profile.col_count == 0
    assert profile.byte_count == 0
    # schema_hash is still deterministic (sha256 of empty bytes).
    assert len(profile.schema_hash) == 64


def test_profile_bronze_accepts_raw_bytes() -> None:
    profile = profile_bronze(
        "s3://bucket/x.csv",
        mime="text/csv",
        raw_bytes=CSV_FIVE_ROWS.encode("utf-8"),
    )
    assert profile.row_count == 5
    assert profile.col_count == 3


# -- silver ----------------------------------------------------------


def test_infer_columns_detects_int_float_date_and_pii() -> None:
    profile = profile_bronze(
        "x.csv",
        mime="text/csv",
        raw_bytes=(
            "user_id,email,signed_up_at,balance\n"
            "1,a@a.com,2026-01-01,100.50\n"
            "2,b@b.com,2026-01-02,200.75\n"
        ).encode("utf-8"),
    )
    cols = infer_columns(profile)
    by_name = {c.name: c for c in cols}
    assert by_name["user_id"].type == "int"
    assert by_name["balance"].type == "float"
    assert by_name["signed_up_at"].type == "date"
    assert by_name["email"].type == "string"
    assert by_name["email"].classification == "pii"
    assert by_name["user_id"].classification == "internal"


def test_find_join_candidates_matches_on_column_name() -> None:
    profile_a = profile_bronze(
        "a.csv",
        mime="text/csv",
        raw_bytes=b"customer_id,amount\n1,10.0\n",
    )
    profile_b = profile_bronze(
        "b.csv",
        mime="text/csv",
        raw_bytes=b"customer_id,plan\n1,premium\n",
    )
    profile_c = profile_bronze(
        "c.csv",
        mime="text/csv",
        raw_bytes=b"unrelated_field,value\nx,1\n",
    )
    cols_a = infer_columns(profile_a)
    bid = uuid4()
    cid = uuid4()
    others = {
        bid: [c.name for c in infer_columns(profile_b)],
        cid: [c.name for c in infer_columns(profile_c)],
    }
    hits = find_join_candidates(cols_a, others)
    assert hits == [bid]


# -- gold ------------------------------------------------------------


def test_derive_gold_sums_revenue_and_proposes_kpi_when_date_present() -> None:
    profile = profile_bronze(
        "x.csv",
        mime="text/csv",
        raw_bytes=CSV_FIVE_ROWS.encode("utf-8"),
    )
    cols = infer_columns(profile)
    gold = derive_gold(profile, cols)
    assert gold is not None
    assert gold.value["metric"] == "sum"
    assert gold.value["column"] == "revenue"
    assert gold.suggests_kpi is True
    assert gold.kpi_label == "monthly total revenue"
    assert gold.kpi_unit == "USD"
    # Sum of the 5 sample rows = 1501.50
    assert abs(gold.value["result"] - 1501.5) < 1e-6


def test_derive_gold_falls_back_to_mean_then_count_distinct() -> None:
    # Numeric only, no revenue hint, no date column → mean.
    profile = profile_bronze(
        "x.csv",
        mime="text/csv",
        raw_bytes=b"a,b\n1,foo\n2,bar\n3,baz\n",
    )
    cols = infer_columns(profile)
    gold = derive_gold(profile, cols)
    assert gold is not None
    assert gold.value["metric"] == "mean"
    assert gold.value["column"] == "a"


# -- cascade ----------------------------------------------------------


async def test_medallion_cascade_writes_three_entries(ledger, company_id, clock):
    cascade = MedallionCascade(ledger, clock=clock)
    await cascade.cascade(
        company_id=company_id,
        source_id=uuid4(),
        uri="s3://demo/sales.csv",
        mime="text/csv",
        raw_bytes=b"id,balance\n1,10.50\n2,20.25\n",
    )
    rows = await ledger.fetch(company_id)
    tools = [r["payload"]["tool"] for r in rows if r["kind"] == "execute"]
    assert "emit_source_bronzed" in tools
    assert "emit_source_silvered" in tools
    assert "emit_source_golded" in tools


async def test_medallion_cascade_emits_kpi_proposal_for_revenue(
    ledger, company_id, clock,
):
    cascade = MedallionCascade(ledger, clock=clock)
    await cascade.cascade(
        company_id=company_id,
        source_id=uuid4(),
        uri="file:///fake/sales.csv",
        mime="text/csv",
        raw_bytes=CSV_FIVE_ROWS.encode("utf-8"),
    )
    rows = await ledger.fetch(company_id)
    tools = [r["payload"]["tool"] for r in rows if r["kind"] == "execute"]
    assert "emit_kpi_proposed" in tools
    kpi_entry = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_kpi_proposed"
    ][0]
    assert kpi_entry["payload"]["args"]["unit"] == "USD"
    assert "revenue" in kpi_entry["payload"]["args"]["label"]


async def test_medallion_cascade_finds_join_candidates(
    ledger, company_id, clock,
):
    cascade = MedallionCascade(ledger, clock=clock)
    sid_a = uuid4()
    sid_b = uuid4()
    await cascade.cascade(
        company_id=company_id, source_id=sid_a,
        uri="file:///a.csv", mime="text/csv",
        raw_bytes=b"customer_id,plan\n1,starter\n2,pro\n",
    )
    await cascade.cascade(
        company_id=company_id, source_id=sid_b,
        uri="file:///b.csv", mime="text/csv",
        raw_bytes=b"customer_id,balance\n1,100\n2,200\n",
    )
    rows = await ledger.fetch(company_id)
    silver_for_b = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_silvered"
        and r["payload"]["args"]["source_id"] == str(sid_b)
    ][0]
    join_candidates = silver_for_b["payload"]["args"]["join_candidates"]
    assert str(sid_a) in join_candidates


# -- lake_discovery flow ---------------------------------------------


async def test_lake_discovery_snowflake_emits_proposals_and_summary(
    ledger, company_id, clock,
):
    builder = SourceBuilder(ledger, clock)
    flow = LakeDiscoveryFlow(builder, ledger)
    summary = await flow.discover(
        company_id, "snowflake://demo/wh/analytics",
    )
    assert summary["lake_kind"] == "snowflake"
    assert summary["tables_seen"] >= 5
    assert summary["sources_proposed"] == summary["tables_seen"]
    rows = await ledger.fetch(company_id)
    proposals = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_proposed"
        and r["payload"]["args"]["added_via_flow"] == "lake_discovery"
    ]
    assert len(proposals) == summary["sources_proposed"]
    discovered = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_lake_discovered"
    ]
    assert len(discovered) == 1
    assert discovered[0]["payload"]["args"]["lake_kind"] == "snowflake"


async def test_lake_discovery_postgres_emits_database_kind_proposals(
    ledger, company_id, clock,
):
    builder = SourceBuilder(ledger, clock)
    flow = LakeDiscoveryFlow(builder, ledger)
    summary = await flow.discover(company_id, "postgres://host/db")
    assert summary["lake_kind"] == "postgres"
    rows = await ledger.fetch(company_id)
    proposals = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_proposed"
    ]
    for p in proposals:
        assert p["payload"]["args"]["source_kind"] == "database"


async def test_lake_discovery_s3_emits_blob_kind_proposals(
    ledger, company_id, clock,
):
    builder = SourceBuilder(ledger, clock)
    flow = LakeDiscoveryFlow(builder, ledger)
    summary = await flow.discover(company_id, "s3://bucket/prefix")
    assert summary["lake_kind"] == "s3"
    rows = await ledger.fetch(company_id)
    proposals = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] == "emit_source_proposed"
    ]
    assert len(proposals) >= 2
    for p in proposals:
        assert p["payload"]["args"]["source_kind"] == "blob"


async def test_lake_discovery_rejects_unknown_scheme(
    ledger, company_id, clock,
):
    builder = SourceBuilder(ledger, clock)
    flow = LakeDiscoveryFlow(builder, ledger)
    with pytest.raises(ValueError, match="unsupported lake URI scheme"):
        await flow.discover(company_id, "https://api.example/lake")


# -- end-to-end: drop -> bronze -> silver -> gold ordering -----------


async def test_drop_with_cascade_writes_full_medallion_in_order(
    ledger, company_id, clock,
):
    """Drop a CSV via SourceBuilder then run the medallion cascade.

    Verifies the canonical Step 2 order: source_proposed → source_bronzed
    → source_silvered → source_golded.
    """
    from wormbase_core.flows import cascade_after_propose

    builder = SourceBuilder(ledger, clock)
    cascade = MedallionCascade(ledger, clock=clock)
    proposal = SourceProposal(
        proposed_uri="file:///demo/sales.csv",
        proposed_type="file",
        proposed_domain="finance",
        proposed_classification="internal",
        added_via_flow="drop_and_profile",
        added_in_response_to="channel_msg:demo",
        company_id=company_id,
    )
    cid = await builder.propose(proposal)
    await cascade_after_propose(
        builder, cascade,
        correlation_id=str(cid),
        company_id=company_id,
        uri=proposal.proposed_uri,
        mime="text/csv",
        raw_bytes=CSV_FIVE_ROWS.encode("utf-8"),
    )
    rows = await ledger.fetch(company_id)
    medallion_tools_in_order = [
        r["payload"]["tool"]
        for r in rows
        if r["kind"] == "execute"
        and r["payload"]["tool"] in {
            "emit_source_proposed",
            "emit_source_bronzed",
            "emit_source_silvered",
            "emit_source_golded",
        }
    ]
    assert medallion_tools_in_order == [
        "emit_source_proposed",
        "emit_source_bronzed",
        "emit_source_silvered",
        "emit_source_golded",
    ]
