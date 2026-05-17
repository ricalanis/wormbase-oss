"""wormbase-tools — OSS audit toolkit.

The package an auditor pip-installs to replay a frozen WormBase ledger
snapshot and reproduce a KPI value bit-for-bit, without the hosted plane.

Public surface
--------------
* :func:`wormbase_tools.replay.replay_snapshot` — load a JSONL ledger
  snapshot, verify the hash chain, fold deterministic projections, and
  return the requested KPI value.
* :class:`wormbase_tools.replay.ReplayResult` — structured return shape
  carrying the value, terminal hash, and provenance trail.
* :func:`wormbase_tools.wire_replay.iter_wire_events` — the canonical
  wire-replay primitive used by P14 (Wave B) for two-tenant determinism
  demos. Pure-Python iterator over a wire-event JSONL.
* :mod:`wormbase_tools.projections` — pure-Python re-implementations of
  the projection folds used by replay; see the module docstring for the
  vendoring seam.

The CLI entrypoint is exposed as ``wormbase-tools`` via the project's
console_scripts.
"""

from wormbase_tools.replay import (
    ReplayError,
    ReplayResult,
    replay_snapshot,
)
from wormbase_tools.wire_replay import (
    CHANNEL_ADAPTER_TOOLS,
    MCP_TOOLS,
    WIRE_TOOLS,
    WireReplayError,
    iter_wire_events,
    load_wire_events,
    replay_mcp_tool_calls,
)

__all__ = [
    "CHANNEL_ADAPTER_TOOLS",
    "MCP_TOOLS",
    "ReplayError",
    "ReplayResult",
    "WIRE_TOOLS",
    "WireReplayError",
    "iter_wire_events",
    "load_wire_events",
    "replay_mcp_tool_calls",
    "replay_snapshot",
]

__version__ = "0.1.0"
