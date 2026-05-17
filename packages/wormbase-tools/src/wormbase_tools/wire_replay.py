"""Wire-event JSONL replay primitive (export for P14 Wave B + Wave 3.1).

The hosted plane already has a wire-replay integrated with the
channel-adapter (``apps/channel-adapter/src/wormbase_channel_adapter/wire_replay.py``).
That implementation needs the channel-adapter's ledger-write machinery
and is therefore unsuitable for a clean-venv auditor install.

What this module exports
========================

A pure-Python iterator over a wire-event JSONL file (the format the
sim-harness ``WireRecorder`` produces) with a strict schema check.
P14's two-tenant determinism stage demo uses it to:

1. Read the canonical ``install_arc.jsonl`` once.
2. Stream the same parsed records into two tenant adapters.
3. Diff the resulting terminal ledger hashes (via
   :func:`wormbase_tools.replay.replay_snapshot` on each tenant's
   exported snapshot).

This module deliberately knows nothing about ledgers, adapters, or
SQL. It owns one job — parse a wire-event JSONL deterministically.
The byte-for-byte wire-replay-into-ledger remains the channel-adapter's
production concern.

Wave 3.1 polish
---------------

The schema is extended with the ``mcp.tool_call`` transport so the
ASML demo's `wire_replay_tape.jsonl` becomes byte-replayable end-to-end
(channel-adapter wire events + MCP agent-gateway tool calls).

Wire-event format (``WireRecorder`` + agent-gateway MCP recorder)
=================================================================

::

    {
      "seq": <int>,         # writer's seq, monotonic
      "ts": "<ISO 8601>",
      "tool": "channel_adapter.emit_chat_received"
              | "channel_adapter.emit_chat_sent"
              | "channel_adapter.emit_file_received"
              | "mcp.tool_call",
      "args": { ... }       # tool-specific payload
    }

The ``mcp.tool_call`` ``args`` shape is:

::

    {
      "tool": "lake.semantic.metric" | ... ,        # MCP tool name
      "params": { ... },                            # the call's kwargs
      "agent_id": "claude_research",                # calling agent
      "audit_trail_id": "<uuid>" | null,            # post-execute, if known
      "result_summary": {"row_count": 1, ...} | null
    }

Channel-adapter wire-replay (``WireReplayer``) ignores any record
whose tool is not in its own allow-list; MCP replay (see
:func:`replay_mcp_tool_calls`) ignores any record whose tool is not
``mcp.tool_call``. The two are designed to coexist in one tape.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any


log = logging.getLogger("wormbase_tools.wire_replay")


CHANNEL_ADAPTER_TOOLS: tuple[str, ...] = (
    "channel_adapter.emit_chat_received",
    "channel_adapter.emit_chat_sent",
    "channel_adapter.emit_file_received",
)
"""Wire tools owned by the channel-adapter (apps/channel-adapter)."""


MCP_TOOLS: tuple[str, ...] = ("mcp.tool_call",)
"""Wire tools owned by the agent-gateway MCP server (Wave 3.1)."""


WIRE_TOOLS: tuple[str, ...] = CHANNEL_ADAPTER_TOOLS + MCP_TOOLS
"""Union of all known wire-event tools.

