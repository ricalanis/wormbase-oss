import Link from "next/link";

import { ChannelCapabilityMatrix } from "../../components/landing/ChannelCapabilityMatrix";
import { SecurityPosture } from "../../components/landing/SecurityPosture";

export const metadata = {
  title: "WormBase · Trust & Security",
  description:
    "WormBase trust & security posture — multi-tenant isolation under contract test, hash-chained ledger, PEVR audit cycles, PII redaction gates, SOC-2 in progress, TLS in transit, Postgres at-rest, Kimi remote / Gemma own-VLAN inference data flow. Honest claims with audit paths.",
};

/**
 * Standalone `/security` (a.k.a. trust posture) route — Phase 4 Task 4E.
 *
 * Public unauthenticated trust page for visitors evaluating WormBase. The
 * pitch is "auditable, hash-receipted, multi-tenant institutional AI"; this
 * page makes that pitch verifiable. Each proof point names the contract
 * test, doctrine document, or source file the reader can audit themselves.
 *
 * Honest claims only:
 *   - "in progress" beats "certified"
 *   - "we use TLS" beats "encrypted everything"
 *   - "the substrate supports it" beats "shipping" when the tooling is roadmap
 *
 * Field Notebook chrome (masthead + footer) wraps the SecurityPosture
 * section so direct visitors land on a complete page rather than a
 * fragment.
 */
export default function SecurityPage() {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--wb-color-paper)",
        color: "var(--wb-color-aged-ink)",
        position: "relative",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <header
        style={{
          borderBottom: "1px solid var(--wb-color-rule-line)",
          padding: "20px 48px",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 24,
        }}
      >
        <Link
          href="/"
          data-testid="security-page-home"
          style={{
            textDecoration: "none",
            color: "inherit",
            display: "inline-flex",
            alignItems: "baseline",
            gap: 12,
          }}
        >
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: "var(--wb-text-md)",
              fontWeight: 600,
              letterSpacing: "-0.01em",
            }}
          >
            WormBase
          </span>
          <span
            className="wb-mono"
            style={{
              fontSize: "10px",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            vol. I · field notebook · wormbase.io
          </span>
        </Link>
        <span
          className="wb-mono"
          style={{
            fontSize: "10px",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          MMXXVI · plate vi · trust
        </span>
      </header>

      <main style={{ flex: 1 }}>
        <SecurityPosture />
        <ChannelCapabilityMatrix />
      </main>

      <footer
        style={{
          borderTop: "1px solid var(--wb-color-rule-line)",
          padding: "32px 48px 48px",
          textAlign: "center",
        }}
      >
        <span
          className="wb-mono"
          style={{
            fontSize: "11px",
            letterSpacing: "0.06em",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          specimen / lumbricus terrestris · agent / wormbase@v-demo · every
          answer carries its hash. · wormbase.io
        </span>
      </footer>
    </div>
  );
}
