"""P7 contract: Snowflake column-tag passthrough + masked-column gate refusal.

This test validates the end-to-end demo path described in PRD §7 P7:

    Snowflake COLUMN.TAG  →  Profile.column_tags  →  Resource.classification
                          →  MaskedColumnRefusalGate refuses query
                          →  ledger ``gate_fired`` entry carries
                             policy_name + offending column + tag chain
                          →  /trace can jump back to /sources/<id>
                             via ``subject_ref`` + ``source_id`` fields

**Why a Snowflake mock is the right choice here.**

Per the PRD's "no flow-bypass" rule, the only acceptable mock in this
codebase is a Snowflake mock. Snowflake instances are not reliable in
CI (network, OAuth, VPC peering, role provisioning) and warming a real
account up for every PR build would gate the merge on out-of-band ops
work. The PRD's correctness property is the **gate-fire path**: that
when a tag exists on a column, a query touching that column refuses
and the ledger entry chain carries the column-tag back to the source.
That property is purely a function of (a) the connector's profile
output shape and (b) the gate's behavior over that shape — neither of
which depends on the warehouse runtime. We therefore mock the Snowflake
cursor at the ``snowflake.connector.connect`` boundary (the same
strategy ``packages/connectors/tests/test_snowflake.py`` already uses)
and assert the property end-to-end through the WormBase ledger.

A real-Snowflake variant of this test (gated on a ``WORMBASE_LIVE_SNOW``
env var) is intentionally NOT shipped in this contract suite — it
belongs in the optional ``tests/integration/`` live-services suite.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from wormbase_lake_surfaces.snowflake import (
    SNOWFLAKE_TAG_MAPPINGS,
    SnowflakeSurfaceDriver,
)
from wormbase_lake_surfaces.types import AuthHandle
from wormbase_governance.policies.masked_column_refusal import (
    GATE_NAME,
    POLICY_NAME,
    MaskedColumnQuery,
    MaskedColumnRefusalGate,
)
from wormbase_ledger import InMemoryLedger

_SNOW_KWARGS = {
    "account": "abc.us-east-1",
    "user": "wb",
    "password": "secret",
    "warehouse": "WB_WH",
    "database": "WB_DB",
}

_TEST_COMPANY_ID = uuid4()


# ---------------------------------------------------------------------------
# Snowflake mock — programmable per-execute fetchall responses.
#
# The connector's ``_profile_sync`` issues three SQL statements in
# order:
#   1. DESCRIBE TABLE "<schema>"."<table>"  -> fetchall (column rows)
#   2. SELECT ROW_COUNT FROM INFORMATION_SCHEMA.TABLES ... -> fetchone
#   3. INFORMATION_SCHEMA.TAG_REFERENCES_ALL_COLUMNS(...)  -> fetchall
#
# We dispatch ``fetchall`` based on the most-recent ``execute`` SQL
# substring so the test exercises the real query routing.
# ---------------------------------------------------------------------------


@pytest.fixture
def snowflake_mock() -> Any:
    """Mocks snowflake.connector.connect with tag-aware DESCRIBE/TAG routing."""
    fake_cur = MagicMock()
    last_sql: dict[str, str] = {"sql": ""}

    # Per-table column rows for DESCRIBE TABLE
    describe_rows = [
        ("ID", "NUMBER", "N", None),
        ("EMAIL", "VARCHAR", "Y", None),
        ("NAME", "VARCHAR", "Y", None),
        ("SSN", "VARCHAR", "Y", None),
    ]

    # Snowflake column tags — the COLUMN.TAG values that
    # governance_passthrough must propagate end-to-end.
    tag_rows = [
        # (COLUMN_NAME, TAG_NAME, TAG_VALUE)
        ("EMAIL", "PII", "EMAIL"),
        ("SSN", "PII", "SSN"),
    ]

    def _execute(sql: str, *args: Any, **kwargs: Any) -> None:
        last_sql["sql"] = sql

    def _fetchall() -> list[tuple[Any, ...]]:
        sql = last_sql["sql"].upper()
        if "DESCRIBE TABLE" in sql:
            return describe_rows
        if "TAG_REFERENCES" in sql:
            return tag_rows
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return []
        return []

    def _fetchone() -> tuple[Any, ...]:
        sql = last_sql["sql"].upper()
        if "CURRENT_VERSION" in sql:
            return ("9.5.1",)
        if "ROW_COUNT" in sql:
            return (4242,)
        return ()

    fake_cur.execute = MagicMock(side_effect=_execute)
    fake_cur.fetchall = MagicMock(side_effect=_fetchall)
    fake_cur.fetchone = MagicMock(side_effect=_fetchone)
    fake_cur.description = []
    fake_cur.close = MagicMock()

    fake_conn = MagicMock()
    fake_conn.cursor = MagicMock(return_value=fake_cur)
    fake_conn.close = MagicMock()

    with patch(
        "snowflake.connector.connect", return_value=fake_conn
    ) as m:
        yield m, fake_conn, fake_cur


# ---------------------------------------------------------------------------
# 1. Tag mapping is valid + advertises governance_passthrough capability
# ---------------------------------------------------------------------------


def test_snowflake_advertises_governance_passthrough_capability() -> None:
    c = SnowflakeSurfaceDriver()
    assert "governance_passthrough" in c.capability
    assert {"discover", "profile", "sample"}.issubset(c.capability)


def test_snowflake_tag_mapping_covers_canonical_classes() -> None:
    # The minimum classifications the demo path relies on.
    assert SNOWFLAKE_TAG_MAPPINGS["pii"] == "pii"
    assert SNOWFLAKE_TAG_MAPPINGS["regulated"] == "regulated"
    assert SNOWFLAKE_TAG_MAPPINGS["confidential"] == "confidential"
    # Common Snowflake tag values are recognized.
    assert SNOWFLAKE_TAG_MAPPINGS["email"] == "pii"
    assert SNOWFLAKE_TAG_MAPPINGS["ssn"] == "regulated"


# ---------------------------------------------------------------------------
# 2. Profile propagates Snowflake column tags into Profile output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_propagates_column_tags(snowflake_mock: Any) -> None:
    """Profile must surface column tags + per-column classification + rollup."""
    connector = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _SNOW_KWARGS},
    )
    profile = await connector.profile(handle, "PUBLIC.CUSTOMERS")

    by_name = {col["name"]: col for col in profile.columns}

    # EMAIL has TAG = (PII, EMAIL) -> classification = "pii"
    assert by_name["EMAIL"]["classification"] == "pii"
    assert any(
        t["name"] == "PII" and t["value"] == "EMAIL"
        for t in by_name["EMAIL"]["tags"]
    )

    # SSN has TAG = (PII, SSN) -> SSN tag value escalates to "regulated"
    assert by_name["SSN"]["classification"] == "regulated"

    # ID and NAME have no column tags -> no classification key
    assert "classification" not in by_name["ID"]
    assert "classification" not in by_name["NAME"]

    # Profile.extra carries the tight column-tag map the gate consumes.
    column_tags = profile.extra["column_tags"]
    assert column_tags["EMAIL"] == "pii"
    assert column_tags["SSN"] == "regulated"
    assert "ID" not in column_tags
    assert "NAME" not in column_tags

    # Resource-level rollup = highest column classification.
    # SSN is regulated which outranks pii.
    assert profile.extra["resource_classification"] == "regulated"
    assert profile.extra["governance_passthrough"] is True


@pytest.mark.asyncio
async def test_profile_with_no_tags_falls_back_to_internal(
    snowflake_mock: Any,
) -> None:
    """When TAG_REFERENCES returns nothing, the resource stays ``internal``."""
    _, _, fake_cur = snowflake_mock

    def _fetchall_no_tags() -> list[tuple[Any, ...]]:
        # The fixture's fetchall is an exec-history-aware function; replace
        # it with a stub that always returns empty for TAG_REFERENCES so we
        # can verify the no-tags branch.
        sql = (fake_cur.execute.call_args.args[0]
               if fake_cur.execute.call_args else "").upper()
        if "DESCRIBE TABLE" in sql:
            return [("ID", "NUMBER", "N", None)]
        return []

    fake_cur.fetchall = MagicMock(side_effect=_fetchall_no_tags)
    fake_cur.fetchone = MagicMock(return_value=(0,))

    connector = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _SNOW_KWARGS},
    )
    profile = await connector.profile(handle, "PUBLIC.PLAIN")
    assert profile.extra["column_tags"] == {}
    assert profile.extra["resource_classification"] == "internal"


# ---------------------------------------------------------------------------
# 3. MaskedColumnRefusalGate refuses queries touching tagged columns
#    AND writes a gate_fired entry with policy + tag chain to the ledger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_masked_column_query_refused_and_logged(
    snowflake_mock: Any,
) -> None:
    """Demo property: query touching a PII-tagged column refuses + traces."""
    connector = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _SNOW_KWARGS},
    )
    # 1. Profile: pulls column tags from Snowflake.
    profile = await connector.profile(handle, "PUBLIC.CUSTOMERS")

    # 2. Build the gate against an in-memory ledger.
    ledger = InMemoryLedger()
    gate = MaskedColumnRefusalGate(ledger, _TEST_COMPANY_ID)

    source_id = uuid4()
    query = MaskedColumnQuery(
        query_text=(
            'SELECT id, email, name FROM PUBLIC.CUSTOMERS LIMIT 10'
        ),
        referenced_columns=["ID", "EMAIL", "NAME"],
        column_tags=profile.extra["column_tags"],
        source_id=source_id,
        resource_id="PUBLIC.CUSTOMERS",
        requester="alice@acme.com",
    )
    decision = await gate.check(query)

    # 3. Decision: refused, with the offending column + tag chain.
    assert decision.allow is False
    assert decision.gate == GATE_NAME
    assert decision.policy_name == POLICY_NAME
    assert decision.offending_columns == ["EMAIL"]
    assert decision.tag_chain == [
        {"column": "EMAIL", "classification": "pii"}
    ]

    # 4. Ledger entry: one gate_fired with the policy name + tag chain
    #    + the trace path back to the source.
    rows = await ledger.fetch(_TEST_COMPANY_ID)
    gate_fires = [
        r for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_gate_fired"
    ]
    assert len(gate_fires) == 1
    args = gate_fires[0]["payload"]["args"]
    assert args["gate"] == GATE_NAME
    assert args["outcome"] == "blocked"
    assert args["policy_name"] == POLICY_NAME
    assert args["offending_columns"] == ["EMAIL"]
    assert args["tag_chain"] == [
        {"column": "EMAIL", "classification": "pii"}
    ]
    # Trace path: subject_ref + source_id let /trace deeplink into
    # /sources/<id> and surface the column-tag that drove refusal.
    assert args["subject_ref"] == "PUBLIC.CUSTOMERS"
    assert args["source_id"] == str(source_id)
    assert args["resource_id"] == "PUBLIC.CUSTOMERS"
    assert args["requester"] == "alice@acme.com"
    assert "SELECT" in args["query_text"]


@pytest.mark.asyncio
async def test_masked_column_query_with_clean_columns_allowed(
    snowflake_mock: Any,
) -> None:
    """Queries that don't touch tagged columns pass through cleanly."""
    connector = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _SNOW_KWARGS},
    )
    profile = await connector.profile(handle, "PUBLIC.CUSTOMERS")

    ledger = InMemoryLedger()
    gate = MaskedColumnRefusalGate(ledger, _TEST_COMPANY_ID)

    query = MaskedColumnQuery(
        query_text='SELECT id, name FROM PUBLIC.CUSTOMERS LIMIT 10',
        referenced_columns=["ID", "NAME"],
        column_tags=profile.extra["column_tags"],
        source_id=uuid4(),
        resource_id="PUBLIC.CUSTOMERS",
    )
    decision = await gate.check(query)

    assert decision.allow is True
    assert decision.offending_columns == []
    assert decision.tag_chain == []

    # No ledger entry on allow: we don't bloat the ledger with allow-paths.
    rows = await ledger.fetch(_TEST_COMPANY_ID)
    assert not any(
        r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_gate_fired"
        for r in rows
    )


