/**
 * CatalogPanel — local MCP server's exposed surface (Block J6).
 *
 * Reads the worm-core MCP server's catalog (tools / resources / prompts
 * registered for outbound invocation) and renders three table sections.
 *
 * Honest empty state: when ``catalog.available`` is ``false`` the panel
 * renders an EmptyState explaining that the MCP server isn't running
 * yet. No fixture-fallback rows: a tab with no rows reads as a tab
 * with no rows (per CLAUDE.md cleanup checklist).
 *
 * Visual chrome mirrors PeopleRoster / DataProductsTable: square
 * corners, wb-mono ids, serif names, sepia dashed border for empty.
 */

import type { McpCatalog, McpCatalogEntry } from "../../lib/ledger-client.types";
import { EmptyState } from "../chrome/EmptyState";
import { chipStyle } from "../people/_styles";

type CatalogKind = McpCatalogEntry["kind"];

const SECTIONS: { kind: CatalogKind; label: string; description: string }[] = [
  {
    kind: "tool",
    label: "Tools",
    description:
      "Read + write tools an MCP client (Claude Desktop, Cursor, Cline) can invoke against this tenant.",
  },
  {
    kind: "resource",
    label: "Resources",
    description:
      "URI-addressable read context — ledger, KPIs, decisions, conversations.",
  },
  {
    kind: "prompt",
    label: "Prompts",
    description:
      "Shareable templates an MCP client can render (audit_decision, cfo_snapshot, whats_new_today).",
  },
];

export function CatalogPanel({ catalog }: { catalog: McpCatalog }) {
  if (!catalog.available) {
    return (
      <EmptyState
        testId="mcp-catalog-empty"
        eyebrow="mcp server not yet running"
        title="The MCP server isn't reachable yet."
        description={
          "Start the worm-core MCP server (set WORMBASE_MCP_ENABLED=1 + " +
          "WORMBASE_MCP_CATALOG_URL) to surface the tools, resources, and " +
          "prompts this tenant exposes outbound to Claude Desktop, Cursor, " +
          "and other MCP clients."
        }
      />
    );
  }

  const groupedByKind = new Map<CatalogKind, McpCatalogEntry[]>();
  for (const entry of catalog.entries) {
    const arr = groupedByKind.get(entry.kind) ?? [];
    arr.push(entry);
    groupedByKind.set(entry.kind, arr);
  }

  return (
    <section
      data-testid="mcp-catalog"
      style={{ display: "flex", flexDirection: "column", gap: 24 }}
    >
      {SECTIONS.map((section) => {
        const rows = groupedByKind.get(section.kind) ?? [];
        return (
          <CatalogSection
            key={section.kind}
            section={section}
            rows={rows}
          />
        );
      })}
    </section>
  );
}

function CatalogSection({
  section,
  rows,
}: {
  section: { kind: CatalogKind; label: string; description: string };
  rows: McpCatalogEntry[];
}) {
  return (
    <section
      data-testid={`mcp-catalog-section-${section.kind}`}
      style={{ display: "flex", flexDirection: "column", gap: 8 }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 18,
            fontWeight: 500,
          }}
        >
          {section.label}
          <span
            className="wb-mono"
            style={{
              marginLeft: 8,
              fontSize: 12,
              color: "var(--wb-color-hash-gray)",
            }}
          >
            ({rows.length})
          </span>
        </h3>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          {section.description}
        </p>
      </header>

      {rows.length === 0 ? (
        <p
          data-testid={`mcp-catalog-section-${section.kind}-empty`}
          style={{
            padding: "16px 12px",
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
            border: "1px dashed var(--wb-color-paper-edge)",
          }}
        >
          No {section.label.toLowerCase()} registered yet.
        </p>
      ) : (
        <table
          data-testid={`mcp-catalog-table-${section.kind}`}
          style={{
            width: "100%",
            borderCollapse: "collapse",
            borderTop: "1px solid var(--wb-color-aged-ink)",
          }}
        >
          <thead>
            <tr style={{ borderBottom: "1px solid var(--wb-color-aged-ink)" }}>
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
                Name
              </th>
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
                Description
              </th>
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
                Tags
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((entry) => (
              <tr
                key={`${section.kind}:${entry.name}`}
                data-testid={`mcp-catalog-row-${section.kind}`}
                style={{
                  borderBottom: "1px solid var(--wb-color-paper-edge)",
                }}
              >
                <td
                  className="wb-mono"
                  style={{
                    padding: "10px 12px",
                    fontSize: 13,
                    color: "var(--wb-color-aged-ink)",
                  }}
                >
                  {entry.name}
                </td>
                <td
                  style={{
                    padding: "10px 12px",
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 13,
                    color: "var(--wb-color-aged-ink)",
                  }}
                >
                  {entry.description || "—"}
                </td>
                <td style={{ padding: "10px 12px" }}>
                  <span
                    style={{
                      display: "inline-flex",
                      flexWrap: "wrap",
                      gap: 4,
                    }}
                  >
                    {(entry.tags ?? []).map((tag) => (
                      <span key={tag} style={chipStyle("neutral")}>
                        {tag}
                      </span>
                    ))}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
