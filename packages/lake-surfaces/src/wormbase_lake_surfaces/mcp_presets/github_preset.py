"""GitHub MCP preset (``mcp:github``).

GitHub's official MCP server, hosted by GitHub. OAuth 2.1. Coverage:
repos, issues, PRs, files. Carries source-code adjacency for the
system-map gold artifact (who-touches-what files / who-reviews-what
PRs maps to person-position chatter).
"""

from __future__ import annotations

from ..mcp import MCPServerConfig, make_mcp_preset

GITHUB_CONFIG = MCPServerConfig(
    kind="mcp:github",
    server_url="https://api.githubcopilot.com/mcp/",
    required_secrets=("bearer_token",),
    optional_secrets=("organization", "default_repo"),
    classification_hints=("internal",),
    scopes=("repo", "read:org", "read:user"),
    description=(
        "GitHub repos, issues, pull requests, and files — engineering "
        "context for the system-map and decision provenance."
    ),
)

GithubMCPSurfaceDriver = make_mcp_preset(GITHUB_CONFIG, status="preview")

__all__ = ["GITHUB_CONFIG", "GithubMCPSurfaceDriver"]
