"""ASML demo wire-replay — byte-replayability check (Wave 3.1 polish).

Validates that ``infra/asml-demo/wire_replay_tape.jsonl`` is a valid
canonical wire-event JSONL and that the ``mcp.tool_call`` events replay
deterministically through an in-process ``AgentGatewayMCPServer``.

What this test covers (vs ``test_asml_demo_arc.py``)
----------------------------------------------------

``test_asml_demo_arc.py`` reproduces the 6 beats programmatically: it
calls the MCP server directly with the canonical params from spec §7.
This test takes the *recorded tape* as input and dispatches every
``mcp.tool_call`` line through ``replay_mcp_tool_calls`` — a much
stronger contract:

1. Every line in the tape parses under the wire-event schema.
2. Every ``mcp.tool_call`` line round-trips through the gateway and
   produces an ``audit_trail_id`` + an ``agent_query`` PEVR cycle in
   the ledger.
3. The set of MCP tools recorded in the tape matches the set the
   live FastMCP server registers (no tape drift).
4. The recorder round-trips: a fresh tape recorded from this replay
   produces the same MCP tool-call sequence in the same order.

Channel-adapter events in the tape (``channel_adapter.emit_chat_received``
for admin commands) are *parsed* here but not replayed — they need a
running channel-adapter pipeline which is out of scope for this
hermetic test. The channel-adapter replay path is covered by
``apps/channel-adapter/tests/test_wire_replay*.py``.

Determinism caveats
-------------------

Replay produces *equivalent* ledger entries, not byte-identical ones:
each replay allocates a fresh ``audit_trail_id``, so two consecutive
replays land different IDs while landing the same row shapes and
counts. To recover byte-determinism the operator folds the resulting
ledger through ``wormbase_tools.replay.replay_snapshot`` and diffs
the terminal hash — the P14 backstop. This test asserts equivalence
(row counts, kinds, agent_id) rather than byte-identity.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Awaitable, Literal, Sequence
from uuid import UUID, uuid4

import pytest
from fastmcp import Client

from wormbase_inference import AgentID, GovernanceContext
from wormbase_ledger import InMemoryLedger
from wormbase_tools.wire_replay import (
    CHANNEL_ADAPTER_TOOLS,
    MCP_TOOLS,
    WIRE_TOOLS,
    WireReplayError,
    iter_wire_events,
    load_wire_events,
    replay_mcp_tool_calls,
)

from wormbase_agent_gateway.credential_broker import EnvCredentialBroker
from wormbase_agent_gateway.identity import AgentGrant
from wormbase_agent_gateway.mcp_server import (
    GatewayDeps,
    McpToolCallRecorder,
    build_agent_gateway_mcp_server,
)
from wormbase_agent_gateway.router_query import BrokerExecutor, FederateIssuer


# Async tests in this module opt-in to asyncio explicitly via
# ``@pytest.mark.asyncio``; the schema-validation tests are sync and
# would otherwise warn under a module-wide asyncio mark.


# ---------------------------------------------------------------------------
# Constants — canonical paths + ids (mirrors test_asml_demo_arc.py)
# ---------------------------------------------------------------------------


ASML_DEMO_DIR = Path(__file__).resolve().parents[2] / "infra" / "asml-demo"
ASML_TAPE = ASML_DEMO_DIR / "wire_replay_tape.jsonl"

ASML_COMPANY_ID = UUID("aa000000-0000-0000-0000-00000000a5ad")
ASML_INSTALL_ID = "install-asml-demo"
ASML_DOMAIN_FINANCE = "00000000-0000-0000-0000-0000000f1ce1"
ASML_ADMIN_PERSON = "00000000-0000-0000-0000-00000000ad11"
CLAUDE_RESEARCH_AGENT_ID = "claude_research"


# ---------------------------------------------------------------------------
# Minimal harness — only what's needed to drive Beat-4 / Beat-6 MCP calls
# ---------------------------------------------------------------------------


@dataclass
class _StubDriver:
    rows: list[dict[str, Any]] = field(default_factory=list)

    async def query(
        self, *, account: dict[str, Any], sql: str, params: list[Any],
    ) -> list[dict[str, Any]]:
        return list(self.rows)


@dataclass
class _StubCatalogClient:
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def get_metric(self, name: str) -> dict[str, Any] | None:
        return self.metrics.get(name)

    async def get_table(self, external_id: str) -> dict[str, Any] | None:
        return self.tables.get(external_id)

    async def list_tables(self) -> list[dict[str, Any]]:
        return list(self.tables.values())


@dataclass
class _StubCatalogReader:
    catalog_rows: list[dict[str, Any]] = field(default_factory=list)
    lineage_rows: list[dict[str, Any]] = field(default_factory=list)
    classifications: dict[str, str] = field(default_factory=dict)

    async def list_tables(
        self, *, company_id: UUID, filter: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        return list(self.catalog_rows)

    async def list_lineage(
        self, *, company_id: UUID, resource_id: str,
        direction: Literal["upstream", "downstream", "both"],
    ) -> list[dict[str, Any]]:
        if direction == "upstream":
            return [
                e for e in self.lineage_rows
                if e.get("downstream") == resource_id
            ]
        if direction == "downstream":
            return [
                e for e in self.lineage_rows
                if e.get("upstream") == resource_id
            ]
        return list(self.lineage_rows)

    async def get_resource_classification(self, resource_id: str) -> str | None:
        return self.classifications.get(resource_id)


# ---------------------------------------------------------------------------
# Schema-validation tests (no live server)
# ---------------------------------------------------------------------------


def test_tape_file_exists_and_has_lines() -> None:
    """The canonical tape must exist at the documented path."""
    assert ASML_TAPE.exists(), f"missing wire-replay tape: {ASML_TAPE}"
    raw = [ln for ln in ASML_TAPE.read_text("utf-8").splitlines() if ln.strip()]
    assert len(raw) >= 4, (
        f"tape must carry the hero arc (>=4 events); found {len(raw)}"
    )


def test_tape_parses_under_canonical_wire_event_schema() -> None:
    """Every line is a valid {seq, ts, tool, args} record."""
    events = list(iter_wire_events(ASML_TAPE, strict=True))
    # Tape carries at least the 4 mcp.tool_call beats + 3 channel-adapter
    # admin commands recorded in the canonical 6-beat arc.
    assert len(events) >= 7
    for rec in events:
        assert "seq" in rec
        assert "ts" in rec
        assert rec["tool"] in WIRE_TOOLS, (
            f"unknown tool in tape: {rec['tool']}"
        )
        assert isinstance(rec["args"], dict)


def test_tape_seq_is_monotonic() -> None:
    """Replay determinism requires monotonic seq."""
    events = load_wire_events(ASML_TAPE)
    seqs = [int(e["seq"]) for e in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs), "duplicate seq in tape"


def test_tape_mcp_tool_names_match_live_server() -> None:
    """Every recorded mcp.tool_call.tool must be a tool the live FastMCP server registers.

    Drift between the recorded tape and the registered tool surface
    would silently break replay. The canonical 9-tool registry lives
    on the server instance — we build one and intersect.
    """
    events = load_wire_events(ASML_TAPE)
    recorded_tools = {
        rec["args"]["tool"]
        for rec in events
        if rec["tool"] == "mcp.tool_call"
    }
    assert recorded_tools, "tape has no mcp.tool_call events"

    # Build a server instance just to read the tool registry.
    server = _build_server(_build_harness_state(tmp_secrets_dir=None))
    live_tools = set(server.tool_names)
    drift = recorded_tools - live_tools
    assert not drift, (
        f"tape references tools the live server doesn't expose: {drift}\n"
        f"live tools: {sorted(live_tools)}\n"
        f"tape tools: {sorted(recorded_tools)}"
    )


def test_iter_wire_events_rejects_corrupt_mcp_tool_call(tmp_path: Path) -> None:
    """The schema check catches mcp.tool_call entries with no inner tool."""
    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        json.dumps({
            "seq": 1, "ts": "2026-05-10T09:00:00Z",
            "tool": "mcp.tool_call",
            "args": {"params": {}},  # missing inner "tool"
        }) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(WireReplayError):
        list(iter_wire_events(bad, strict=True))


# ---------------------------------------------------------------------------
# Constants exposure — extending WIRE_TOOLS must not drop the existing set
# ---------------------------------------------------------------------------


def test_channel_adapter_tools_preserved_after_mcp_extension() -> None:
    """Wave 3.1 must extend WIRE_TOOLS additively — no removal."""
    expected_channel = {
        "channel_adapter.emit_chat_received",
        "channel_adapter.emit_chat_sent",
        "channel_adapter.emit_file_received",
    }
    assert set(CHANNEL_ADAPTER_TOOLS) == expected_channel
    assert "mcp.tool_call" in MCP_TOOLS
    assert expected_channel.issubset(set(WIRE_TOOLS))
    assert "mcp.tool_call" in WIRE_TOOLS


# ---------------------------------------------------------------------------
# Live-replay test — drive the in-process gateway from the tape
# ---------------------------------------------------------------------------


@dataclass
class _HarnessState:
    ledger: InMemoryLedger
    broker: EnvCredentialBroker
    catalog_client: _StubCatalogClient
    catalog_reader: _StubCatalogReader
    driver: _StubDriver
    grants: list[AgentGrant]


def _build_harness_state(*, tmp_secrets_dir: Path | None) -> _HarnessState:
    """Wire the minimal stub stack needed for the MCP server to answer
    the Beat 4 / Beat 6 calls. Mirrors the asml_harness fixture in
    test_asml_demo_arc.py but stays inline so this test can run
    standalone if someone moves the fixture.
    """
    ledger = InMemoryLedger()
    secrets = tmp_secrets_dir or Path("/tmp/wormbase_asml_replay_secrets")
    broker = EnvCredentialBroker(secrets_dir=secrets)

    # Seed the Snowflake account file used by BrokerExecutor.
    secret_dir = secrets / "data" / "snowflake" / ASML_INSTALL_ID
    secret_dir.parent.mkdir(parents=True, exist_ok=True)
    secret_dir.write_text(json.dumps({
        "account": "asml_demo.snowflakecomputing.com",
        "user": "WORM_SERVICE",
        "warehouse": "ANALYTICS_WH",
        "database": "ASML_DEMO",
        "schema": "ANALYTICS",
    }))

    catalog_client = _StubCatalogClient()
    catalog_client.metrics["revenue_q3"] = {
        "name": "revenue_q3",
        "source_table_id": "tbl-rev-by-region-001",
        "source_kind": "snowflake",
        "expression": "SUM(amount_usd)",
    }
    catalog_client.tables["tbl-rev-by-region-001"] = {
        "name": "ASML_DEMO.ANALYTICS.REVENUE_BY_REGION",
        "external_id": "tbl-rev-by-region-001",
        "upstream_kind": "snowflake",
        "columns": [{"name": "region"}, {"name": "revenue_usd"}],
    }
    catalog_reader = _StubCatalogReader(
        lineage_rows=[
            {
                "upstream": "seed.jaffle_shop.raw_orders",
                "downstream": "tbl-rev-by-region-001",
                "source_id": "src-jaffle-shop-001",
            },
        ],
        classifications={"tbl-rev-by-region-001": "internal"},
    )

    driver = _StubDriver(rows=[
        {"region": "EMEA", "fiscal_q": "Q3_2026", "revenue_usd": 83500.00},
    ])

    # Seed grants pre-Beat-4 (admin already registered the agent + 2 grants).
    now = datetime.now(UTC)
    grants = [
        AgentGrant(
            id=str(uuid4()),
            agent_id=CLAUDE_RESEARCH_AGENT_ID,
            grant_kind="domain.read",
            grant_target=ASML_DOMAIN_FINANCE,
            status="active",
            granted_by=ASML_ADMIN_PERSON,
            granted_at=now,
        ),
        AgentGrant(
            id=str(uuid4()),
            agent_id=CLAUDE_RESEARCH_AGENT_ID,
            grant_kind="model.access",
            grant_target="claude",
            status="active",
            granted_by=ASML_ADMIN_PERSON,
            granted_at=now,
            budget_remaining_usd=Decimal("5.00"),
        ),
    ]

    return _HarnessState(
        ledger=ledger,
        broker=broker,
        catalog_client=catalog_client,
        catalog_reader=catalog_reader,
        driver=driver,
        grants=grants,
    )


def _build_server(harness: _HarnessState, recorder: McpToolCallRecorder | None = None):
    """Construct the agent-gateway server with optional recorder wired."""
    executor = BrokerExecutor(
        broker=harness.broker, install_id=ASML_INSTALL_ID, driver=harness.driver,
    )
    federate = FederateIssuer(broker=harness.broker)
    agent_id = AgentID(value=CLAUDE_RESEARCH_AGENT_ID)

    async def _grant_lookup(aid: AgentID) -> Sequence[AgentGrant]:
        return [g for g in harness.grants if g.agent_id == aid.value]

    async def _agent_resolver() -> AgentID:
        return agent_id

    async def _governance_resolver(_a: AgentID) -> GovernanceContext:
        return GovernanceContext(
            classification_ceiling="internal",
            cost_budget_usd=Decimal("5.00"),
            pii_redaction=True,
            domain_id=ASML_DOMAIN_FINANCE,
        )

    deps = GatewayDeps(
        ledger=harness.ledger,
        company_id=ASML_COMPANY_ID,
        install_id=ASML_INSTALL_ID,
        catalog_client=harness.catalog_client,
        catalog_reader=harness.catalog_reader,
        broker_executor=executor,
        federate_issuer=federate,
        grant_lookup=_grant_lookup,
        agent_id_resolver=_agent_resolver,
        governance_resolver=_governance_resolver,
        router=None,
        recorder=recorder,
    )
    return build_agent_gateway_mcp_server(deps)


@pytest.mark.asyncio
async def test_replay_mcp_events_against_live_gateway(tmp_path: Path) -> None:
    """Load the tape, replay every mcp.tool_call, assert ledger writes land.

    For Beat 4's 3 MCP calls, the gateway writes 1 ``agent_query`` PEVR
    cycle per call → 3 distinct audit_trail_ids. The Beat-6 denied call
    also lands a PEVR cycle (status=denied on execute), but only with a
    revoked grant — we keep the grants active here so all 4 mcp.tool_call
    events succeed.

    The byte-replay backstop (recover byte-identity via replay_snapshot
    hash) is documented in the module docstring and exercised by P14.
    """
    harness = _build_harness_state(tmp_secrets_dir=tmp_path / "secrets")
    server = _build_server(harness)

    events = load_wire_events(ASML_TAPE)
    mcp_events = [e for e in events if e["tool"] == "mcp.tool_call"]
    assert len(mcp_events) >= 3, "tape must contain the 3 hero MCP calls"

    async with Client(server.mcp) as client:
        results = await replay_mcp_tool_calls(events, client=client)

    # Every successful mcp.tool_call landed a row in results.
    # Beat 6's call (last mcp.tool_call) succeeds here because we keep
    # grants active — the denial test is owned by test_asml_demo_arc.py.
    assert len(results) == len(mcp_events)
    for entry in results:
        result = entry["result"]
        assert not result.is_error, (
            f"replay failed for seq={entry['seq']} tool={entry['tool']}"
        )

    # Each successful tool call wrote 4 PEVR phase rows for one
    # audit_trail_id. Count distinct atids.
    rows = await harness.ledger.fetch(ASML_COMPANY_ID)
    atids = {
        (r.get("payload") or {}).get("audit_trail_id")
        for r in rows
        if (r.get("payload") or {}).get("audit_trail_id")
        and (r.get("payload") or {}).get("phase") is not None
        and (r.get("payload") or {}).get("mcp_tool") is not None
    }
    assert len(atids) == len(mcp_events), (
        f"expected {len(mcp_events)} agent_query cycles, got {len(atids)}"
    )

    # Every PEVR phase row carries the claude_research agent_id.
    for r in rows:
        payload = r.get("payload") or {}
        if payload.get("phase") and payload.get("mcp_tool"):
            assert payload.get("agent_id") == CLAUDE_RESEARCH_AGENT_ID


@pytest.mark.asyncio
async def test_recorder_round_trips_tape_through_live_gateway(tmp_path: Path) -> None:
    """Recording a replay yields a tape with the same mcp.tool_call sequence.

    Wire-record-on-replay is the round-trip contract: if we record while
    replaying, the recorded tape's mcp.tool_call lines must match the
    original tape's in tool-name order. This is the "we did not silently
    drop a call" check.
    """
    harness = _build_harness_state(tmp_secrets_dir=tmp_path / "secrets")
    recorder = McpToolCallRecorder(out_path=tmp_path / "replayed.jsonl")
    server = _build_server(harness, recorder=recorder)

    events = load_wire_events(ASML_TAPE)
    original_tools = [
        e["args"]["tool"] for e in events if e["tool"] == "mcp.tool_call"
    ]

    async with Client(server.mcp) as client:
        await replay_mcp_tool_calls(events, client=client)

    # Parse the freshly-recorded tape and assert the inner-tool order
    # matches the original (modulo audit_trail_id which is replay-fresh).
    replayed_events = load_wire_events(recorder.out_path)
    replayed_tools = [
        e["args"]["tool"] for e in replayed_events
        if e["tool"] == "mcp.tool_call"
    ]
    assert replayed_tools == original_tools, (
        f"replayed sequence diverges from original\n"
        f"original: {original_tools}\nreplayed: {replayed_tools}"
    )

    # Every replayed record carries a fresh audit_trail_id (post-execute).
    for e in replayed_events:
        if e["tool"] != "mcp.tool_call":
            continue
        args = e["args"]
        assert args["agent_id"] == CLAUDE_RESEARCH_AGENT_ID
        # audit_trail_id allocated by the gateway — must be a UUID-ish str.
        atid = args["audit_trail_id"]
        assert isinstance(atid, str) and len(atid) > 0


@pytest.mark.asyncio
async def test_recorder_records_call_when_recorder_is_none() -> None:
    """When deps.recorder is None the server runs unchanged.

    Backwards-compat: existing callers (live worm-core boot) do not pass
    a recorder; the wrapper must not raise on the None path.
    """
    harness = _build_harness_state(tmp_secrets_dir=Path("/tmp/asml-noop-recorder"))
    server = _build_server(harness, recorder=None)

    async with Client(server.mcp) as client:
        r = await client.call_tool(
            "lake.semantic.metric",
            {"name": "revenue_q3", "filter": {"region": "EMEA"}},
        )
    assert not r.is_error
