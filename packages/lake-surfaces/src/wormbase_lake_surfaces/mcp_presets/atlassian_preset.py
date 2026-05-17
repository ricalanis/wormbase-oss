"""Atlassian (Jira + Confluence) MCP preset (``mcp:atlassian``).

Atlassian Rovo MCP, GA Feb 2026, hosted on Cloudflare. OAuth 2.1 +
API token. SSE endpoint deprecates June 30 2026 — we use the new
``/v1/mcp`` Streamable HTTP endpoint. Coverage: Jira issues + Confluence
pages — search, create, update, link.
"""

from __future__ import annotations

from ..mcp import MCPServerConfig, make_mcp_preset

ATLASSIAN_CONFIG = MCPServerConfig(
    kind="mcp:atlassian",
    server_url="https://mcp.atlassian.com/v1/mcp",
    required_secrets=("bearer_token",),
    optional_secrets=("cloud_id", "site_url"),
    classification_hints=("internal",),
    scopes=(
        "read:jira-work",
        "read:jira-user",
        "read:confluence-content.all",
        "read:confluence-space.summary",
    ),
    description=(
        "Jira issues + Confluence pages — search, retrieve, link. The "
        "decision-and-process adjacency to the conversation lake."
    ),
)

AtlassianMCPConnector = make_mcp_preset(ATLASSIAN_CONFIG, status="preview")

__all__ = ["ATLASSIAN_CONFIG", "AtlassianMCPConnector"]
