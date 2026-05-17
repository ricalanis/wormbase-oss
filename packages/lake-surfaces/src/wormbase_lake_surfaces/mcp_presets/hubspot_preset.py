"""HubSpot MCP preset (``mcp:hubspot``).

HubSpot's official remote MCP, GA April 13 2026. OAuth 2.1 via the
new self-service "MCP Auth Apps" flow. Coverage: CRM read+write for
Contacts/Companies/Deals/Tickets/Line items/Products + read-only
campaigns/landing pages.

This preset is the alternative path to the existing native
``hubspot`` connector — admins can pick MCP-vs-native side-by-side
in the connector picker. Same surface area; the trade-off is
schema-stability (vendor-maintained MCP can drift) vs.
implementation-control (native httpx call we own).
"""

from __future__ import annotations

from ..mcp import MCPServerConfig, make_mcp_preset

HUBSPOT_CONFIG = MCPServerConfig(
    kind="mcp:hubspot",
    server_url="https://mcp.hubspot.com/mcp",
    required_secrets=("bearer_token",),
    optional_secrets=("portal_id",),
    classification_hints=("pii",),
    scopes=(
        "crm.objects.contacts.read",
        "crm.objects.companies.read",
        "crm.objects.deals.read",
        "crm.objects.tickets.read",
    ),
    description=(
        "HubSpot CRM — contacts, companies, deals, tickets. Alternative "
        "to the native HubSpot connector; choose the MCP path when you "
        "want the vendor to own schema drift."
    ),
)

HubspotMCPSurfaceDriver = make_mcp_preset(HUBSPOT_CONFIG, status="preview")

__all__ = ["HUBSPOT_CONFIG", "HubspotMCPSurfaceDriver"]
