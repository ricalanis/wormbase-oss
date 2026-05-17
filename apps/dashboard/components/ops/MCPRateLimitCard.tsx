/**
 * MCPRateLimitCard — per-tenant rate-limit status.
 *
 * Reads the existing `WORMBASE_MCP_RATE_LIMIT_PER_MIN` ceiling and the
 * trailing 60-second call counts from worm-core's audit log. Renders one
 * row per tenant (baseworm + democorp at minimum) showing
 * `callsInWindow / ceiling` plus a saturation badge.
 *
 * MCP-disabled state: when the worm-core MCP server isn't enabled
 * (`WORMBASE_MCP_ENABLED=0`) the card renders an honest "MCP disabled"
 * message and the per-tenant rows are suppressed.
 */

import type { MCPRateLimits } from "../../lib/ledger-client.types";

export function MCPRateLimitCard({ rateLimits }: { rateLimits: MCPRateLimits }) {
  return (
    <section
      data-testid="ops-mcp-rate-limit"
      style={{
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper)",
        padding: "16px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        MCP · rate-limit status per tenant
      </span>

      {!rateLimits.enabled ? (
        <p
          data-testid="ops-mcp-rate-limit-disabled"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 13,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {rateLimits.disabledReason ??
            "MCP server is disabled — set WORMBASE_MCP_ENABLED=1 to expose the rate-limit gate."}
        </p>
      ) : rateLimits.tenants.length === 0 ? (
        <p
          data-testid="ops-mcp-rate-limit-empty"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 13,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          No registered tenants reporting yet.
        </p>
      ) : (
        <table
          data-testid="ops-mcp-rate-limit-table"
          style={{
            width: "100%",
            borderCollapse: "collapse",
            borderTop: "1px solid var(--wb-color-aged-ink)",
          }}
        >
          <thead>
            <tr style={{ borderBottom: "1px solid var(--wb-color-aged-ink)" }}>
              <Th>Tenant</Th>
              <Th>Calls (window)</Th>
              <Th>Ceiling / min</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {rateLimits.tenants.map((t) => {
              const pct =
                t.ceilingPerMin > 0
                  ? Math.min(100, (t.callsInWindow / t.ceilingPerMin) * 100)
                  : 0;
              return (
                <tr
                  key={t.companyId}
                  data-testid={`ops-mcp-rate-limit-row-${t.tenantSlug}`}
                  style={{
                    borderBottom: "1px solid var(--wb-color-paper-edge)",
                  }}
                >
                  <Td>
                    <span
                      style={{
                        fontFamily: "var(--wb-font-serif)",
                        fontSize: 14,
                      }}
                    >
                      {t.tenantDisplayName}
                    </span>
                    <span
                      className="wb-mono"
                      style={{
                        marginLeft: 8,
                        fontSize: 11,
                        color: "var(--wb-color-hash-gray)",
                      }}
                    >
                      {t.tenantSlug}
                    </span>
                  </Td>
                  <Td mono>
                    {t.callsInWindow.toLocaleString()}
                    <span
                      aria-hidden
                      style={{
                        display: "inline-block",
                        width: 60,
                        height: 4,
                        marginLeft: 8,
                        background: "var(--wb-color-paper-edge)",
                        verticalAlign: "middle",
                      }}
                    >
                      <span
                        style={{
                          display: "block",
                          height: 4,
                          width: `${pct}%`,
                          background: t.saturated
                            ? "#9c1f1f"
                            : "var(--wb-color-botanical-green-deep)",
                        }}
                      />
                    </span>
                  </Td>
                  <Td mono>{t.ceilingPerMin.toLocaleString()}</Td>
                  <Td>
                    <span
                      data-testid={`ops-mcp-rate-limit-status-${t.tenantSlug}`}
                      data-saturated={t.saturated ? "true" : "false"}
                      className="wb-mono"
                      style={{
                        fontSize: 11,
                        textTransform: "uppercase",
                        letterSpacing: "0.1em",
                        padding: "2px 8px",
                        border: `1px solid ${
                          t.saturated ? "#9c1f1f" : "var(--wb-color-botanical-green-deep)"
                        }`,
                        color: t.saturated
                          ? "#9c1f1f"
                          : "var(--wb-color-botanical-green-deep)",
                      }}
                    >
                      {t.saturated ? "saturated" : "ok"}
                    </span>
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th
      scope="col"
      style={{
        textAlign: "left",
        padding: "8px 12px",
        fontFamily: "var(--wb-font-serif)",
        fontSize: 12,
        fontWeight: 500,
        textTransform: "uppercase",
        color: "var(--wb-color-hash-gray)",
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  mono = false,
}: {
  children: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <td
      className={mono ? "wb-mono" : undefined}
      style={{
        padding: "10px 12px",
        fontFamily: mono
          ? "var(--wb-font-mono)"
          : "var(--wb-font-serif)",
        fontSize: 13,
        color: "var(--wb-color-aged-ink)",
      }}
    >
      {children}
    </td>
  );
}
