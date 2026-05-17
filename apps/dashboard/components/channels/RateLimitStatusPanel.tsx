/**
 * RateLimitStatusPanel — W3-B (2026-05-07).
 *
 * Below D3's SyncHistoryPanel on /channels/[id], this surface shows the
 * WhatsApp send rate-limit status for the current tenant + bot:
 *
 *   1. Token-bucket fill indicator. Today the projection does NOT track
 *      live in-process bucket state (the bucket lives in
 *      ``packages/channel-adapters/src/wormbase_channel_adapters/whatsapp_rate_limit.py``
 *      module-globals, not in the ledger), so we surface an honest
 *      derived state: "5 / 5 tokens (idle, not throttling)" when no
 *      recent throttle event lands, "throttle in progress — 0 / 5
 *      tokens" while a persistent-throttle session is open. Capability
 *      honesty per CLAUDE.md §3 — we do not fabricate a live fill bar.
 *
 *   2. Recent backoff events list — the most-recent
 *      ``policy:whatsapp_rate_limit`` ``policy_applied`` execute entries
 *      for this tenant (~10 entries). One row per persistent-throttle
 *      audit emission, with timestamp + rule + rationale + scope.
 *
 *   3. Configured rate disclosure — "Configured rate: 5 messages /
 *      minute (default)". The actual env override
 *      (``WORMBASE_WHATSAPP_RATE_PER_MIN_<TENANT>``) lives server-side;
 *      we surface the default and document the env knob in the hint
 *      copy. No fabricated tenant value.
 *
 * Renders only when ``platform === "whatsapp"``. Other platforms have
 * different rate-limit stories (Slack: rich-headers from Slack API;
 * Discord: stub) and are out of scope for W3-B per plan §6.
 *
 * Reads only ledger projections per CLAUDE.md §1; visible empty state
 * per §9 ("No throttling events recorded — the bot has stayed under the
 * rate limit."). Read-only, no admin gate.
 */
import { getPolicyAppliedEvents } from "../../lib/ledger-client";
import type { PolicyAppliedEvent } from "../../lib/ledger-client.types";
import type { PlatformSlug } from "../../lib/platform-status";

const POLICY_NAME = "policy:whatsapp_rate_limit";
const DEFAULT_RATE_PER_MIN = 5;
const RECENT_EVENTS_LIMIT = 10;

interface Props {
  companyId: string;
  channelId: string;
  platform: PlatformSlug | string | null | undefined;
}

export async function RateLimitStatusPanel({
  companyId,
  channelId,
  platform,
}: Props) {
  // Narrowly-scoped to WhatsApp today (W3-B). Other platforms render
  // nothing — they will get their own rate-limit panels when their
  // adapters wire one.
  if (platform !== "whatsapp") return null;

  const events = await getPolicyAppliedEvents(companyId, POLICY_NAME, {
    limit: RECENT_EVENTS_LIMIT,
  });

  // Derive "throttle session active" from event recency: if the most
  // recent emission landed in the last 5 minutes, we surface "throttle
  // in progress" — otherwise we render the idle state. The rate
  // limiter's session-clear semantics live in the Python module; the
  // dashboard projection doesn't directly observe session boundaries.
  const mostRecentTs = events.length > 0 ? events[0].ts : null;
  const throttleActive = isWithin5Minutes(mostRecentTs);
  const tokensAvailable = throttleActive ? 0 : DEFAULT_RATE_PER_MIN;

  return (
    <section
      aria-label="rate limit status"
      data-testid="rate-limit-status-section"
      data-channel-id={channelId}
      data-throttle-active={throttleActive ? "true" : "false"}
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
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
        whatsapp rate limit · {events.length}{" "}
        event{events.length === 1 ? "" : "s"}
      </span>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
          fontSize: 13,
        }}
      >
        Token-bucket throttle on WhatsApp send. Configured rate{" "}
        <span className="wb-mono">{DEFAULT_RATE_PER_MIN} / min</span> by
        default; override per tenant via{" "}
        <span className="wb-mono">
          WORMBASE_WHATSAPP_RATE_PER_MIN_&lt;TENANT&gt;
        </span>
        .
      </p>
      <FillBar
        tokensAvailable={tokensAvailable}
        capacity={DEFAULT_RATE_PER_MIN}
        throttleActive={throttleActive}
      />
      <BackoffEventsList events={events} />
    </section>
  );
}

