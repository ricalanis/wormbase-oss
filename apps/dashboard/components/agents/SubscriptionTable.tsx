/**
 * SubscriptionTable — list of active subscriptions for an agent
 * (v2.A Task 7).
 *
 * Pure-presentational. Shows the filter summary as chips (kinds /
 * domains / agent_id_ref / payload pairs), the transport, the created-at
 * timestamp, the 24h delivery count, and a revoke action. Click-through
 * on the subscription_id (shortened) opens a future detail page; that
 * detail view is deferred to a follow-up — for now the chip is just
 * copy-to-clipboard friendly.
 *
 * Empty state is handled by the page itself. This component renders only
 * the table.
 */
"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";

import type { Subscription } from "../../lib/agent-subscriptions";
import type { RevokeSubscriptionResult } from "../../app/(app)/people/agents/[id]/subscriptions/actions";

type RevokeAction = (
  agentId: string,
  subscriptionId: string,
) => Promise<RevokeSubscriptionResult>;

export interface SubscriptionTableProps {
  agentId: string;
  rows: Subscription[];
  revokeAction: RevokeAction;
  /** Caller can override; defaults to alert() — tests pass a spy. */
  onRevokeFailed?: (msg: string) => void;
}

const TH_STYLE: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 12px",
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 11,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray, #6b6256)",
  borderBottom: "1px solid var(--wb-color-edge, rgba(0,0,0,0.12))",
  whiteSpace: "nowrap",
};

const TD_STYLE: React.CSSProperties = {
  padding: "10px 12px",
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 14,
  borderBottom: "1px solid var(--wb-color-edge, rgba(0,0,0,0.06))",
  verticalAlign: "top",
};

const CHIP_STYLE: React.CSSProperties = {
  display: "inline-block",
  margin: "2px 4px 2px 0",
  padding: "2px 8px",
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 10,
  letterSpacing: "0.04em",
  border: "1px solid var(--wb-color-edge, rgba(0,0,0,0.18))",
  background: "var(--wb-color-paper, #f6f1e7)",
};

const REVOKE_STYLE: React.CSSProperties = {
  padding: "4px 10px",
  borderRadius: 0,
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 11,
  border: "1px solid var(--wb-color-error, #b03a2e)",
  background: "transparent",
  color: "var(--wb-color-error, #b03a2e)",
  cursor: "pointer",
};

function fmtTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().replace("T", " ").slice(0, 16);
  } catch {
    return iso;
  }
}

function FilterChips({ sub }: { sub: Subscription }): JSX.Element {
  const { kinds, domains, agentIdRef, payloadPathEq } = sub.filter;
  if (
    kinds.length === 0 &&
    domains.length === 0 &&
    !agentIdRef &&
    payloadPathEq.length === 0
  ) {
    return (
      <span
        style={{
          fontFamily: "var(--wb-font-serif, Georgia, serif)",
          fontStyle: "italic",
          color: "var(--wb-color-hash-gray, #6b6256)",
          fontSize: 12,
        }}
      >
        (wildcard)
      </span>
    );
  }
  return (
    <div>
      {kinds.map((k) => (
        <span key={`k-${k}`} style={CHIP_STYLE} data-testid={`sub-chip-kind-${k}`}>
          kind:{k}
        </span>
      ))}
      {domains.map((d) => (
        <span key={`d-${d}`} style={CHIP_STYLE} data-testid={`sub-chip-domain-${d}`}>
          domain:{d.slice(0, 8)}…
        </span>
      ))}
      {agentIdRef ? (
        <span style={CHIP_STYLE} data-testid="sub-chip-agent-id-ref">
          agent_id_ref:{agentIdRef.slice(0, 8)}…
        </span>
      ) : null}
      {payloadPathEq.map(([path, value], i) => (
        <span
          key={`p-${i}`}
          style={CHIP_STYLE}
          data-testid={`sub-chip-payload-${i}`}
        >
          {path}={value}
        </span>
      ))}
    </div>
  );
}

