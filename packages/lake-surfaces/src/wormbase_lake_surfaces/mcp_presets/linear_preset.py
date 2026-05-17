"""Linear MCP preset (``mcp:linear``).

Linear's official remote MCP server, GA early 2026 — hosted at
``mcp.linear.app``. SSE endpoint deprecated; use ``/mcp`` (Streamable
HTTP). OAuth 2.1. Coverage: initiatives, milestones, updates, issues,
teams, projects.
"""

from __future__ import annotations

from ..mcp import MCPServerConfig, make_mcp_preset

LINEAR_CONFIG = MCPServerConfig(
    kind="mcp:linear",
    server_url="https://mcp.linear.app/mcp",
    required_secrets=("bearer_token",),
    optional_secrets=("workspace_id",),
    classification_hints=("internal",),
    scopes=("read", "issues:read", "projects:read"),
    description=(
        "Linear initiatives, projects, issues, and updates — engineering "
        "workstream signal feeding the system map."
    ),
)

LinearMCPConnector = make_mcp_preset(LINEAR_CONFIG, status="preview")

__all__ = ["LINEAR_CONFIG", "LinearMCPConnector"]
