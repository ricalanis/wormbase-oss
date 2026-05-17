"""Record MCP tool calls into a wire-event JSONL (Wave 3.1 polish).

The sim-harness ``WireRecorder``
(``apps/sim-harness/src/wormbase_sim_harness/wire_record.py``) captures
``channel_adapter.emit_*`` ledger rows; the agent-gateway is upstream
of the ledger for MCP-driven flows, so it owns its own per-call recorder
that emits ``mcp.tool_call`` entries directly.

Co-location rationale
---------------------

The recorder lives in the gateway package, not in wormbase-tools, because:

1. It is wired at the FastMCP-server construction site, so it shares the
   same dependency surface (FastMCP, GatewayDeps) as the server itself.
2. wormbase-tools is the OSS audit toolkit and stays infra-agnostic —
   it knows the *schema* (``mcp.tool_call``) but not the *server*.
3. Mirrors how the channel-adapter ships its ``WireReplayer`` alongside
   the channel-adapter service itself (apps/channel-adapter).

The output JSONL conforms to the canonical
:func:`wormbase_tools.wire_replay.iter_wire_events` schema, so any
recorded tape can be replayed via
:func:`wormbase_tools.wire_replay.replay_mcp_tool_calls`.

Determinism caveats
-------------------

``audit_trail_id`` and ``result_summary.row_count`` (and any field that
embeds server-side state) are post-execute observations — they are
populated when the wrapped tool returns. Replay reproduces *equivalent*
ledger entries, not byte-identical ones: a fresh ``audit_trail_id`` is
allocated per replay call. The byte-replay backstop is to fold the
resulting ledger through :func:`wormbase_tools.replay.replay_snapshot`
and diff the terminal hash. This matches how
``apps/channel-adapter/src/wormbase_channel_adapter/wire_replay.py``
handles its own non-determinism.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


log = logging.getLogger("wormbase_agent_gateway.mcp_wire_record")


MCP_TOOL_CALL_KIND = "mcp.tool_call"


class McpToolCallRecorder:
    """Append ``mcp.tool_call`` wire events into a JSONL file.

    Thread-safe append; the recorder is a single sink that multiple
    coroutines may write to concurrently. Each :meth:`record` call
    writes one line and flushes; durability is per-line, not per-batch.

    Parameters
    ----------
    out_path:
        Destination JSONL. Parent directories are created on init.
    seq_start:
        Initial seq value; default 1. Each successful record bumps the
        seq. Callers that want to interleave with a channel-adapter
        recorder can pass a shared :class:`itertools.count`-style
        generator via ``seq_provider`` instead.
    seq_provider:
        Optional ``Callable[[], int]`` returning the next seq. When
        supplied it overrides ``seq_start`` — useful for a shared
        cross-recorder seq pool. The callable is invoked under the
        recorder's lock.
    """

    def __init__(
        self,
        out_path: Path,
        *,
        seq_start: int = 1,
        seq_provider: Any | None = None,
    ) -> None:
        self._out_path = Path(out_path)
        self._out_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._out_path.exists():
            self._out_path.touch()
        self._next_seq = int(seq_start)
        self._seq_provider = seq_provider
        self._lock = threading.Lock()
        self._records_written = 0

    @property
    def out_path(self) -> Path:
        return self._out_path

    @property
    def records_written(self) -> int:
        return self._records_written

    def record(
        self,
        *,
        tool: str,
        params: dict[str, Any],
        agent_id: str,
        audit_trail_id: str | None = None,
        result_summary: dict[str, Any] | None = None,
        ts: datetime | None = None,
    ) -> int:
        """Write one ``mcp.tool_call`` line. Returns the assigned seq.

        Parameters
        ----------
        tool:
            MCP tool name, e.g. ``"lake.semantic.metric"``.
        params:
            The tool's kwargs as sent over the wire.
        agent_id:
            The calling agent's identifier.
        audit_trail_id:
            The audit_trail_id allocated by the gateway, if known at
            record time. May be ``None`` for failures that never
            allocated one.
        result_summary:
            Optional post-execute summary (row count, status, gate
            outcome, etc.). The summary is opaque to replay; tooling
            uses it for assertion harnesses.
        ts:
            Optional override; defaults to UTC now.
        """
        ts = ts or datetime.now(UTC)
        with self._lock:
            if self._seq_provider is not None:
                seq = int(self._seq_provider())
            else:
                seq = self._next_seq
                self._next_seq = seq + 1
            args: dict[str, Any] = {
                "tool": tool,
                "params": params,
                "agent_id": agent_id,
                "audit_trail_id": audit_trail_id,
                "result_summary": result_summary,
            }
            rec = {
                "seq": seq,
                "ts": ts.isoformat(),
                "tool": MCP_TOOL_CALL_KIND,
                "args": args,
            }
            with self._out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
            self._records_written += 1
        return seq


__all__ = ["McpToolCallRecorder", "MCP_TOOL_CALL_KIND"]
