"""MCP tool name aliases for the continuous-lake rename (Wave D4).

> 2026-05-17 — Wave D of the continuous-lake philosophy work renames
> the Connector vocabulary to SurfaceDriver / lake-surface across the
> codebase. The MCP server's tool names (e.g. ``lake.catalog.tables``,
> ``lake.query``, ``decisions.list``) already use the lake-side
> vocabulary. The alias table below is therefore empty today — there
> are no ``*connector*`` tool names to alias.
>
> The alias-mapping infrastructure is wired up nonetheless so future
> tool renames (e.g. should we rename a ``lake.*`` tool to ``surfaces.*``
> when the surface namespace becomes user-facing) can register an alias
> without a behavioral change.
>
> Removal timeline: aliases get dropped at the v1.0 cutover (~6 weeks
> from 2026-05-17). See ``docs/setup/migration-from-pre-rename.md`` for
> the full migration table presented to external MCP clients.

Usage:

* :data:`TOOL_NAME_ALIASES` is a ``dict[old_name, new_name]`` mapping.
* :func:`resolve_tool_name` returns the canonical (new) tool name when
  the alias is the input, else returns the input unchanged.
* The MCP server registration code wires both names to the same handler
  by iterating ``TOOL_NAME_ALIASES`` and calling
  ``mcp.tool(name=old_name)`` against the same decorated function used
  for the canonical name. This is integrated in
  ``wormbase_agent_gateway.mcp_server.server.register_aliases`` (added
  in Wave D4); the no-op alias table makes the call a defensive no-op
  today.
"""
from __future__ import annotations

from typing import Mapping

# Old MCP tool name → new (canonical) MCP tool name.
#
# Empty today (no ``*connector*`` MCP tool names existed at the rename
# cut-over). Add entries here when a tool is renamed and the old name
# must remain callable for one release.
TOOL_NAME_ALIASES: Mapping[str, str] = {}


def resolve_tool_name(name: str) -> str:
    """Return the canonical tool name for ``name``.

    If ``name`` is a registered alias, returns the canonical (new) tool
    name. Otherwise returns ``name`` unchanged. The MCP server uses this
    for incoming tool calls so that both the alias and the canonical
    name route to the same handler.

    Examples:
        >>> resolve_tool_name("decisions.list")
        'decisions.list'
        >>> # When an alias exists for `lake.connectors.list` → `lake.surfaces.list`:
        >>> # resolve_tool_name("lake.connectors.list")  # → 'lake.surfaces.list'
    """
    return TOOL_NAME_ALIASES.get(name, name)


__all__ = ["TOOL_NAME_ALIASES", "resolve_tool_name"]
