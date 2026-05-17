"""Notion MCP preset (``mcp:notion``).

Official Notion MCP server, GA 2026 (v2.0.0, Notion API 2025-09-03).
18 tools — search-and-content focused. OAuth 2.1; bearer token after
the OAuth dance. Limitation: human-present required for many flows
(documented upstream); unattended agentic use is partial in v1.
"""

from __future__ import annotations

from ..mcp import MCPServerConfig, make_mcp_preset

NOTION_CONFIG = MCPServerConfig(
    kind="mcp:notion",
    server_url="https://mcp.notion.com/mcp",
    required_secrets=("bearer_token",),
    optional_secrets=("workspace_id",),
    classification_hints=("internal",),
    scopes=("read_content", "read_comments", "read_users"),
    description=(
        "Notion workspace pages, databases, and comments — read access "
        "for ingest into the conversation lake."
    ),
)

NotionMCPSurfaceDriver = make_mcp_preset(NOTION_CONFIG, status="preview")

__all__ = ["NOTION_CONFIG", "NotionMCPSurfaceDriver"]
