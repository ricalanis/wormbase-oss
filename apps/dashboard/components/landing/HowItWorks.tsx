/**
 * HowItWorks — the canonical 5-beat product arc.
 *
 * Beats from `docs/superpowers/specs/2026-04-26-wormbase-product-arc.md`:
 *   1. CONNECT             Install. Worm joins ANY chat platform.
 *   2. GROW THE LAKE       Medallion bronze→silver→gold across six flows.
 *   3. BUILD CONCURRENTLY  KPIs, governance, processes — at the same time.
 *   4. PRODUCE + CONVERSE  Data products + text/voice receipts.
 *   5. SELF-IMPROVE        Karpathy autoresearch, parameterized per Person.
 *
 * Field Notebook treatment: numbered plates, serif headlines, mono kickers,
 * one taxonomic sentence per beat. No icons. No emoji. The text is the art.
 */
import type { CSSProperties } from "react";

interface Beat {
  /** Slug used for testid (lowercase first word). */
  slug: string;
  /** Roman numeral for the field-notebook plate effect. */
  numeral: string;
  /** Decimal step number, used by tests. */
  n: string;
  /** Headline (uppercase serif). */
  title: string;
  /** Subtitle in italic serif. */
  subtitle: string;
  /** Body paragraph. */
  body: string;
  /** Hash-receipt-style mono coda. */
  receipt: string;
}

const BEATS: Beat[] = [
  {
    slug: "connect",
    numeral: "i",
    n: "1",
    title: "CONNECT",
    subtitle: "Install. The worm joins any chat platform.",
    body:
      "One tap connects Slack, Discord, Teams, WhatsApp — anywhere OpenClaw reaches. The installer becomes admin and the first Person; the rest of your team is auto-discovered from the wire. Speak is gated. Listen-for-ingest is always on.",
    receipt:
      "ledger · install · person/installer · grants(installer + admin + domain.owner)",
  },
  {
    slug: "grow",
    numeral: "ii",
    n: "2",
    title: "GROW THE LAKE",
    subtitle: "Medallion: bronze → silver → gold.",
    body:
      "Files dropped, credentials offered, sources mentioned in chatter — every byte flows through one cascade. Bronze captures the hash-stable bytes. Silver applies inferred schema and governance. Gold lands KPI-ready aggregates. Replay the ledger to land on the same hashes.",
    receipt:
      "cascade · bronze 200ms · silver 1.5s · gold 4s · every layer hash-receipted",
  },
  {
    slug: "build",
    numeral: "iii",
    n: "3",
    title: "BUILD CONCURRENTLY",
    subtitle: "KPIs, governance, processes — together, not in phases.",
    body:
      "The KPI tree, the governance graph, and the process map grow from the same substrate. The worm proposes; admins confirm. Decisions extracted from chat. System maps drawn from handoffs. Recurring questions surfaced as automation candidates.",
    receipt:
      "graph · kpis · domains · processes · all materialized from the ledger",
  },
  {
    slug: "produce",
    numeral: "iv",
    n: "4",
    title: "PRODUCE + CONVERSE",
    subtitle: "Data products. Text and voice. Receipts under every answer.",
    body:
      "The worm publishes dashboards, decision logs, lineage trails, and improvement candidates as ledger artifacts. Ask in Slack or pick up the phone — every reply lands with a hash, a source list, and a click-through trail to the bronze bytes that produced it.",
    receipt:
      "data_product_published · text · voice · hash a8989ece · source receipt visible",
  },
  {
    slug: "self-improve",
    numeral: "v",
    n: "5",
    title: "SELF-IMPROVE PER USER",
    subtitle: "An analyst seat that gets sharper every night.",
    body:
      "Karpathy-style autoresearch, parameterized by each Person × position. The CFO sees revenue-runway experiments; the data engineer sees pipeline-latency experiments. Wins keep, losses discard, every cycle is a ledger receipt. The worm scales by adding Persons, not config.",
    receipt:
      "experiment · proposed → executed → verified → resolved · wins kept, losses discarded",
  },
];

export function HowItWorks() {
  return (
    <section
      data-testid="how-it-works-section"
      aria-labelledby="how-it-works-headline"
      style={sectionStyle}
    >
      <div style={innerStyle}>
        <p className="wb-mono" style={eyebrowStyle}>
          plate iv · the arc
        </p>
        <h2 id="how-it-works-headline" style={headlineStyle}>
          Five beats. One ledger. Every step a receipt.
        </h2>
        <p style={subheadStyle}>
          The product arc reads like a journal entry — chronological, dated,
          attributable. Replay the ledger to any timestamp and you land on the
          same state, the same hashes, the same answers.
        </p>

        <ol style={beatsStyle}>
          {BEATS.map((beat) => (
            <li
              key={beat.slug}
              data-testid={`how-it-works-beat-${beat.slug}`}
              style={beatItemStyle}
            >
              <div style={beatHeaderStyle}>
                <span
                  data-testid={`how-it-works-step-${beat.n}`}
                  className="wb-mono"
                  style={numeralStyle}
                  aria-hidden="false"
                >
                  step {beat.n} · plate {beat.numeral}
                </span>
                <h3 style={beatTitleStyle}>{beat.title}</h3>
                <p style={beatSubtitleStyle}>{beat.subtitle}</p>
              </div>
              <p style={beatBodyStyle}>{beat.body}</p>
              <p className="wb-mono" style={beatReceiptStyle}>
                ↳ {beat.receipt}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

const sectionStyle: CSSProperties = {
  width: "100%",
  padding: "96px 24px",
  background: "var(--wb-color-paper)",
};

const innerStyle: CSSProperties = {
  maxWidth: 980,
  margin: "0 auto",
  display: "flex",
  flexDirection: "column",
  gap: 24,
};

const eyebrowStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  letterSpacing: "0.24em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const headlineStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "clamp(28px, 3.4vw, 40px)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
  letterSpacing: "-0.012em",
  lineHeight: 1.15,
  maxWidth: 820,
};

const subheadStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-md)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.55,
  maxWidth: 720,
};

const beatsStyle: CSSProperties = {
  listStyle: "none",
  margin: "32px 0 0",
  padding: 0,
  display: "flex",
  flexDirection: "column",
  borderTop: "1px solid var(--wb-color-rule-line)",
};

const beatItemStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(160px, 220px) 1fr",
  gap: 32,
  padding: "28px 0",
  borderBottom: "1px solid var(--wb-color-rule-line)",
};

const beatHeaderStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const numeralStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const beatTitleStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-lg)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
  letterSpacing: "0.04em",
};

const beatSubtitleStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  fontSize: "var(--wb-text-sm)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.5,
};

const beatBodyStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-base)",
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.6,
};

const beatReceiptStyle: CSSProperties = {
  margin: "8px 0 0",
  fontSize: 11,
  letterSpacing: "0.04em",
  color: "var(--wb-color-botanical-green-deep)",
  gridColumn: "2",
};
