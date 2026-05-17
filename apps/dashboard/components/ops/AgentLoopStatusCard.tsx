/**
 * AgentLoopStatusCard — running-state per agent loop (W2.A10).
 *
 * Three loops are surfaced by /api/v1/ops/health:
 *
 *   - worm-core         — the heartbeat + reactivity loops
 *   - channel-adapter   — wire ingress / egress (status derived from recent
 *                         `chat_received` / `channel_message` ledger activity)
 *   - projection-runner — periodic projection rebuild (status derived from
 *                         schema-migrations marker)
 *
 * Status palette mirrors PostgresHealthCard: ok=green, degraded=amber,
 * down=red, unknown=neutral. Each row shows the last-seen timestamp so
 * an operator can tell whether a loop is alive but quiet vs. genuinely
 * stuck.
 */

import type { AgentLoopStatus, HealthStatus } from "../../lib/ledger-client.types";

const STATUS_PALETTE: Record<HealthStatus, { fg: string; border: string }> = {
  ok: {
    fg: "var(--wb-color-botanical-green-deep)",
    border: "var(--wb-color-botanical-green-deep)",
  },
  degraded: { fg: "#a36a00", border: "#a36a00" },
  down: { fg: "#9c1f1f", border: "#9c1f1f" },
  unknown: {
    fg: "var(--wb-color-hash-gray)",
    border: "var(--wb-color-paper-edge)",
  },
};

function formatLastSeen(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const deltaSec = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (deltaSec < 60) return `${deltaSec}s ago`;
  if (deltaSec < 3600) return `${Math.round(deltaSec / 60)}m ago`;
  if (deltaSec < 86400) return `${Math.round(deltaSec / 3600)}h ago`;
  return `${Math.round(deltaSec / 86400)}d ago`;
}

export function AgentLoopStatusCard({
  loops,
}: {
  loops: AgentLoopStatus[];
}) {
  return (
    <section
      data-testid="ops-agent-loops"
      style={{
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper)",
        padding: "16px 20px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
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
        Agent loops
      </span>
      {loops.length === 0 ? (
        <p
          data-testid="ops-agent-loops-empty"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 13,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          No agent loops reporting yet.
        </p>
      ) : (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {loops.map((loop) => {
            const palette = STATUS_PALETTE[loop.status] ?? STATUS_PALETTE.unknown;
            return (
              <li
                key={loop.id}
                data-testid={`ops-agent-loops-row-${loop.id}`}
                data-status={loop.status}
                style={{
                  display: "grid",
                  gridTemplateColumns: "180px 110px 1fr 110px",
                  gap: 12,
                  alignItems: "baseline",
                  padding: "8px 10px",
                  borderLeft: `3px solid ${palette.border}`,
                  background: "var(--wb-color-paper-deep)",
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontSize: 14,
                    color: "var(--wb-color-aged-ink)",
                  }}
                >
                  {loop.label}
                </span>
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    textTransform: "uppercase",
                    letterSpacing: "0.1em",
                    color: palette.fg,
                  }}
                >
                  {loop.status}
                </span>
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontStyle: "italic",
                    fontSize: 13,
                    color: "var(--wb-color-hash-gray)",
                  }}
                >
                  {loop.message ?? "—"}
                </span>
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray)",
                    textAlign: "right",
                  }}
                >
                  {formatLastSeen(loop.lastSeenAt)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
