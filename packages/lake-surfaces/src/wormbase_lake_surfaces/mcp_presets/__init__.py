"""MCP server presets — one config per official vendor MCP server.

Each preset registers a per-server :class:`MCPConnector` subclass with
the default registry under a prefixed kind:

* ``mcp:notion``      — Notion (official, GA 2026)
* ``mcp:atlassian``   — Jira + Confluence (Rovo MCP, GA Feb 2026)
* ``mcp:linear``      — Linear (official remote, GA early 2026)
* ``mcp:github``      — GitHub (official hosted)
* ``mcp:gworkspace``  — Google Workspace (Calendar + Drive + Sheets)
* ``mcp:hubspot``     — HubSpot (official remote, GA April 2026)

Importing this package eagerly imports each preset module; the
``make_mcp_preset(...)`` call inside each module fires the
``register_connector`` decorator. The dashboard's connector picker
(D4) sees them alongside the native connectors.

This is the v1 cut. New presets are added by dropping a 30-LOC file
in this package — no core code changes needed.
"""

from __future__ import annotations

from . import (  # noqa: F401  — eager imports for self-registration
    atlassian_preset,
    github_preset,
    gworkspace_preset,
    hubspot_preset,
    linear_preset,
    notion_preset,
)

__all__ = [
    "atlassian_preset",
    "github_preset",
    "gworkspace_preset",
    "hubspot_preset",
    "linear_preset",
    "notion_preset",
]
