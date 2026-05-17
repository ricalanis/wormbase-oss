#!/usr/bin/env bash
# Beat 8 helper — fires audit_decision against the running MCP server.
# Inputs: DECISION_ID (required), COMPANY_SLUG (default baseworm),
# WORMBASE_MCP_URL (default :9911/mcp), WORMBASE_MCP_TOKEN (default
# $WORMBASE_LEDGER_API_TOKEN). Same code path as the live AI-client
# call; lands one emit_mcp_call_received audit entry on the ledger.
set -euo pipefail
URL="${WORMBASE_MCP_URL:-http://localhost:9911/mcp}"
TOKEN="${WORMBASE_MCP_TOKEN:-${WORMBASE_LEDGER_API_TOKEN:-dev-only-token-rotate-in-prod}}"
COMPANY="${COMPANY_SLUG:-baseworm}"
DECISION="${DECISION_ID:-}"
[[ -n "$DECISION" ]] || { echo "DECISION_ID required" >&2; exit 2; }
exec uv run --package wormbase-worm-core --extra dev python - "$URL" "$TOKEN" "$COMPANY" "$DECISION" <<'PY'
import asyncio, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
url, token, company, decision = sys.argv[1:5]
async def main():
    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            result = await session.get_prompt("audit_decision", arguments={"company_id": company, "decision_id": decision})
            for msg in result.messages:
                text = getattr(msg.content, "text", None) or str(msg.content)
                print(f"--- {msg.role} ---\n{text}")
asyncio.run(main())
PY