function FillBar({
  tokensAvailable,
  capacity,
  throttleActive,
}: {
  tokensAvailable: number;
  capacity: number;
  throttleActive: boolean;
}) {
  const ratio = capacity > 0 ? tokensAvailable / capacity : 0;
  const widthPct = Math.max(0, Math.min(1, ratio)) * 100;
  const stateLabel = throttleActive
    ? "throttle in progress"
    : "idle, not throttling";
  return (
    <div
      data-testid="rate-limit-fill-bar"
      data-tokens={tokensAvailable}
      data-capacity={capacity}
      style={{
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper)",
        padding: 10,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          className="wb-mono"
          data-testid="rate-limit-fill-label"
          style={{
            fontSize: 12,
            color: "var(--wb-color-aged-ink)",
            letterSpacing: "0.04em",
          }}
        >
          {tokensAvailable} / {capacity} tokens available
        </span>
        <span
          className="wb-mono"
          data-testid="rate-limit-fill-state"
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: throttleActive
              ? "var(--wb-color-sepia-warning-deep)"
              : "var(--wb-color-botanical-green-deep)",
          }}
        >
          {stateLabel}
        </span>
      </div>
      <div
        aria-hidden
        style={{
          height: 6,
          background: "var(--wb-color-paper-deep)",
          border: "1px solid var(--wb-color-paper-edge)",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div
          data-testid="rate-limit-fill-bar-fill"
          style={{
            position: "absolute",
            inset: 0,
            width: `${widthPct}%`,
            background: throttleActive
              ? "var(--wb-color-sepia-warning-deep)"
              : "var(--wb-color-botanical-green-deep)",
            transition: "width 0.3s ease",
          }}
        />
      </div>
    </div>
  );
}

function BackoffEventsList({ events }: { events: PolicyAppliedEvent[] }) {
  if (events.length === 0) {
    return (
      <section
        data-testid="rate-limit-events-empty"
        style={{
          border: "1px dashed var(--wb-color-paper-edge)",
          padding: 18,
          fontFamily: "var(--wb-font-serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        No throttling events recorded — the bot has stayed under the rate
        limit.
      </section>
    );
  }
  return (
    <section
      data-testid="rate-limit-events-list"
      style={{
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper)",
      }}
    >
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontFamily: "var(--wb-font-serif)",
        }}
      >
        <thead>
          <tr
            style={{
              borderBottom: "1px solid var(--wb-color-aged-ink)",
              fontFamily: "var(--wb-font-mono)",
              textTransform: "uppercase",
              fontSize: 10,
              letterSpacing: "0.12em",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            <th style={cellStyle("left", true)}>timestamp</th>
            <th style={cellStyle("left", true)}>rule</th>
            <th style={cellStyle("left", true)}>scope</th>
            <th style={cellStyle("left", true)}>rationale</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr
              key={e.hash || `${e.ts}-${e.rule}`}
              data-testid={`rate-limit-event-row-${e.hash || e.ts}`}
              data-rule={e.rule}
              style={{
                borderBottom: "1px solid var(--wb-color-paper-edge)",
              }}
            >
              <td style={cellStyle("left")}>
                <span className="wb-mono" style={{ fontSize: 12 }}>
                  {formatTs(e.ts)}
                </span>
              </td>
              <td style={cellStyle("left")}>
                <span className="wb-mono" style={{ fontSize: 12 }}>
                  {e.rule || "—"}
                </span>
              </td>
              <td style={cellStyle("left")}>
                <span className="wb-mono" style={{ fontSize: 11 }}>
                  {scopeLabel(e)}
                </span>
              </td>
              <td style={cellStyle("left")}>
                <span style={{ fontSize: 13 }}>{e.rationale || "—"}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function scopeLabel(e: PolicyAppliedEvent): string {
  if (e.botPhone) return e.botPhone;
  const scope = e.appliesTo["scope"];
  if (typeof scope === "string") return scope;
  return "—";
}

function formatTs(iso: string): string {
  return iso.replace("T", " ").replace(/\.\d+Z$/, "Z").slice(0, 20);
}

function cellStyle(
  align: "left" | "right" | "center",
  header = false,
): React.CSSProperties {
  return {
    textAlign: align,
    padding: header ? "8px 12px" : "10px 12px",
    verticalAlign: "middle",
    whiteSpace: "nowrap",
  };
}

function isWithin5Minutes(iso: string | null): boolean {
  if (!iso) return false;
  const eventMs = Date.parse(iso);
  if (Number.isNaN(eventMs)) return false;
  const ageMs = Date.now() - eventMs;
  return ageMs >= 0 && ageMs <= 5 * 60 * 1000;
}
