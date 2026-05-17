/**
 * /sources/new — connector picker page.
 *
 * W2.A5 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Server component; fetches the connector catalog from the dashboard's
 * `/api/v1/connectors/list` proxy which forwards to worm-core's
 * `/api/v1/connectors`. The Python connector registry is the single
 * source of truth — promote a status (coming_soon → preview →
 * production) by editing the connector class once.
 *
 * On worm-core unreachable this page renders an honest empty grid +
 * retry link rather than falling back to a stale fixture catalog.
 */
import Link from "next/link";
import { headers } from "next/headers";
import type { ConnectorEntry } from "../../../api/v1/connectors/list/route";
import { ConnectorCard } from "../../../../components/sources/ConnectorCard";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · New Source" };
export const dynamic = "force-dynamic";

async function fetchConnectors(): Promise<{
  connectors: ConnectorEntry[];
  error: string | null;
}> {
  // Construct an absolute URL for the server-side fetch — Next 15
  // requires this even for same-origin API routes during RSC.
  const h = await headers();
  const host = h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? "http";
  const url = `${proto}://${host}/api/v1/connectors/list`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      return {
        connectors: [],
        error: `worm-core returned ${res.status}: ${text.slice(0, 200)}`,
      };
    }
    const body = (await res.json()) as { kinds?: ConnectorEntry[] };
    return {
      connectors: Array.isArray(body.kinds) ? body.kinds : [],
      error: null,
    };
  } catch (err) {
    return {
      connectors: [],
      error: (err as Error).message ?? String(err),
    };
  }
}

export default async function NewSourcePage() {
  const { connectors, error } = await fetchConnectors();
  const productionCount = connectors.filter(
    (c) => c.status === "production",
  ).length;
  return (
    <PageBoundary surface="new source" traceQuery="?surface=sources-new">
      <header
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Pl. VI · New source
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
            Add a lake surface
          </h1>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {connectors.length} surfaces registered; {productionCount}{" "}
            production-ready today. The Python registry is the source of
            truth — status badges reflect runtime capability, not promise.
          </p>
        </div>
        <Link
          href="/sources"
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "6px 12px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-paper)",
            color: "var(--wb-color-aged-ink)",
            textDecoration: "none",
            borderRadius: 0,
          }}
          data-testid="back-to-sources"
        >
          ← back to sources
        </Link>
      </header>

      {error ? (
        <div
          data-testid="connectors-error"
          role="alert"
          style={{
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            background: "var(--wb-color-paper-deep)",
            padding: 14,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning-deep)",
            }}
          >
            surface registry unreachable
          </span>
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 12,
              color: "var(--wb-color-aged-ink)",
            }}
          >
            {error}. Verify worm-core is running and{" "}
            <code className="wb-mono">WORMBASE_LEDGER_API_BASE</code> resolves
            to it.
          </span>
        </div>
      ) : null}

      {connectors.length === 0 && !error ? (
        <div
          data-testid="connectors-empty"
          role="note"
          style={{
            border: "1px dashed var(--wb-color-paper-edge)",
            background: "var(--wb-color-paper-deep)",
            padding: 18,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          The lake-surface registry returned an empty list. Check the
          worm-core service is healthy and reachable from the dashboard.
        </div>
      ) : null}

      <section
        data-testid="connector-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
          gap: 12,
        }}
      >
        {connectors.map((c) => (
          <ConnectorCard key={c.kind} entry={c} />
        ))}
      </section>
    </PageBoundary>
  );
}
