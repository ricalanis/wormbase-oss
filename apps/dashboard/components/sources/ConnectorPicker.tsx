"use client";
/**
 * ConnectorPicker — the connector kind catalog grid.
 *
 * D4 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * One card per kind from the dashboard's hardcoded catalog (lib/
 * connectors-catalog.ts). Three card states driven by ``status``:
 *
 *   - production: green pill ``Production``; full-color card; routes
 *     to the config form on click.
 *   - preview: amber pill ``Preview`` + tooltip; clicking still opens
 *     the config form (with a ``ConnectorConfigForm`` info banner).
 *   - coming_soon: gray pill ``Coming soon``; muted card (50% opacity);
 *     clicking opens a "coming soon" modal with a notify-me CTA — does
 *     NOT route to the config form.
 *
 * Capability-honesty contract: the picker NEVER pretends a coming_soon
 * connector works. Its config form does not render; its OAuth flow
 * does not start. The ledger receives a ``coming_soon_interest`` entry
 * when admins click "Notify me" so product can prioritize.
 */
import { useState } from "react";
import { ConnectorConfigForm } from "./ConnectorConfigForm";
import type {
  ConnectorCatalogEntry,
  CapabilityFlag,
  ConnectorStatus,
} from "../../lib/connectors-catalog";

const CAP_LABEL: Record<CapabilityFlag, string> = {
  discover: "discover",
  profile: "profile",
  sample: "sample",
  watch: "watch",
};

interface StatusVisuals {
  pillLabel: string;
  pillColor: string;
  pillBorder: string;
  cardBg: string;
  cardBorderLeft: string;
  opacity: number;
  cursor: string;
}

function visualsFor(status: ConnectorStatus): StatusVisuals {
  switch (status) {
    case "production":
      return {
        pillLabel: "production",
        pillColor: "var(--wb-color-botanical-green-deep)",
        pillBorder: "var(--wb-color-botanical-green)",
        cardBg: "var(--wb-color-paper)",
        cardBorderLeft: "3px solid var(--wb-color-botanical-green)",
        opacity: 1,
        cursor: "pointer",
      };
    case "preview":
      return {
        pillLabel: "preview",
        pillColor: "var(--wb-color-sepia-warning-deep)",
        pillBorder: "var(--wb-color-sepia-warning-deep)",
        cardBg: "var(--wb-color-paper)",
        cardBorderLeft: "3px solid var(--wb-color-sepia-warning-deep)",
        opacity: 0.95,
        cursor: "pointer",
      };
    case "coming_soon":
    default:
      return {
        pillLabel: "coming soon",
        pillColor: "var(--wb-color-hash-gray)",
        pillBorder: "var(--wb-color-paper-edge)",
        cardBg: "var(--wb-color-paper-deep)",
        cardBorderLeft: "3px solid var(--wb-color-hash-gray)",
        opacity: 0.5,
        cursor: "not-allowed",
      };
  }
}

