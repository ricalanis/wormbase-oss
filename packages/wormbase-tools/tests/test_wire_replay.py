"""Tests for the wire-event JSONL primitive (P14 dependency)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wormbase_tools.wire_replay import (
    CHANNEL_ADAPTER_TOOLS,
    MCP_TOOLS,
    WIRE_TOOLS,
    WireReplayError,
    iter_wire_events,
    load_wire_events,
)


def _write(path: Path, recs: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


def test_iter_wire_events_yields_known_tools(tmp_path: Path) -> None:
    p = tmp_path / "wire.jsonl"
    _write(
        p,
        [
            {
                "seq": 1,
                "ts": "2026-04-28T12:00:00Z",
                "tool": "channel_adapter.emit_chat_received",
                "args": {"channel_id": "C1", "text": "hi"},
            },
            {
                "seq": 2,
                "ts": "2026-04-28T12:00:01Z",
                "tool": "channel_adapter.emit_file_received",
                "args": {"slack_file_id": "F1"},
            },
        ],
    )
    events = list(iter_wire_events(p))
    assert len(events) == 2
    assert {e["tool"] for e in events} <= set(WIRE_TOOLS)


def test_iter_wire_events_strict_rejects_unknown_tool(tmp_path: Path) -> None:
    p = tmp_path / "wire.jsonl"
    _write(
        p,
        [
            {
                "seq": 1,
                "ts": "2026-04-28T12:00:00Z",
                "tool": "channel_adapter.emit_chat_received",
                "args": {},
            },
            {
                "seq": 2,
                "ts": "2026-04-28T12:00:01Z",
                "tool": "ledger.emit_propose",  # not a wire tool
                "args": {},
            },
        ],
    )
    with pytest.raises(WireReplayError):
        list(iter_wire_events(p, strict=True))


def test_iter_wire_events_lenient_skips_unknown_tool(tmp_path: Path) -> None:
    p = tmp_path / "wire.jsonl"
    _write(
        p,
        [
            {
                "seq": 1,
                "ts": "2026-04-28T12:00:00Z",
                "tool": "channel_adapter.emit_chat_received",
                "args": {},
            },
            {
                "seq": 2,
                "ts": "2026-04-28T12:00:01Z",
                "tool": "ledger.emit_propose",
                "args": {},
            },
        ],
    )
    events = list(iter_wire_events(p, strict=False))
    assert len(events) == 1


def test_iter_wire_events_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "wire.jsonl"
    p.write_text(
        "\n"
        '{"seq":1,"ts":"2026-04-28T12:00:00Z","tool":"channel_adapter.emit_chat_received","args":{}}\n'
        "\n",
        encoding="utf-8",
    )
    events = list(iter_wire_events(p))
    assert len(events) == 1


def test_iter_wire_events_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(WireReplayError):
        list(iter_wire_events(tmp_path / "nope.jsonl"))


def test_mcp_tool_call_event_parses(tmp_path: Path) -> None:
    """Wave 3.1: ``mcp.tool_call`` is a first-class wire transport."""
    p = tmp_path / "wire.jsonl"
    _write(
        p,
        [
            {
                "seq": 1,
                "ts": "2026-05-10T09:00:00Z",
                "tool": "mcp.tool_call",
                "args": {
                    "tool": "lake.semantic.metric",
                    "params": {"name": "revenue_q3"},
                    "agent_id": "claude_research",
                    "audit_trail_id": None,
                    "result_summary": None,
                },
            },
        ],
    )
    events = list(iter_wire_events(p, strict=True))
    assert len(events) == 1
    assert events[0]["tool"] == "mcp.tool_call"
    assert events[0]["args"]["tool"] == "lake.semantic.metric"


def test_mcp_tool_call_missing_inner_tool_is_rejected(tmp_path: Path) -> None:
    """The mcp.tool_call schema check needs a non-empty args.tool field."""
    p = tmp_path / "wire.jsonl"
    _write(
        p,
        [
            {
                "seq": 1,
                "ts": "2026-05-10T09:00:00Z",
                "tool": "mcp.tool_call",
                "args": {"params": {}, "agent_id": "x"},
            },
        ],
    )
    with pytest.raises(WireReplayError):
        list(iter_wire_events(p, strict=True))


def test_wire_tools_is_channel_adapter_plus_mcp_extension() -> None:
    """The exported constants compose correctly + preserve historic ordering."""
    # CHANNEL_ADAPTER_TOOLS retains the original three tools.
    assert set(CHANNEL_ADAPTER_TOOLS) == {
        "channel_adapter.emit_chat_received",
        "channel_adapter.emit_chat_sent",
        "channel_adapter.emit_file_received",
    }
    # MCP_TOOLS carries the Wave 3.1 transport.
    assert "mcp.tool_call" in MCP_TOOLS
    # WIRE_TOOLS is the union.
    assert set(WIRE_TOOLS) == set(CHANNEL_ADAPTER_TOOLS) | set(MCP_TOOLS)


def test_load_wire_events_sorts_by_seq(tmp_path: Path) -> None:
    p = tmp_path / "wire.jsonl"
    _write(
        p,
        [
            {
                "seq": 5,
                "ts": "2026-04-28T12:00:05Z",
                "tool": "channel_adapter.emit_chat_received",
                "args": {},
            },
            {
                "seq": 1,
                "ts": "2026-04-28T12:00:00Z",
                "tool": "channel_adapter.emit_chat_received",
                "args": {},
            },
            {
                "seq": 3,
                "ts": "2026-04-28T12:00:03Z",
                "tool": "channel_adapter.emit_chat_received",
                "args": {},
            },
        ],
    )
    events = load_wire_events(p)
    assert [int(e["seq"]) for e in events] == [1, 3, 5]