@pytest.mark.asyncio
async def test_regulated_tag_also_refused(snowflake_mock: Any) -> None:
    """Regulated columns (e.g. SSN) refuse independent of pii."""
    connector = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _SNOW_KWARGS},
    )
    profile = await connector.profile(handle, "PUBLIC.CUSTOMERS")

    ledger = InMemoryLedger()
    gate = MaskedColumnRefusalGate(ledger, _TEST_COMPANY_ID)

    query = MaskedColumnQuery(
        query_text='SELECT ssn FROM PUBLIC.CUSTOMERS WHERE id = 1',
        referenced_columns=["SSN"],
        column_tags=profile.extra["column_tags"],
        source_id=uuid4(),
        resource_id="PUBLIC.CUSTOMERS",
    )
    decision = await gate.check(query)

    assert decision.allow is False
    assert decision.offending_columns == ["SSN"]
    assert decision.tag_chain == [
        {"column": "SSN", "classification": "regulated"}
    ]


# ---------------------------------------------------------------------------
# 4. End-to-end column-tag chain — Snowflake -> Profile -> Gate -> /trace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_to_end_tag_chain_visible_via_ledger(
    snowflake_mock: Any,
) -> None:
    """Replay the full P7 demo path through a single ledger.

    Asserts the property the demo bullet promises: a refused query in
    /trace can jump to /sources/<id> via the gate_fired payload's
    ``source_id`` + ``resource_id`` + ``tag_chain`` triple.
    """
    connector = SnowflakeSurfaceDriver()
    handle = AuthHandle(
        connector_kind="snowflake",
        handle_id="x",
        extra={"connect_kwargs": _SNOW_KWARGS},
    )
    profile = await connector.profile(handle, "PUBLIC.CUSTOMERS")

    # The shape downstream consumers (resource projection, gate) read.
    assert profile.extra["governance_passthrough"] is True
    assert profile.extra["column_tags"] == {
        "EMAIL": "pii",
        "SSN": "regulated",
    }
    # Resource-level classification == max of column classifications.
    assert profile.extra["resource_classification"] == "regulated"

    # Run the gate over a query that touches BOTH tagged columns.
    ledger = InMemoryLedger()
    gate = MaskedColumnRefusalGate(ledger, _TEST_COMPANY_ID)
    source_id = uuid4()
    decision = await gate.check(
        MaskedColumnQuery(
            query_text=(
                'SELECT email, ssn FROM PUBLIC.CUSTOMERS LIMIT 1'
            ),
            referenced_columns=["EMAIL", "SSN"],
            column_tags=profile.extra["column_tags"],
            source_id=source_id,
            resource_id="PUBLIC.CUSTOMERS",
            requester="bob@acme.com",
        )
    )
    assert decision.allow is False
    assert set(decision.offending_columns) == {"EMAIL", "SSN"}

    # The ledger row alone carries everything /trace needs to deeplink:
    #   policy name, gate name, source_id, resource_id, full tag chain.
    rows = await ledger.fetch(_TEST_COMPANY_ID)
    args = next(
        r["payload"]["args"]
        for r in rows
        if r["kind"] == "execute"
        and r["payload"].get("tool") == "emit_gate_fired"
    )
    assert args["policy_name"] == POLICY_NAME
    assert args["source_id"] == str(source_id)
    assert args["resource_id"] == "PUBLIC.CUSTOMERS"
    chain_cols = {entry["column"] for entry in args["tag_chain"]}
    assert chain_cols == {"EMAIL", "SSN"}
    chain_classes = {entry["classification"] for entry in args["tag_chain"]}
    assert chain_classes == {"pii", "regulated"}
