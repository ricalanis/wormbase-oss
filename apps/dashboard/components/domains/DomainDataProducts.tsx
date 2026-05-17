/**
 * DomainDataProducts — per-domain data product roster with freshness badges.
 *
 * F5 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Server-side. Reads via getDataProducts(filter by domain). Freshness
 * traffic-lights:
 *   - green   : generated within last 7 days
 *   - amber   : 7..30 days
 *   - red     : older than 30 days
 *
 * Per-domain card includes a deep-link to /data-products?domain_id=...
 * for the full filtered list.
 */
import Link from "next/link";
import type {
  DataProductRow,
  DomainRow,
} from "../../lib/ledger-client.types";

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

export type Freshness = "green" | "amber" | "red" | "never";

export function classifyFreshness(generatedAt: string | null): Freshness {
  if (!generatedAt) return "never";
  const age = Date.now() - Date.parse(generatedAt);
  if (age <= SEVEN_DAYS_MS) return "green";
  if (age <= THIRTY_DAYS_MS) return "amber";
  return "red";
}

const FRESHNESS_COLOR: Record<Freshness, string> = {
  green: "var(--wb-color-botanical-green-deep)",
  amber: "var(--wb-color-sepia-warning-deep)",
  red: "var(--wb-color-sepia-warning-deep)",
  never: "var(--wb-color-hash-gray)",
};

const FRESHNESS_BG: Record<Freshness, string> = {
  green: "var(--wb-color-botanical-green-soft)",
  amber: "var(--wb-color-sepia-warning-soft)",
  red: "var(--wb-color-paper-deep)",
  never: "var(--wb-color-paper-deep)",
};

const FRESHNESS_LABEL: Record<Freshness, string> = {
  green: "fresh",
  amber: "stale",
  red: "old",
  never: "—",
};

export function DomainDataProducts({
  domains,
  dataProducts,
}: {
  domains: DomainRow[];
  dataProducts: DataProductRow[];
}) {
  const byDomain = new Map<string, DataProductRow[]>();
  for (const dp of dataProducts) {
    if (!dp.domainId) continue;
    const arr = byDomain.get(dp.domainId) ?? [];
    arr.push(dp);
    byDomain.set(dp.domainId, arr);
  }

  return (
    <section
      data-testid="domain-data-products"
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <h2
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 22,
          fontWeight: 500,
          letterSpacing: "-0.005em",
        }}
      >
        Data products by domain
      </h2>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 12,
        }}
      >
        {domains.map((d) => {
          const items = byDomain.get(d.domainId) ?? [];
          return (
            <article
              key={d.domainId}
              data-testid={`domain-data-product-card-${d.domainId}`}
              style={{
                border: "1px solid var(--wb-color-aged-ink)",
                padding: 12,
                background: "var(--wb-color-paper)",
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              <header
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  borderBottom: "1px solid var(--wb-color-paper-edge)",
                  paddingBottom: 6,
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 16,
                    fontWeight: 500,
                  }}
                >
                  {d.name}
                </span>
                <Link
                  href={`/data-products?domain_id=${encodeURIComponent(d.domainId)}`}
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray)",
                    textDecoration: "none",
                  }}
                >
                  {items.length} product{items.length === 1 ? "" : "s"} →
                </Link>
              </header>
              {items.length === 0 ? (
                <p
                  style={{
                    margin: 0,
                    fontFamily: "var(--wb-font-serif)",
                    fontStyle: "italic",
                    fontSize: 13,
                    color: "var(--wb-color-hash-gray)",
                  }}
                >
                  No data products yet.
                </p>
              ) : (
                <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {items.slice(0, 5).map((dp) => {
                    const f = classifyFreshness(dp.generatedAt);
                    return (
                      <li
                        key={dp.dataProductId}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          gap: 8,
                          padding: "4px 0",
                          fontFamily: "var(--wb-font-mono)",
                          fontSize: 12,
                        }}
                      >
                        <Link
                          href={`/data-products/${dp.dataProductId}`}
                          style={{
                            color: "var(--wb-color-aged-ink)",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            flex: 1,
                          }}
                        >
                          {dp.name}
                        </Link>
                        <span
                          data-testid={`freshness-${dp.dataProductId}`}
                          style={{
                            fontSize: 10,
                            letterSpacing: "0.06em",
                            textTransform: "uppercase",
                            padding: "2px 6px",
                            color: FRESHNESS_COLOR[f],
                            background: FRESHNESS_BG[f],
                            border: `1px solid ${FRESHNESS_COLOR[f]}`,
                          }}
                        >
                          {FRESHNESS_LABEL[f]}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
