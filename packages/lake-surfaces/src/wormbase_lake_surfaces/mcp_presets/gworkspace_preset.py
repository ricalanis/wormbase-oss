"""Google Workspace MCP preset (``mcp:gworkspace``).

Google's official Workspace MCP server, GA Cloud Next 2026. Bundles
Gmail (10 tools), Drive (7), Calendar (8), People (3), Chat (2). For
WormBase v1 we declare the scopes we actually need: Calendar + Drive +
Sheets — the doc/decision adjacency to the conversation lake. Gmail
and Chat tools are reachable but not the v1 cut.
"""

from __future__ import annotations

from ..mcp import MCPServerConfig, make_mcp_preset

GWORKSPACE_CONFIG = MCPServerConfig(
    kind="mcp:gworkspace",
    server_url="https://mcp.workspace.google.com/mcp",
    required_secrets=("bearer_token",),
    optional_secrets=("workspace_domain",),
    classification_hints=("internal", "pii"),
    scopes=(
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    ),
    description=(
        "Google Calendar, Drive, and Sheets — meetings, documents, and "
        "spreadsheets adjacent to the org's decision flow."
    ),
)

GworkspaceMCPSurfaceDriver = make_mcp_preset(GWORKSPACE_CONFIG, status="preview")

__all__ = ["GWORKSPACE_CONFIG", "GworkspaceMCPSurfaceDriver"]
