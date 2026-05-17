"use client";

import Link from "next/link";
import { Button } from "@wormbase/design";
import { WizardProgress } from "../../../components/onboarding/WizardProgress";
import { PiiRulesPanel } from "../../../components/onboarding/PiiRulesPanel";
import { DmRoutingPanel } from "../../../components/onboarding/DmRoutingPanel";
import { OntologySeedsPanel } from "../../../components/onboarding/OntologySeedsPanel";
import { AddSourceForm } from "../../../components/onboarding/AddSourceForm";
import type {
  OntologySeed,
  PersonRow,
  PiiPattern,
} from "../../../lib/ledger-client.types";

export function Tier3Client({
  pii,
  people,
  seeds,
}: {
  pii: PiiPattern[];
  people: PersonRow[];
  seeds: OntologySeed[];
}) {
  return (
    <div
      style={{
        maxWidth: 980,
        margin: "0 auto",
        padding: "32px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 28,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Onboarding · Tier 3 · Policy
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 30,
            fontWeight: 600,
            letterSpacing: "-0.01em",
          }}
        >
          Power-user controls
        </h1>
      </header>

      <WizardProgress currentTier={3} completed={[1, 2]} />

      <Section title="PII patterns">
        <PiiRulesPanel patterns={pii} />
      </Section>

      <Section title="DM routing">
        <DmRoutingPanel people={people} />
      </Section>

      <Section title="Ontology seeds">
        <OntologySeedsPanel seeds={seeds} />
      </Section>

      <Section title="Add source · escape hatch">
        <p
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            margin: "0 0 12px",
          }}
        >
          The dashboard form is one of five worm-driven flows; the others are
          drop_and_profile, credential_offered_in_dm, mentioned_in_conversation,
          and kpi_gap_triggered. Use this only when you must.
        </p>
        <AddSourceForm />
      </Section>

      <Section title="Import existing catalog">
        <p
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            margin: "0 0 12px",
          }}
        >
          Already running dbt or a Snowflake schema with governance attached?
          Mirror it in one shot. The CatalogMirror layer materializes models,
          tags, and policy references as source rows under the bound domain;
          subsequent drift fires a Reactivity. Distinct from live-source
          connectors (which are streaming pipelines) — these are point-in-time
          metadata mirrors that the worm keeps in sync.
        </p>
        <div
          data-testid="import-catalog-picker"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
            gap: 10,
          }}
        >
          <ImportCatalogCard
            href="/onboarding/connect/dbt-manifest"
            label="dbt manifest"
            kind="dbt-manifest"
            status="preview"
            description={
              "Mirror an existing dbt project. Resolves the manifest.json " +
              "and materializes each model as a source row."
            }
            testId="import-catalog-card-dbt-manifest"
          />
          <ImportCatalogCard
            href="/onboarding/connect/snowflake-catalog"
            label="Snowflake catalog"
            kind="snowflake-catalog"
            status="preview"
            description={
              "Mirror an existing Snowflake schema. Reads " +
              "INFORMATION_SCHEMA + tag refs + policy graph."
            }
            testId="import-catalog-card-snowflake-catalog"
          />
        </div>
      </Section>

      <footer
        style={{
          display: "flex",
          justifyContent: "space-between",
          borderTop: "1px solid var(--wb-color-aged-ink)",
          paddingTop: 16,
        }}
      >
        <Link href="/onboarding/tier2" style={{ textDecoration: "none" }}>
          <Button variant="ghost">Back</Button>
        </Link>
        <Link href="/dashboard" style={{ textDecoration: "none" }}>
          <Button data-testid="finish">Finish</Button>
        </Link>
      </footer>
    </div>
  );
}

function ImportCatalogCard({
  href,
  label,
  kind,
  status,
  description,
  testId,
}: {
  href: string;
  label: string;
  kind: string;
  status: "production" | "preview" | "coming_soon";
  description: string;
  testId: string;
}) {
  const pillColor =
    status === "production"
      ? "var(--wb-color-botanical-green-deep)"
      : status === "preview"
        ? "var(--wb-color-sepia-warning-deep)"
        : "var(--wb-color-hash-gray)";
  const accentBorder =
    status === "production"
      ? "var(--wb-color-botanical-green)"
      : status === "preview"
        ? "var(--wb-color-sepia-warning-deep)"
        : "var(--wb-color-hash-gray)";
  return (
    <Link
      href={href}
      data-testid={testId}
      data-status={status}
      style={{
        textDecoration: "none",
        color: "inherit",
        textAlign: "left",
        border: "1px solid var(--wb-color-paper-edge)",
        borderLeft: `3px solid ${accentBorder}`,
        background: "var(--wb-color-paper)",
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        borderRadius: 0,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 16,
            fontWeight: 500,
          }}
        >
          {label}
        </span>
        <span
          className="wb-mono"
          data-testid={`${testId}-pill`}
          style={{
            fontSize: 9,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: pillColor,
            border: `1px solid ${pillColor}`,
            padding: "1px 6px",
            borderRadius: 0,
            whiteSpace: "nowrap",
          }}
        >
          {status === "coming_soon" ? "coming soon" : status}
        </span>
      </header>
      <span
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          color: "var(--wb-color-aged-ink)",
          lineHeight: 1.4,
        }}
      >
        {description}
      </span>
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          color: "var(--wb-color-aged-ink-soft)",
        }}
      >
        kind: {kind}
      </span>
    </Link>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h2
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: 20,
          fontWeight: 600,
          margin: 0,
          borderBottom: "3px double var(--wb-color-aged-ink)",
          paddingBottom: 6,
        }}
      >
        {title}
      </h2>
      {children}
    </section>
  );
}
