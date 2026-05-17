/**
 * /sources/new/[connector] — per-connector configure form.
 *
 * W2.A5 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Renders the field schema returned by worm-core's `/api/v1/connectors`
 * for one specific kind, plus the test-connection panel and a
 * propose-source CTA. Coming-soon connectors render an honest banner
 * and disable the form — the same kind handler in
 * `/api/v1/connectors/test/{kind}` rejects coming-soon kinds with a
 * 409 so even direct API hits behave consistently.
 */
import Link from "next/link";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import type { ConnectorEntry } from "../../../../api/v1/connectors/list/route";
import { ConnectorConfigure } from "../../../../../components/sources/ConnectorConfigure";
import { PageBoundary } from "../../../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Configure connector" };
export const dynamic = "force-dynamic";

async function fetchConnector(kind: string): Promise<ConnectorEntry | null> {
  const h = await headers();
  const host = h.get("host") ?? "localhost:3000";
  const proto = h.get("x-forwarded-proto") ?? "http";
  const url = `${proto}://${host}/api/v1/connectors/list`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    const body = (await res.json()) as { kinds?: ConnectorEntry[] };
    const kinds = Array.isArray(body.kinds) ? body.kinds : [];
    return kinds.find((c) => c.kind === kind) ?? null;
  } catch {
    return null;
  }
}

export default async function ConnectorConfigurePage({
  params,
}: {
  params: Promise<{ connector: string }>;
}) {
  const { connector } = await params;
  const decoded = decodeURIComponent(connector);
  const entry = await fetchConnector(decoded);
  if (!entry) {
    notFound();
  }
  return (
    <PageBoundary surface="connector configure" traceQuery={`?surface=connector&kind=${decoded}`} preserveFormState>
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
            Pl. VI · Configure · {entry.kind}
          </span>
          <h1
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 30,
              fontWeight: 500,
              letterSpacing: "-0.01em",
            }}
          >
            {entry.label}
          </h1>
          <p
            data-testid="connector-status-note"
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {entry.status_note}
          </p>
        </div>
        <Link
          href="/sources/new"
          className="wb-mono"
          data-testid="back-to-grid"
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
        >
          ← back to grid
        </Link>
      </header>

      <ConnectorConfigure entry={entry} />
    </PageBoundary>
  );
}
