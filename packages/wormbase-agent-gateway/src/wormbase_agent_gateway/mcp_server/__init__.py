"""FastMCP server + 9 tools — Wave 2 Task 7.

Public surface re-exports the server-builder + the canonical response
shapes so callers (worm-core boot wiring, dashboard introspectors)
can construct a server without poking at private modules.
"""
from __future__ import annotations

from .responses import (
    CatalogTablesResponse,
    DeniedResponse,
    LineageResponse,
    MetricQueryResponse,
    OutcomeRecordedResponse,
    QueryFederateResponse,
    SemanticGapResponse,
    SemanticSearchResponse,
    SuggestCorrectionResponse,
)
from .server import (
    AgentGatewayMCPServer,
    GatewayDeps,
    build_agent_gateway_mcp_server,
)
from .wire_record import MCP_TOOL_CALL_KIND, McpToolCallRecorder

__all__ = [
    "AgentGatewayMCPServer",
    "CatalogTablesResponse",
    "DeniedResponse",
    "GatewayDeps",
    "LineageResponse",
    "MCP_TOOL_CALL_KIND",
    "McpToolCallRecorder",
    "MetricQueryResponse",
    "OutcomeRecordedResponse",
    "QueryFederateResponse",
    "SemanticGapResponse",
    "SemanticSearchResponse",
    "SuggestCorrectionResponse",
    "build_agent_gateway_mcp_server",
]
