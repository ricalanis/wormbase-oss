# `/mcp` — User guide

## What it does

The MCP tab is the **MCP-native institutional AI** surface. Three panels:

1. **Local MCP server catalog** — every tool, resource, and prompt the
   worm-core MCP server exposes outbound to clients (Claude Desktop,
   Cursor, Cline, custom agents).
2. **Recent inbound MCP calls** — the audit log, read straight from
   `projection_mcp_calls`. Every external AI agent's touch on the
   tenant's substrate, hash-chained, role-aware.
3. **Per-tenant rate-limit status** — call counts + last-call-at,
   derived from the same audit log.

Per the role-nav, this tab is **admin (daily)** and **observer
(weekly)**. Members and the installer don't see it during onboarding —
the audit log surfaces caller identities that members shouldn't browse.

This is the C6 auditable-governance close: **nobody else makes the MCP
audit log a first-class customer artifact.**

## First action

Connect Claude Desktop to your tenant's MCP server:

1. Open `/mcp`. Click the **Connect Claude Desktop** panel.
2. Click **Generate token**. Writes `emit_token_issued`; the panel
   renders a JSON snippet:

   ```json
   {
     "mcp": {
       "wormbase": {
         "url": "http://localhost:9911/mcp",
         "transport": "streamable_http",
         "headers": {
           "Authorization": "Bearer wb_dev_<company_id>_<person_id>_<random>_<hmac>"
         }
       }
     }
   }
   ```

3. Copy the snippet into Claude Desktop's MCP config (typically at
   `~/Library/Application Support/Claude/claude_desktop_config.json` on
   macOS).
4. Restart Claude Desktop. The catalog tools (`query_kpis`,
   `query_decisions`, `query_processes`, etc.) appear in Claude's tool
   menu.

To exercise:

1. In Claude Desktop, ask: "audit decision `<decision_id>` from baseworm
   — walk the chain of custody."
2. Claude picks the `audit_decision` prompt, calls the WormBase MCP
   server, receives the four-step narrative (decision → process map →
   KPIs → source bytes), and renders.
3. Alt-tab back to `/mcp`. The call appears at the top of
   **Recent inbound MCP calls** within ~1s. Click it — drill-in shows
   `tool_name="prompts/audit_decision"`, the args_hash, the latency, and
   the caller's bearer-token-derived identity.

## Advanced

- **Add an external MCP server** (inbound — worm consumes external) — open
  the **Add MCP server** wizard. Pick a preset (`mcp:notion`,
  `mcp:atlassian`, `mcp:linear`, `mcp:github`, `mcp:google_workspace`,
  `mcp:hubspot`) or paste a custom URL + auth. Writes
  `emit_source_proposed` with `kind=mcp:<preset>`. Same Connector
  contract as direct-API sources — see [`/sources`](sources.md).
- **Revoke a token** — open the catalog panel; click any issued token →
  **Revoke**. Writes `emit_token_revoked`. The token is invalidated
  immediately; in-flight requests with that bearer return 401.
- **Inspect a call** — click any row in the audit log. Drill-in shows the
  full PEVR chain (`emit_mcp_call_received → emit_mcp_call_resolved`),
  the args_hash + truncated args (full args in encrypted side-storage if
  classified), the role-filter applied, the rate-limit budget remaining.
- **Set rate limits** — admin-only. `/settings/mcp` exposes per-(tenant,
  Person, tool) budgets — N calls / hour, N calls / day. Limit exceeded
  → gate writes `emit_mcp_call_rate_limited` and the call returns 429.
  Budgets are folded directly from the audit log; no Redis.
- **Filter calls by Person / tool / time-range** — chips at the top of
  the audit panel. URL-driven; shareable.

## Behind the scenes

Reads from `projection_mcp_calls`, a fold of these ledger entries:

```
emit_mcp_call_received    {company_id, caller_person_id, caller_client,
                           tool_name | resource_uri,
                           args_hash, classification, ts}
emit_mcp_call_resolved    {call_id, status, rows_returned,
                           output_hash, output_classification,
                           duration_ms, ts}
emit_mcp_call_rate_limited (gate-emit instead of received)
emit_token_issued
emit_token_revoked
```

The MCP server lives at `apps/worm-core/src/wormbase_core/mcp_server.py`.
FastMCP 3.0 over Streamable HTTP at `:9911/mcp`. Read tools call into
the same projection helpers the dashboard uses; write tools wrap their
work in PEVR chains via `write_actions.py`.

**Privacy nuance** — the call audit can itself be classified (a deny on
a PII query reveals existence of PII data). The classification
min-cap means observers see `<call denied>` not `<call denied for query
containing email "ricardo@…">`.

**Role-aware filtering** is the same role-grant join the dashboard uses
for `useNavForRole` — reused, not duplicated. `tenancy.observer` sees
read-only with PII redaction; `tenancy.member` hides domains they have
no grant for; `tenancy.admin` sees full visibility within tenant;
cross-tenant is always denied.

## Why MCP-native institutional AI

Atlan, Glean, Atlassian, Notion, dbt Cloud, Monte Carlo all ship MCP
servers in 2026. **Nobody else makes the MCP audit log a first-class
customer artifact on a hash-chained ledger.** The competing servers are
query surfaces; the WormBase MCP server is a **truth surface** —
hash-stable, replayable, classification-governed, role-filtered.

> "Atlan's MCP gives Claude Desktop your column-level lineage. Glean's
> MCP gives Claude your search results. WormBase's MCP gives Claude your
> decisions, your processes, your KPIs, your conversations, AND an audit
> log of every query Claude just made. The first three vendors are
> oracles. WormBase is the substrate."

Full design (10 dimensions + 5-phase plan) in
[`docs/superpowers/specs/2026-04-27-mcp-integration.md`](../superpowers/specs/2026-04-27-mcp-integration.md).

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Catalog panel says "MCP server not running" | worm-core's MCP subsystem failed to bind :9911 | `make worm-logs \| grep mcp_server`; restart |
| Token works in curl but not Claude Desktop | Streamable HTTP transport mismatch | Confirm Claude Desktop ≥ release with Streamable HTTP support; v0.x clients used HTTP+SSE which is deprecated |
| Audit log empty after Claude calls | Token's `company_id` doesn't match the cookie's tenant | Re-issue token from the right tenant |
| Rate-limit fires on every call | Budget set too tight | Raise via `/settings/mcp`; defaults are 1000 calls / hour |
| Add MCP server wizard rejects URL | Connector preset not registered | Add to `packages/lake-surfaces/mcp_presets/`; restart worm-core |
