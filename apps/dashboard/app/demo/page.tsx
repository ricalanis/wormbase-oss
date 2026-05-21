import Link from "next/link";
import { DemoDashboard } from "./DemoDashboard";

export const metadata = {
  title: "WormBase · Demo dashboard",
  description:
    "WormBase demo dashboard with mock data — conversation insights, source/lake insights, agent-loop tending, and compounding-knowledge artifacts. For design-partner walkthroughs.",
};

export default function DemoPage() {
  return (
    <div
      style={{
        minHeight: "100vh",
        background: "var(--wb-color-paper)",
        color: "var(--wb-color-aged-ink)",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <header
        style={{
          borderBottom: "1px solid var(--wb-color-rule-line)",
          padding: "18px 40px",
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 24,
          background: "var(--wb-color-paper-deep)",
        }}
      >
        <Link
          href="/"
          style={{
            textDecoration: "none",
            color: "inherit",
            display: "inline-flex",
            alignItems: "baseline",
            gap: 14,
            fontFamily: "var(--wb-font-mono)",
            fontWeight: 600,
            fontSize: 15,
            letterSpacing: "-0.005em",
          }}
        >
          <span
            aria-hidden
            style={{
              width: 12,
              height: 12,
              background: "var(--wb-color-botanical-green)",
              transform: "rotate(45deg)",
              display: "inline-block",
              position: "relative",
              top: 2,
            }}
          />
          wormbase
          <span
            style={{
              color: "var(--wb-color-hash-gray)",
              fontWeight: 400,
              fontSize: 11,
              letterSpacing: "0.16em",
              textTransform: "uppercase",
              marginLeft: 12,
            }}
          >
            demo dashboard · democorp tenant
          </span>
        </Link>
        <div style={{ display: "inline-flex", gap: 12, alignItems: "center" }}>
          <span
            style={{
              fontFamily: "var(--wb-font-mono)",
              fontSize: 10,
              letterSpacing: "0.22em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning)",
              border: "1px solid var(--wb-color-sepia-warning)",
              padding: "4px 10px",
              borderRadius: 999,
              background: "var(--wb-color-sepia-warning-soft)",
            }}
          >
            demo · mock data
          </span>
          <Link
            href="/"
            style={{
              fontFamily: "var(--wb-font-mono)",
              fontSize: 11,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-aged-ink-soft)",
              textDecoration: "none",
              borderBottom: "1px solid var(--wb-color-rule-line)",
            }}
          >
            ← landing
          </Link>
        </div>
      </header>

      <main
        style={{
          flex: 1,
          padding: "32px 40px 64px",
          display: "flex",
          flexDirection: "column",
          gap: 24,
          maxWidth: 1400,
          width: "100%",
          margin: "0 auto",
        }}
      >
        <DemoDashboard />
      </main>

      <footer
        style={{
          borderTop: "1px solid var(--wb-color-rule-line)",
          padding: "16px 40px",
          fontFamily: "var(--wb-font-mono)",
          fontSize: 11,
          letterSpacing: "0.1em",
          color: "var(--wb-color-hash-gray)",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>
          WormBase · /demo · mock data &nbsp;·&nbsp; the dashboard you'll see is
          the one your install will populate
        </span>
        <span>ledger tip · seq 184,221 · hash 0x9a4f…c12e</span>
      </footer>
    </div>
  );
}