Channel-adapter tools come first to preserve the historical ordering
that the existing tests (``test_wire_replay.py``) assert against.
"""


class WireReplayError(Exception):
    """Raised on a malformed or missing wire-event JSONL file."""


def iter_wire_events(
    path: Path | str,
    *,
    strict: bool = True,
) -> Iterator[dict[str, Any]]:
    """Yield ``{seq, ts, tool, args}`` records from a wire-event JSONL.

    Parameters
    ----------
    path:
        Path to the JSONL file produced by the sim-harness's
        ``WireRecorder``, the agent-gateway's
        :class:`McpToolCallRecorder`, or any equivalent recorder.
    strict:
        If True (default), unknown tools or malformed records raise
        :class:`WireReplayError`. If False, malformed records are
        skipped with a warning — useful when a slack-flake produced
        a couple of bad lines but the bulk of the recording is good.

    Determinism: yields in file order. Callers that need
    seq-monotonicity should sort the result.
    """
    p = Path(path)
    if not p.exists():
        raise WireReplayError(f"wire-event JSONL does not exist: {p}")

    with p.open("r", encoding="utf-8") as f:
        for idx, raw in enumerate(f):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                msg = f"wire-replay: line {idx + 1} is not valid JSON: {exc}"
                if strict:
                    raise WireReplayError(msg) from exc
                log.warning(msg)
                continue
            if not isinstance(rec, dict):
                msg = f"wire-replay: line {idx + 1} is not a JSON object"
                if strict:
                    raise WireReplayError(msg)
                log.warning(msg)
                continue
            tool = rec.get("tool")
            if tool not in WIRE_TOOLS:
                msg = (
                    f"wire-replay: line {idx + 1} has unknown tool {tool!r}; "
                    f"expected one of {WIRE_TOOLS}"
                )
                if strict:
                    raise WireReplayError(msg)
                log.warning(msg)
                continue
            args = rec.get("args")
            if not isinstance(args, dict):
                msg = (
                    f"wire-replay: line {idx + 1} has non-dict args "
                    f"({type(args).__name__})"
                )
                if strict:
                    raise WireReplayError(msg)
                log.warning(msg)
                continue
            # mcp.tool_call carries one extra schema check: args.tool
            # must be a non-empty string, since the MCP replay dispatcher
            # routes on that field. Param shape is opaque (tool-defined).
            if tool == "mcp.tool_call":
                inner_tool = args.get("tool")
                if not isinstance(inner_tool, str) or not inner_tool:
                    msg = (
                        f"wire-replay: line {idx + 1} mcp.tool_call missing "
                        f"a non-empty 'tool' field in args"
                    )
                    if strict:
                        raise WireReplayError(msg)
                    log.warning(msg)
                    continue
            yield rec


def load_wire_events(
    path: Path | str,
    *,
    strict: bool = True,
) -> list[dict[str, Any]]:
    """Eagerly load + sort wire events by ``seq``."""
    events = list(iter_wire_events(path, strict=strict))
    events.sort(key=lambda r: int(r.get("seq", 0)))
    return events


async def replay_mcp_tool_calls(
    events: list[dict[str, Any]],
    *,
    client: Any,
) -> list[dict[str, Any]]:
    """Replay ``mcp.tool_call`` events through a FastMCP ``Client``.

    Filters ``events`` to the ``mcp.tool_call`` subset, then invokes
    each tool against the provided ``client`` (an open ``fastmcp.Client``
    bound to an :class:`AgentGatewayMCPServer.mcp` instance, or any
    equivalent transport).

    Returns the list of ``CallToolResult`` objects FastMCP produced, in
    seq order. The caller does the assertion work — this helper stays
    transport-thin and observation-only.

    Channel-adapter wire events are skipped silently here; route them
    through the channel-adapter's own ``WireReplayer`` if you need
    end-to-end replay of a mixed tape.

    Parameters
    ----------
    events:
        Output of :func:`load_wire_events` (or any iterable of records
        with the canonical ``{seq, ts, tool, args}`` shape).
    client:
        An open FastMCP ``Client`` (or compatible async client). The
        helper calls ``await client.call_tool(name, params)`` for every
        ``mcp.tool_call`` event.

    Notes
    -----
    Byte-determinism caveats: FastMCP responses embed server-side
    timestamps and freshly-allocated audit_trail_ids on every replay,
    so two consecutive replays produce *equivalent* (same shape,
    same row_count, same metric_name) results, not *byte-identical*
    ones. To recover full byte-determinism, downstream tests must
    canonicalize via :func:`wormbase_tools.replay.replay_snapshot` on
    the resulting ledger and diff terminal hashes — the same approach
    P14 takes for channel-adapter replay.
    """
    results: list[dict[str, Any]] = []
    for rec in events:
        if rec.get("tool") != "mcp.tool_call":
            continue
        args = rec.get("args") or {}
        inner_tool = args.get("tool")
        params = args.get("params") or {}
        if not isinstance(inner_tool, str) or not isinstance(params, dict):
            log.warning(
                "wire-replay: skipping malformed mcp.tool_call at seq=%s",
                rec.get("seq"),
            )
            continue
        try:
            result = await client.call_tool(inner_tool, params)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "wire-replay: mcp.tool_call failed seq=%s tool=%s: %s",
                rec.get("seq"), inner_tool, exc,
            )
            continue
        results.append({"seq": rec.get("seq"), "tool": inner_tool, "result": result})
    return results


__all__ = [
    "CHANNEL_ADAPTER_TOOLS",
    "MCP_TOOLS",
    "WIRE_TOOLS",
    "WireReplayError",
    "iter_wire_events",
    "load_wire_events",
    "replay_mcp_tool_calls",
]
