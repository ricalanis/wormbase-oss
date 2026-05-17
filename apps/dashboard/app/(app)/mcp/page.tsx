/**
 * /mcp — Block J6 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Three panels:
 *
 * 1. Local MCP server catalog (tools / resources / prompts that the
 *    worm-core MCP server exposes to outbound clients like Claude
 *    Desktop, Cursor, Cline).
 * 2. Recent inbound MCP calls — read straight from
 *    ``projection_mcp_calls`` (audit log).
 * 3. Per-tenant rate-limit status — derived from the same audit log
 *    (count + last-call-at; the actual rate-limit gate lives
 *    server-side in J5).
 *
 * Server component. Reads only ledger projections + the worm-core
 * catalog endpoint (when reachable). No fixture fallbacks — empty
 * states render an honest "no MCP calls yet / MCP server not yet
 * running" copy with a named trigger flow.
 *
 * Visibility per role-nav.ts: admin (daily), observer (weekly).
 * Members + installer don't see this tab — privacy: the audit log
 * surfaces caller identities that members shouldn't browse.
 */

import {
  getMcpCalls,
  getMcpCatalog,
} from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { getMcpServerUrl } from "../../../lib/server/dashboard-url";
import { CatalogPanel } from "../../../components/mcp/CatalogPanel";
import { RecentCallsTable } from "../../../components/mcp/RecentCallsTable";
import { ConnectClaudeDesktopPanel } from "../../../components/mcp/ConnectClaudeDesktopPanel";
import { AddMcpServerWizard } from "../../../components/mcp/AddMcpServerWizard";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · MCP" };

const RATE_LIMIT_WINDOW_MIN = 60;

function callsInWindow(
  rows: { startedAt: string }[],
  windowMin: number,
): number {
  const cutoff = Date.now() - windowMin * 60_000;
  return rows.filter((r) => Date.parse(r.startedAt) >= cutoff).length;
}

export default async function McpPage() {
  const companyId = await getCurrentCompanyId();
  const [catalog, calls] = await Promise.all([
    getMcpCatalog(companyId),
    getMcpCalls(companyId, 50),
  ]);
  // W7.A4 — resolve the snippet URL server-side so a remote Claude
  // Desktop can reach this tenant's MCP server via the cloudflared
  // tunnel proxy. ``WORMBASE_DASHBOARD_URL`` stays in process.env;
  // only the resolved URL + mode crosses the RSC boundary.
  const mcpServer = getMcpServerUrl();

  const totalCalls = calls.length;
  const recentCallsInWindow = callsInWindow(calls, RATE_LIMIT_WINDOW_MIN);
  const lastCall = calls[0];

  return (
    <PageBoundary surface="MCP" traceQuery="?surface=mcp">
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Block J · MCP integration · live
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 34,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          MCP
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          The worm exposes its full feature surface (tools, resources,
          prompts) over the Model Context Protocol. Every inbound call is
          audited as a ledger entry; replay is byte-identical.
        </p>
      </header>

      <RateLimitSummary
        total={totalCalls}
        windowMin={RATE_LIMIT_WINDOW_MIN}
        windowCount={recentCallsInWindow}
        lastCallAt={lastCall?.startedAt ?? null}
      />

      <section
        data-testid="mcp-connect-section"
        style={{ display: "flex", flexDirection: "column", gap: 16 }}
      >
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
          }}
        >
          Connect a client
        </h2>
        <ConnectClaudeDesktopPanel
          mcpUrl={mcpServer.url}
          mode={mcpServer.mode}
        />
      </section>

      <section
        data-testid="mcp-add-server-section"
        style={{ display: "flex", flexDirection: "column", gap: 16 }}
      >
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
          }}
        >
          Add MCP server
        </h2>
        <AddMcpServerWizard />
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
          }}
        >
          Server catalog
        </h2>
        <CatalogPanel catalog={catalog} />
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
          }}
        >
          Recent calls
        </h2>
        <RecentCallsTable rows={calls} />
      </section>
    </PageBoundary>
  );
}

function RateLimitSummary({
  total,
  windowMin,
  windowCount,
  lastCallAt,
}: {
  total: number;
  windowMin: number;
  windowCount: number;
  lastCallAt: string | null;
}) {
  return (
    <section
      data-testid="mcp-rate-limit"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
        gap: 16,
        border: "1px solid var(--wb-color-aged-ink)",
        padding: "16px 20px",
      }}
    >
      <Stat
        label="Total recorded"
        value={total.toLocaleString()}
        hint="Inbound MCP calls in audit log"
      />
      <Stat
        label={`Last ${windowMin} min`}
        value={windowCount.toLocaleString()}
        hint="Reads against the per-tenant rate-limit window"
      />
      <Stat
        label="Last call"
        value={
          lastCallAt
            ? new Date(lastCallAt).toISOString().slice(0, 19) + "Z"
            : "—"
        }
        hint={lastCallAt ? "Most recent inbound call" : "No calls yet"}
      />
    </section>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: 24,
          fontWeight: 500,
          color: "var(--wb-color-aged-ink)",
        }}
      >
        {value}
      </span>
      <span
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          fontSize: 12,
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {hint}
      </span>
    </div>
  );
}
