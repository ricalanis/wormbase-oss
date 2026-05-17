/**
 * /status/connector/{kind} — Sub-wave D connector probe detail.
 *
 * Click-through from the marketplace probe badge. Renders the full
 * probe envelope (state + reason + timestamp). The probe is fetched
 * server-side on every page load so the timestamp reflects the most
 * recent attempt.
 */
import Link from "next/link";

import { PageBoundary } from "../../../../../components/chrome/PageBoundary";
import { probeConnector } from "../../../../../lib/connector-probes";

export const dynamic = "force-dynamic";
export const metadata = { title: "WormBase · Connector probe" };

export default async function ConnectorProbeDetailPage({
  params,
}: {
  params: Promise<{ kind: string }>;
}): Promise<JSX.Element> {
  const { kind } = await params;
  const cleanKind = decodeURIComponent(kind ?? "");
  const probedAt = new Date().toISOString();
  const probe = await probeConnector(cleanKind);

  return (
    <PageBoundary
      surface="connector probe"
      traceQuery={`?surface=connector.probe&kind=${cleanKind}`}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray, #7c7569)",
          }}
        >
          Connector probe · per-tenant health
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 28,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          {cleanKind}
        </h1>
      </header>

      <section
        data-testid="connector-probe-detail"
        style={{
          marginTop: 16,
          border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
          padding: 14,
          background: "var(--wb-color-paper, #f8f3e1)",
        }}
      >
        <dl style={{ margin: 0 }}>
          <dt
            className="wb-mono"
            style={{ fontSize: 10, textTransform: "uppercase" }}
          >
            state
          </dt>
          <dd
            data-testid="connector-probe-state"
            className="wb-mono"
            style={{ fontSize: 14, marginBottom: 12 }}
          >
            {probe.state}
          </dd>
          <dt
            className="wb-mono"
            style={{ fontSize: 10, textTransform: "uppercase" }}
          >
            reason
          </dt>
          <dd
            data-testid="connector-probe-reason"
            style={{ fontSize: 12, marginBottom: 12, fontStyle: "italic" }}
          >
            {probe.reason ?? "—"}
          </dd>
          <dt
            className="wb-mono"
            style={{ fontSize: 10, textTransform: "uppercase" }}
          >
            probed at
          </dt>
          <dd
            data-testid="connector-probe-ts"
            className="wb-mono"
            style={{ fontSize: 11 }}
          >
            {probedAt}
          </dd>
        </dl>
      </section>

      <section style={{ marginTop: 16 }}>
        <Link
          href="/lake/surfaces"
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "8px 16px",
            border: "1px solid var(--wb-color-aged-ink, #2a2620)",
            background: "var(--wb-color-paper, #f8f3e1)",
            color: "var(--wb-color-aged-ink, #2a2620)",
            textDecoration: "none",
          }}
        >
          ← back to connectors
        </Link>
      </section>
    </PageBoundary>
  );
}
