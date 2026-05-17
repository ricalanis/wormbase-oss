"""MCP tool surface — extension modules for the Phase 0 server.

J1+J2+J3 of docs/superpowers/plans/2026-04-26-production-dashboard.md
extend the Phase 0 stateless FastMCP server (``mcp_server.py``) with a
full read/write/resource/prompt catalog. Each register_* function is a
thin glue layer over the ledger fold helpers and the canonical
``write_actions`` PEVR primitives.

The Phase 0 ``query_ledger`` tool is preserved as-is. These modules
register additional tools, resources, and prompts on the same FastMCP
instance built by ``build_mcp_server``.
"""

from wormbase_core.mcp_tools.audit import register_audit_tools
from wormbase_core.mcp_tools.read_tools import register_read_tools
from wormbase_core.mcp_tools.write_tools import register_write_tools
from wormbase_core.mcp_tools.resources import register_resources
from wormbase_core.mcp_tools.prompts import register_prompts

__all__ = [
    "register_audit_tools",
    "register_prompts",
    "register_read_tools",
    "register_resources",
    "register_write_tools",
]