export function SubscriptionTable({
  agentId,
  rows,
  revokeAction,
  onRevokeFailed,
}: SubscriptionTableProps): JSX.Element {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function revoke(subscriptionId: string): void {
    if (typeof window !== "undefined") {
      const ok = window.confirm(
        `Revoke subscription ${subscriptionId.slice(0, 8)}…? This writes an ` +
          `emit_agent_subscription_revoked ledger entry and cannot be undone ` +
          `(re-subscribe by creating a new one).`,
      );
      if (!ok) return;
    }
    startTransition(async () => {
      const result = await revokeAction(agentId, subscriptionId);
      if (result.ok) {
        router.refresh();
      } else {
        const msg = result.error ?? "revoke failed";
        if (onRevokeFailed) {
          onRevokeFailed(msg);
        } else if (typeof window !== "undefined") {
          window.alert(`Revoke failed: ${msg}`);
        }
      }
    });
  }

  return (
    <div data-testid="subscriptions-table" style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        <thead>
          <tr>
            <th scope="col" style={TH_STYLE}>
              Subscription
            </th>
            <th scope="col" style={TH_STYLE}>
              Filter
            </th>
            <th scope="col" style={TH_STYLE}>
              Transport
            </th>
            <th scope="col" style={TH_STYLE}>
              Created
            </th>
            <th scope="col" style={{ ...TH_STYLE, textAlign: "right" }}>
              24h
            </th>
            <th scope="col" style={TH_STYLE} aria-label="actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.subscriptionId}
              data-testid={`subscription-row-${row.subscriptionId}`}
            >
              <td style={TD_STYLE}>
                <div
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 12,
                  }}
                >
                  {row.subscriptionId.slice(0, 12)}…
                </div>
                {row.description ? (
                  <div
                    style={{
                      fontFamily: "var(--wb-font-serif, Georgia, serif)",
                      fontStyle: "italic",
                      fontSize: 11,
                      color: "var(--wb-color-hash-gray, #6b6256)",
                      marginTop: 2,
                    }}
                  >
                    {row.description}
                  </div>
                ) : null}
              </td>
              <td style={TD_STYLE}>
                <FilterChips sub={row} />
              </td>
              <td style={TD_STYLE}>
                <span
                  data-testid={`subscription-transport-${row.transport}`}
                  style={{
                    fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    letterSpacing: "0.04em",
                    textTransform: "uppercase",
                    padding: "2px 8px",
                    border: "1px solid var(--wb-color-edge, rgba(0,0,0,0.12))",
                  }}
                >
                  {row.transport}
                </span>
                {row.webhookUrl ? (
                  <div
                    style={{
                      fontFamily:
                        "var(--wb-font-mono, ui-monospace, monospace)",
                      fontSize: 10,
                      color: "var(--wb-color-hash-gray, #6b6256)",
                      marginTop: 2,
                      maxWidth: 220,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={row.webhookUrl}
                  >
                    {row.webhookUrl}
                  </div>
                ) : null}
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                  whiteSpace: "nowrap",
                }}
              >
                {fmtTimestamp(row.createdAt)}
              </td>
              <td style={{ ...TD_STYLE, textAlign: "right" }}>
                {row.deliveryCount24h}
              </td>
              <td style={{ ...TD_STYLE, textAlign: "right" }}>
                <button
                  type="button"
                  data-testid={`subscription-revoke-${row.subscriptionId}`}
                  onClick={() => revoke(row.subscriptionId)}
                  disabled={pending}
                  style={{
                    ...REVOKE_STYLE,
                    opacity: pending ? 0.6 : 1,
                    cursor: pending ? "default" : "pointer",
                  }}
                >
                  Revoke
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * DeliveryTable — Recent Deliveries panel.
 */
export interface DeliveryTableProps {
  rows: import("../../lib/agent-subscriptions").Delivery[];
}

export function DeliveryTable({ rows }: DeliveryTableProps): JSX.Element {
  return (
    <div data-testid="deliveries-table" style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        <thead>
          <tr>
            <th scope="col" style={TH_STYLE}>
              Subscription
            </th>
            <th scope="col" style={TH_STYLE}>
              Triggering entry
            </th>
            <th scope="col" style={TH_STYLE}>
              Transport
            </th>
            <th scope="col" style={TH_STYLE}>
              Status
            </th>
            <th scope="col" style={{ ...TH_STYLE, textAlign: "right" }}>
              Latency
            </th>
            <th scope="col" style={TH_STYLE}>
              At
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={`${row.seq}`}
              data-testid={`delivery-row-${row.seq}`}
            >
              <td
                style={{
                  ...TD_STYLE,
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 11,
                }}
              >
                {row.subscriptionId.slice(0, 12)}…
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                }}
              >
                #{row.triggeringEntrySeq}
                <div
                  style={{
                    fontSize: 10,
                    color: "var(--wb-color-hash-gray, #6b6256)",
                  }}
                >
                  {row.triggeringEntryKind}
                </div>
              </td>
              <td style={TD_STYLE}>
                <span
                  style={{
                    fontFamily:
                      "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 10,
                    letterSpacing: "0.04em",
                    textTransform: "uppercase",
                    padding: "1px 6px",
                    border: "1px solid var(--wb-color-edge, rgba(0,0,0,0.12))",
                  }}
                >
                  {row.transportUsed}
                </span>
              </td>
              <td style={TD_STYLE}>
                <span
                  data-testid={`delivery-status-${row.deliveryStatus}`}
                  style={{
                    fontFamily:
                      "var(--wb-font-mono, ui-monospace, monospace)",
                    fontSize: 11,
                    letterSpacing: "0.04em",
                    textTransform: "uppercase",
                    color:
                      row.deliveryStatus === "delivered"
                        ? "var(--wb-color-botanical, #2d6a4f)"
                        : row.deliveryStatus === "failed"
                          ? "var(--wb-color-error, #b03a2e)"
                          : "var(--wb-color-hash-gray, #6b6256)",
                  }}
                >
                  {row.deliveryStatus}
                </span>
                {row.error ? (
                  <div
                    style={{
                      fontFamily: "var(--wb-font-serif, Georgia, serif)",
                      fontStyle: "italic",
                      fontSize: 10,
                      color: "var(--wb-color-hash-gray, #6b6256)",
                      marginTop: 2,
                      maxWidth: 260,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                    title={row.error}
                  >
                    {row.error}
                  </div>
                ) : null}
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  textAlign: "right",
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 12,
                }}
              >
                {row.durationMs}ms
              </td>
              <td
                style={{
                  ...TD_STYLE,
                  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
                  fontSize: 11,
                  whiteSpace: "nowrap",
                }}
              >
                {fmtTimestamp(row.ts)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
