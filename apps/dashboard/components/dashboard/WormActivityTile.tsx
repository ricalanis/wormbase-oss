/**
 * WS5 S1 (+ Phase 3 Task 3A) — "Worm activity since you logged off" digest tile.
 *
 * The first daily moment of value. Counts the relevant ledger entries
 * since the current Person's last-seen timestamp (passed in as a prop
 * from the server component) and renders them as a row of family
 * counters. Each counter deep-links to the surface that owns the
 * corresponding artifact.
 *
 * Twelve families across two waves:
 *
 *   WS5 S1 (legacy four + three):
 *     - chat / files / kpis / decisions       → /activity?filter=<family>
 *     - sources / proactivity / artifacts     → /activity?filter=<family>
 *
 *   Phase 3 Task 3A (P2.1 validation gap, 2026-04-27):
 *     - drift                  → /sources?filter=drift  (lake-maintainer)
 *     - experiments            → /research              (research-worm)
 *     - recurring_questions    → /processes             (process-worm P10)
 *     - position_proposals     → /people/proposals      (identity-tracker)
 *     - topics                 → /topics                (process-extractor 2B)
 *
 * Honest empty state: when no recent activity, the tile reads
 *   "Nothing yet — the worm starts mining once your team starts chatting."
 *
 * Editorial chrome — square corners, wb-mono eyebrow + counters, serif
 * body. No Tailwind, no emojis.
 */

import Link from "next/link";
import type { WormActivityFamily, WormActivitySummary } from "../../lib/ledger-client";

interface FamilyDef {
  key: WormActivityFamily;
  /** Italic body label rendered next to the counter. */
  label: string;
  /** Override the default `/activity?filter=<key>` deep-link. Phase 3
   *  families route to the surface that owns the artifact (e.g. drift
   *  goes to /sources, position proposals go to /people/proposals). */
  href?: string;
}

const FAMILIES: ReadonlyArray<FamilyDef> = [
  { key: "chat", label: "messages" },
  { key: "files", label: "files dropped" },
  { key: "kpis", label: "KPI candidates" },
  { key: "decisions", label: "decisions" },
  { key: "sources", label: "sources proposed" },
  { key: "proactivity", label: "proactive offers" },
  { key: "artifacts", label: "gold artifacts" },
  // Phase 3 Task 3A — surface-targeted deep links.
  { key: "drift", label: "drift signals", href: "/sources?filter=drift" },
  { key: "experiments", label: "experiments resolved", href: "/research" },
  {
    key: "recurring_questions",
    label: "recurring questions",
    href: "/processes",
  },
  {
    key: "position_proposals",
    label: "position proposals pending",
    href: "/people/proposals",
  },
  { key: "topics", label: "topic clusters detected", href: "/topics" },
];

export interface WormActivityTileProps {
  summary: WormActivitySummary;
}

export function WormActivityTile({ summary }: WormActivityTileProps) {
  const sinceLabel = summary.sinceTs
    ? `since ${formatSince(summary.sinceTs)}`
    : "since install";

  if (summary.total === 0) {
    return (
      <section
        data-testid="worm-activity-tile"
        data-state="empty"
        style={tileStyle}
      >
        <div style={headerStyle}>
          <span style={eyebrowStyle} className="wb-mono">
            worm activity · {sinceLabel}
          </span>
          <h2 style={titleStyle}>Nothing yet.</h2>
        </div>
        <p style={bodyStyle}>
          The worm starts mining once your team starts chatting. Drop it into
          a channel via{" "}
          <Link href="/channels" style={inlineLinkStyle}>
            /channels
          </Link>{" "}
          to begin.
        </p>
      </section>
    );
  }

  return (
    <section
      data-testid="worm-activity-tile"
      data-state="populated"
      style={tileStyle}
    >
      <div style={headerStyle}>
        <span style={eyebrowStyle} className="wb-mono">
          worm activity · {sinceLabel}
        </span>
        <h2 style={titleStyle}>
          The worm did {summary.total} thing{summary.total === 1 ? "" : "s"}{" "}
          while you were away.
        </h2>
      </div>
      <ul
        data-testid="worm-activity-counts"
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 12,
        }}
      >
        {FAMILIES.map((f) => {
          const n = summary.byFamily[f.key];
          if (n === 0) return null;
          const href = f.href ?? `/activity?filter=${f.key}`;
          return (
            <li key={f.key} data-testid={`worm-activity-family-${f.key}`}>
              <Link
                href={href}
                data-testid={`worm-activity-link-${f.key}`}
                style={counterLinkStyle}
              >
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 28,
                    fontWeight: 500,
                    color: "var(--wb-color-aged-ink)",
                    letterSpacing: "-0.02em",
                  }}
                >
                  {n}
                </span>
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontStyle: "italic",
                    fontSize: 13,
                    color: "var(--wb-color-hash-gray)",
                  }}
                >
                  {f.label}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function formatSince(iso: string): string {
  // Compact ISO display ("2026-04-26 14:00 UTC") for editorial copy.
  // Avoids relying on the user's locale (server-render).
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return iso;
  const yyyy = d.getUTCFullYear();
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mi = String(d.getUTCMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}Z`;
}

const tileStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 16,
  padding: 20,
  border: "1px solid var(--wb-color-paper-edge)",
  background: "var(--wb-color-paper)",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const eyebrowStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const titleStyle: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 22,
  fontWeight: 500,
  letterSpacing: "-0.005em",
  color: "var(--wb-color-aged-ink)",
};

const bodyStyle: React.CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic",
  fontSize: 14,
  lineHeight: 1.55,
  color: "var(--wb-color-hash-gray)",
  maxWidth: 640,
};

const inlineLinkStyle: React.CSSProperties = {
  color: "var(--wb-color-botanical-green-deep)",
  textDecoration: "underline",
};

const counterLinkStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  padding: "12px 14px",
  border: "1px solid var(--wb-color-paper-edge)",
  background: "var(--wb-color-paper-deep)",
  textDecoration: "none",
  cursor: "pointer",
};
