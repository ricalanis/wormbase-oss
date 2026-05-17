import "../src/styles.css";
import {
  Button,
  Card,
  Gauge,
  Input,
  LedgerEntry,
  Page,
  Receipt,
  Select,
} from "../src/components";

export default {
  title: "Overview / Field Notebook",
};

/**
 * Systematic visual review: every primitive + a preview of each page
 * surface. This index is the "design system doc" the rest of the project
 * references.
 */
export const System = () => (
  <Page subtitle="visual review index · Field Notebook">
    <section style={{ display: "flex", flexDirection: "column", gap: 32 }}>
      <Masthead />

      <SectionRow title="Palette" hint="paper · aged-ink · botanical · sepia · hash-gray">
        <PaletteChip name="paper" value="var(--wb-color-paper)" />
        <PaletteChip name="aged ink" value="var(--wb-color-aged-ink)" light />
        <PaletteChip
          name="botanical"
          value="var(--wb-color-botanical-green)"
          light
        />
        <PaletteChip
          name="sepia"
          value="var(--wb-color-sepia-warning)"
          light
        />
        <PaletteChip name="hash gray" value="var(--wb-color-hash-gray)" light />
        <PaletteChip name="rule line" value="var(--wb-color-rule-line)" />
      </SectionRow>

      <SectionRow title="Typography" hint="serif + mono — mono marks ledger">
        <div
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-xl)",
          }}
        >
          Institutional AI for your company&rsquo;s data and processes.
        </div>
        <div
          className="wb-mono"
          style={{
            fontSize: "var(--wb-text-sm)",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          hash / a3f9c2 · source / subscriptions × accounts · owner / ricardo
        </div>
      </SectionRow>

      <SectionRow title="Buttons" hint="≤2px corners, serif label, no gradient">
        <Button>Create demo workspace</Button>
        <Button variant="secondary">Back</Button>
        <Button variant="ghost">Skip</Button>
        <Button variant="danger">Block (PII)</Button>
      </SectionRow>

      <SectionRow title="Inputs & Selects" hint="underlined baseline; rectangular select">
        <div style={{ width: 260 }}>
          <Input label="Company name" defaultValue="DemoCorp" />
        </div>
        <div style={{ width: 260 }}>
          <Select
            label="KPI tree template"
            options={[
              { value: "saas", label: "SaaS" },
              { value: "marketplace", label: "Marketplace" },
              { value: "fintech", label: "Fintech" },
            ]}
          />
        </div>
      </SectionRow>

      <SectionRow title="Card + Receipt" hint="the signature unit">
        <div style={{ width: 400 }}>
          <Card eyebrow="PROJECTION · answer" title="Churn last month">
            <p style={{ margin: 0, fontFamily: "var(--wb-font-serif)" }}>
              <strong>4.2%</strong> overall. SMB 6.1 · Mid-market 3.0 ·
              Enterprise 1.4.
            </p>
            <div style={{ marginTop: 16 }}>
              <Receipt
                hash="a3f9c2"
                source="subscriptions × accounts"
                owner="ricardo"
                classification="internal"
                compact
              />
            </div>
          </Card>
        </div>
      </SectionRow>

      <SectionRow title="Gauge" hint="breathing ±0.5% · 3s cycle · botanical arc">
        <Gauge label="Ontology" value={34} staggerIndex={0} />
        <Gauge label="Conversational" value={65} staggerIndex={1} />
        <Gauge label="Reproducibility" value={100} instant />
      </SectionRow>

      <SectionRow title="Ledger entries" hint="mono stream, expandable detail">
        <div style={{ width: 780 }}>
          <LedgerEntry
            timestamp="08:14:02"
            entryType="propose"
            hash="a3f9c2"
            summary="Proposed source: subscriptions.csv (1,234 rows)"
            actor="worm"
          />
          <LedgerEntry
            timestamp="08:14:07"
            entryType="execute"
            hash="b41f88"
            summary="Downloaded and profiled subscriptions.csv"
            actor="worm"
            detail={`{"rows": 1234, "columns": 5, "missing_pct": {"mrr": 0.02}}`}
          />
          <LedgerEntry
            timestamp="08:16:44"
            entryType="gate_fired"
            hash="dead01"
            summary="pii_redaction gate masked column email"
            actor="gate"
          />
        </div>
      </SectionRow>

      <SectionRow title="Page surfaces" hint="landing · onboarding · dashboard">
        <PageLink href="/" label="Landing" />
        <PageLink href="/onboarding" label="Onboarding · tier 1" />
        <PageLink href="/dashboard" label="Dashboard · ramp gauges" />
      </SectionRow>
    </section>
  </Page>
);

function Masthead() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        borderTop: "1px solid var(--wb-color-aged-ink)",
        borderBottom: "1px solid var(--wb-color-aged-ink)",
        padding: "20px 0",
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 11,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        Phase 1A · visual review · v-demo
      </span>
      <h1
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: "var(--wb-text-2xl)",
          fontWeight: 600,
          letterSpacing: "-0.015em",
        }}
      >
        The Field Notebook.
      </h1>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
          maxWidth: 640,
        }}
      >
        Darwin's journals, not Bloomberg terminal. Scientific publishing meets
        living subject: brutalist content discipline wrapped in organic warmth.
      </p>
    </div>
  );
}

function SectionRow({
  title,
  hint,
  children,
}: {
  title: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <section
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 14,
        borderBottom: "1px solid var(--wb-color-rule-line)",
        paddingBottom: 24,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {hint}
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-md)",
            fontWeight: 600,
          }}
        >
          {title}
        </h2>
      </header>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 16,
          alignItems: "center",
        }}
      >
        {children}
      </div>
    </section>
  );
}

function PaletteChip({
  name,
  value,
  light = false,
}: {
  name: string;
  value: string;
  light?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        width: 120,
      }}
    >
      <div
        style={{
          height: 64,
          background: value,
          border: "1px solid var(--wb-color-rule-line)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          color: light ? "var(--wb-color-paper)" : "var(--wb-color-aged-ink)",
        }}
      >
        {name}
      </div>
      <span
        className="wb-mono"
        style={{ fontSize: 10, color: "var(--wb-color-hash-gray)" }}
      >
        {value}
      </span>
    </div>
  );
}

function PageLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={`http://localhost:3000${href}`}
      target="_blank"
      rel="noreferrer"
      style={{
        textDecoration: "none",
        color: "var(--wb-color-aged-ink)",
        fontFamily: "var(--wb-font-serif)",
        fontSize: "var(--wb-text-sm)",
        padding: "10px 18px",
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper)",
      }}
    >
      {label} →
    </a>
  );
}
