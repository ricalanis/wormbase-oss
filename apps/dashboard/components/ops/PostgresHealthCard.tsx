/**
 * PostgresHealthCard — surfaces the `SELECT 1` probe outcome for the ledger DB.
 *
 * Three states:
 *
 *   - status === "ok"        → green border, latency + version line
 *   - status === "degraded"  → amber border, message string
 *   - status === "down"      → RED banner, full-width, message verbatim
 *
 * Honest-red is the load-bearing requirement of W2.A10: when Postgres is
 * unreachable the operator must see it immediately, not buried in a stat
 * card. A `data-postgres-down` attribute is set on the wrapper so e2e
 * tests can assert the banner state without scraping styles.
 */

import type { PostgresHealth } from "../../lib/ledger-client.types";

const COLORS = {
  ok: {
    border: "var(--wb-color-botanical-green-deep)",
    bg: "var(--wb-color-paper)",
    fg: "var(--wb-color-aged-ink)",
  },
  degraded: {
    border: "#a36a00",
    bg: "#fff8e6",
    fg: "var(--wb-color-aged-ink)",
  },
  down: {
    border: "#9c1f1f",
    bg: "#fde7e7",
    fg: "#7a0e0e",
  },
  unknown: {
    border: "var(--wb-color-aged-ink)",
    bg: "var(--wb-color-paper)",
    fg: "var(--wb-color-aged-ink)",
  },
} as const;

export function PostgresHealthCard({ health }: { health: PostgresHealth }) {
  const palette = COLORS[health.status] ?? COLORS.unknown;
  const isDown = health.status === "down";
  return (
    <section
      data-testid="ops-postgres-health"
      data-status={health.status}
      data-postgres-down={isDown ? "true" : "false"}
      style={{
        border: `${isDown ? "2px" : "1px"} solid ${palette.border}`,
        background: palette.bg,
        color: palette.fg,
        padding: "16px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        Postgres · ledger DB
      </span>
      <h3
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 22,
          fontWeight: 500,
        }}
      >
        {isDown
          ? "Postgres is unreachable."
          : health.status === "degraded"
            ? "Postgres is degraded."
            : health.status === "ok"
              ? "Postgres is healthy."
              : "Postgres status unknown."}
      </h3>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          fontSize: 13,
          color: isDown ? "#7a0e0e" : "var(--wb-color-hash-gray)",
        }}
        data-testid="ops-postgres-message"
      >
        {health.message ??
          (health.status === "ok"
            ? "Last `SELECT 1` returned within the timeout."
            : "No status message yet.")}
      </p>
      <dl
        className="wb-mono"
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          columnGap: 12,
          rowGap: 2,
          margin: 0,
          fontSize: 11,
          color: "var(--wb-color-hash-gray)",
        }}
      >
        <dt>latency</dt>
        <dd style={{ margin: 0 }}>
          {health.latencyMs == null ? "—" : `${health.latencyMs.toFixed(1)} ms`}
        </dd>
        <dt>version</dt>
        <dd style={{ margin: 0, wordBreak: "break-all" }}>
          {health.version ?? "—"}
        </dd>
      </dl>
    </section>
  );
}