export function ConnectorPicker({
  connectors,
}: {
  connectors: ConnectorCatalogEntry[];
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [comingSoonModalKind, setComingSoonModalKind] = useState<string | null>(null);
  const [notifyResult, setNotifyResult] = useState<string | null>(null);
  const active = selected
    ? (connectors.find((c) => c.kind === selected && c.status !== "coming_soon") ?? null)
    : null;

  const comingSoonEntry = comingSoonModalKind
    ? (connectors.find((c) => c.kind === comingSoonModalKind) ?? null)
    : null;

  function onCardClick(c: ConnectorCatalogEntry) {
    if (c.status === "coming_soon") {
      setComingSoonModalKind(c.kind);
      setNotifyResult(null);
      return;
    }
    setSelected(c.kind);
  }

  async function notifyMe() {
    if (!comingSoonEntry) return;
    try {
      const res = await fetch("/api/connectors/notify", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          kind: comingSoonEntry.kind,
          interest: "coming_soon_interest",
        }),
      });
      if (res.ok) {
        setNotifyResult("noted — we'll surface this in the product analytics ledger");
      } else {
        setNotifyResult("logged locally — server endpoint not yet wired");
      }
    } catch {
      setNotifyResult("logged locally — server endpoint not yet wired");
    }
  }

  return (
    <section
      data-testid="connector-picker"
      style={{ display: "flex", flexDirection: "column", gap: 16 }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
          gap: 12,
        }}
      >
        {connectors.map((c) => {
          const v = visualsFor(c.status);
          const isComingSoon = c.status === "coming_soon";
          return (
            <button
              key={c.kind}
              type="button"
              data-testid={`connector-card-${c.kind}`}
              data-ready={c.ready ? "true" : "false"}
              data-status={c.status}
              data-selected={selected === c.kind ? "true" : "false"}
              aria-disabled={isComingSoon}
              onClick={() => onCardClick(c)}
              title={c.statusNote}
              style={{
                textAlign: "left",
                borderTop:
                  selected === c.kind
                    ? "1px solid var(--wb-color-aged-ink)"
                    : "1px solid var(--wb-color-paper-edge)",
                borderRight:
                  selected === c.kind
                    ? "1px solid var(--wb-color-aged-ink)"
                    : "1px solid var(--wb-color-paper-edge)",
                borderBottom:
                  selected === c.kind
                    ? "1px solid var(--wb-color-aged-ink)"
                    : "1px solid var(--wb-color-paper-edge)",
                background: v.cardBg,
                padding: 14,
                cursor: v.cursor,
                display: "flex",
                flexDirection: "column",
                gap: 8,
                borderRadius: 0,
                borderLeft: v.cardBorderLeft,
                opacity: v.opacity,
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
                  {c.label}
                </span>
                <span
                  className="wb-mono"
                  data-testid={`connector-status-pill-${c.kind}`}
                  style={{
                    fontSize: 9,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    color: v.pillColor,
                    border: `1px solid ${v.pillBorder}`,
                    padding: "1px 6px",
                    borderRadius: 0,
                    whiteSpace: "nowrap",
                  }}
                >
                  {v.pillLabel}
                </span>
              </header>
              {isComingSoon ? (
                <span
                  data-testid={`connector-status-note-${c.kind}`}
                  className="wb-mono"
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.05em",
                    color: "var(--wb-color-hash-gray)",
                    fontStyle: "italic",
                  }}
                >
                  {c.statusNote}
                </span>
              ) : null}
              <span
                style={{
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 12,
                  color: "var(--wb-color-aged-ink)",
                  lineHeight: 1.4,
                }}
              >
                {c.description}
              </span>
              <div
                style={{ display: "flex", flexWrap: "wrap", gap: 4 }}
                data-testid={`connector-caps-${c.kind}`}
              >
                {c.capabilities.map((cap) => (
                  <span
                    key={cap}
                    className="wb-mono"
                    style={{
                      fontSize: 9,
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                      color: "var(--wb-color-hash-gray)",
                      border: "1px solid var(--wb-color-paper-edge)",
                      padding: "1px 5px",
                      borderRadius: 0,
                    }}
                  >
                    {CAP_LABEL[cap]}
                  </span>
                ))}
              </div>
              <span
                className="wb-mono"
                style={{
                  fontSize: 10,
                  letterSpacing: "0.08em",
                  color: "var(--wb-color-aged-ink-soft)",
                }}
              >
                kind: {c.kind}
              </span>
            </button>
          );
        })}
      </div>
      {active ? <ConnectorConfigForm connector={active} /> : null}

      {comingSoonEntry ? (
        <div
          data-testid={`connector-coming-soon-modal-${comingSoonEntry.kind}`}
          role="dialog"
          aria-label={`${comingSoonEntry.label} coming soon`}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(20, 20, 20, 0.45)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
          }}
          onClick={() => {
            setComingSoonModalKind(null);
            setNotifyResult(null);
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "var(--wb-color-paper)",
              border: "1px solid var(--wb-color-aged-ink)",
              padding: 24,
              maxWidth: 460,
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span
                className="wb-mono"
                style={{
                  fontSize: 10,
                  letterSpacing: "0.18em",
                  textTransform: "uppercase",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                coming soon
              </span>
              <h3
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 22,
                }}
              >
                {comingSoonEntry.label}
              </h3>
            </header>
            <p
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                color: "var(--wb-color-aged-ink)",
                lineHeight: 1.5,
              }}
            >
              {comingSoonEntry.statusNote}
            </p>
            {notifyResult ? (
              <p
                data-testid="coming-soon-notify-result"
                className="wb-mono"
                style={{
                  fontSize: 11,
                  color: "var(--wb-color-botanical-green-deep)",
                  margin: 0,
                }}
              >
                {notifyResult}
              </p>
            ) : null}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button
                type="button"
                onClick={() => {
                  setComingSoonModalKind(null);
                  setNotifyResult(null);
                }}
                data-testid="coming-soon-modal-close"
                className="wb-mono"
                style={{
                  fontSize: 11,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  padding: "6px 12px",
                  border: "1px solid var(--wb-color-aged-ink)",
                  background: "var(--wb-color-paper)",
                  cursor: "pointer",
                  borderRadius: 0,
                }}
              >
                close
              </button>
              <button
                type="button"
                onClick={notifyMe}
                data-testid="coming-soon-notify-me"
                className="wb-mono"
                style={{
                  fontSize: 11,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  padding: "6px 12px",
                  border: "1px solid var(--wb-color-aged-ink)",
                  background: "var(--wb-color-botanical-green-soft)",
                  cursor: "pointer",
                  borderRadius: 0,
                }}
              >
                notify me when ready
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
