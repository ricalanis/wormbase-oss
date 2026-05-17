"""Compounding loop — search -> query_spec -> suggest_correction -> record_outcome.

Asserts the full §4.5 chain:

    1. ``lake.semantic.search`` returns matches over the seeded catalog.
    2. ``lake.semantic.query_spec`` runs the QuerySpec pipeline.
    3. ``lake.query.suggest_correction`` emits ``query_correction_suggested``
       AND carries ``caused_by`` linkage on its agent_query trail.
    4. ``lake.query.record_outcome`` emits ``query_outcome_recorded``
       chained via ``agent_query_id``.
"""
from __future__ import annotations

import pytest
from fastmcp import Client

from wormbase_agent_gateway.mcp_server import build_agent_gateway_mcp_server

from ._helpers import unwrap


pytestmark = pytest.mark.asyncio


async def test_full_compounding_chain(gateway_deps_factory):
    harness = gateway_deps_factory()
    harness.catalog_client.metrics["weekly_revenue"] = {
        "name": "weekly_revenue",
        "source_table_id": "tbl-rev-001",
        "source_kind": "snowflake",
        "expression": "SUM(amount)",
    }
    harness.catalog_client.tables["tbl-rev-001"] = {
        "name": "ANALYTICS.MART.REVENUE",
        "external_id": "tbl-rev-001",
        "upstream_kind": "snowflake",
        "columns": [{"name": "amount"}, {"name": "region"}],
    }
    harness.driver.rows = [{"weekly_revenue": 4_200_000}]

    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        # 1) Semantic search
        search_result = await client.call_tool(
            "lake.semantic.search",
            {"nl_question": "ANALYTICS revenue", "top_k": 5},
        )
        assert not search_result.is_error
        search_data = unwrap(search_result)
        # At least our seeded table should match.
        assert any(
            m["name"] == "ANALYTICS.MART.REVENUE"
            for m in search_data["matches"]
        ), f"expected ANALYTICS.MART.REVENUE in matches; got {search_data['matches']}"

        # 2) Submit a QuerySpec
        spec_result = await client.call_tool(
            "lake.semantic.query_spec",
            {
                "spec": {
                    "metric": "weekly_revenue",
                    "filter": {"region": "EMEA"},
                    "limit": 100,
                },
            },
        )
        assert not spec_result.is_error
        spec_data = unwrap(spec_result)
        original_query_id = spec_data["audit_trail_id"]
        assert spec_data["row_count"] == 1

        # 3) Suggest a correction (simulate empty result follow-up)
        correction_result = await client.call_tool(
            "lake.query.suggest_correction",
            {
                "original_query_id": original_query_id,
                "failure_kind": "empty",
                "failure_detail": "no rows for region=EMEA",
            },
        )
        assert not correction_result.is_error
        correction_data = unwrap(correction_result)
        assert correction_data["original_query_id"] == original_query_id
        assert correction_data["failure_kind"] == "empty"
        assert correction_data["refined_query_spec"]["filter"] is None
        suggestion_audit_id = correction_data["audit_trail_id"]

        # 4) Record the outcome
        outcome_result = await client.call_tool(
            "lake.query.record_outcome",
            {
                "audit_trail_id": original_query_id,
                "used": True,
                "useful": True,
                "nl_question": "ANALYTICS revenue for EMEA",
                "final_query_spec": {
                    "metric": "weekly_revenue",
                    "filter": {"region": "EMEA"},
                },
                "result_summary": {"row_count": 1},
            },
        )
        assert not outcome_result.is_error
        outcome_data = unwrap(outcome_result)
        assert outcome_data["agent_query_id"] == original_query_id
        assert outcome_data["used"] is True
        assert outcome_data["useful"] is True
        assert outcome_data["quality_score"] == "1.0"

    # Now assert ledger linkage:
    rows = await harness.ledger.fetch(harness.deps.company_id)

    # Find suggestion-tool's agent_query trail entries; confirm caused_by.
    suggestion_phases = [
        r for r in rows
        if r["payload"].get("audit_trail_id") == suggestion_audit_id
    ]
    assert len(suggestion_phases) == 4
    for r in suggestion_phases:
        assert r["payload"].get("caused_by") == original_query_id, (
            "suggest_correction's agent_query trail must caused_by the original"
        )

    # Find the query_correction_suggested propose entry.
    correction_proposes = [
        r for r in rows
        if r["kind"] == "propose"
        and r["payload"].get("original_query_id") == original_query_id
        and r["payload"].get("failure_kind") == "empty"
    ]
    assert len(correction_proposes) == 1

    # Find the query_outcome_recorded propose + execute entries
    # (canonical PEVR shape — propose carries target_kind marker,
    # execute carries the outcome payload in ``args``).
    outcome_proposes = [
        r for r in rows
        if r["kind"] == "propose"
        and (r["payload"] or {}).get("target_kind") == "query_outcome_recorded"
        and (r["payload"] or {}).get("ref_id") == original_query_id
    ]
    assert len(outcome_proposes) == 1
    outcome_executes = [
        r for r in rows
        if r["kind"] == "execute"
        and (r["payload"] or {}).get("tool") == "emit_query_outcome_recorded"
        and ((r["payload"] or {}).get("args") or {}).get("agent_query_id")
            == original_query_id
        and ((r["payload"] or {}).get("args") or {}).get("nl_question")
            == "ANALYTICS revenue for EMEA"
    ]
    assert len(outcome_executes) == 1
    assert outcome_executes[0]["payload"]["args"]["quality_score"] == "1.0"


async def test_semantic_gap_no_enclosing_agent_query(gateway_deps_factory):
    """lake.semantic.gap should land a semantic_gap_proposed entry WITHOUT
    any enclosing agent_query PEVR (Addendum 3 §B)."""
    harness = gateway_deps_factory()
    server = build_agent_gateway_mcp_server(harness.deps)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "lake.semantic.gap",
            {
                "nl_question": "did our churn rate drop last week?",
                "reason": "no_match",
                "proposed_metric_name": "weekly_churn_rate",
            },
        )
    assert not result.is_error
    data = unwrap(result)
    assert data["audit_trail_id"]

    rows = await harness.ledger.fetch(harness.deps.company_id)
    # We should see semantic_gap_proposed-shape proposes, but NO
    # agent_query-shape (mcp_tool=lake.semantic.gap) entries.
    aq_for_gap = [
        r for r in rows
        if r["kind"] == "propose"
        and r["payload"].get("mcp_tool") == "lake.semantic.gap"
    ]
    assert aq_for_gap == [], (
        "lake.semantic.gap must NOT emit an enclosing agent_query "
        "(Addendum 3 §B contract). Got: " + repr(aq_for_gap)
    )
    gap_proposes = [
        r for r in rows
        if r["kind"] == "propose"
        and r["payload"].get("nl_question") == "did our churn rate drop last week?"
        and r["payload"].get("proposed_metric_name") == "weekly_churn_rate"
    ]
    assert len(gap_proposes) == 1, f"expected one gap propose; got {gap_proposes}"
    assert gap_proposes[0]["payload"]["reason"] == "no_match"
    assert gap_proposes[0]["payload"]["agent_id"] == harness.agent_id.value
