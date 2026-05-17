"use client";
/**
 * ConnectorFirstGrid — Tier 0 connector-first landing (Block G2 / PRD §17).
 *
 * Inverts the original PRD §6 lifecycle. The first connection is a data
 * source from the connector catalog, not a chat-platform OAuth click.
 * After the first source connects and the medallion cascade fires, the
 * user lands on the wizard-vs-bot fork (G4).
 *
 * Cards group into three bands per ``status``:
 *   - production (top): full-color cards; clicking routes to
 *     ``/onboarding/connect/{kind}/start`` (G3).
 *   - preview (middle): amber pill; routes the same way but with a
 *     "preview" badge on the destination.
 *   - coming_soon (bottom, muted): gray pill; clicking opens a notify-me
 *     modal — does NOT start a connection flow.
 *
 * Connectors that don't carry identity (csv_local, postgres, snowflake,
 * http_csv) trigger the IdentityForm at the destination start handler;
 * OAuth connectors (stripe, salesforce, hubspot, gsheets) extract identity
 * from the OAuth profile.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import type {
  ConnectorCatalogEntry,
  ConnectorStatus,
} from "../../lib/lake-surfaces-catalog";

const BAND_LABEL: Record<ConnectorStatus, string> = {
  production: "production",
  preview: "preview",
  coming_soon: "coming soon",
};

const BAND_BLURB: Record<ConnectorStatus, string> = {
  production:
    "Wired end-to-end. OAuth or credentials connect; cascade fires within seconds.",
  preview:
    "Discovery + ingest are real. Some downstream actions still skeletal — full wiring in v1.5.",
  coming_soon:
    "Adapter skeleton. Notify the team to prioritize and we'll surface it in the build queue.",
};

function pillVisuals(status: ConnectorStatus) {
  if (status === "production") {
    return {
      color: "var(--wb-color-botanical-green-deep)",
      border: "var(--wb-color-botanical-green)",
      bg: "var(--wb-color-paper)",
      borderLeft: "3px solid var(--wb-color-botanical-green)",
      opacity: 1,
      cursor: "pointer",
    };
  }
  if (status === "preview") {
    return {
      color: "var(--wb-color-sepia-warning-deep)",
      border: "var(--wb-color-sepia-warning-deep)",
      bg: "var(--wb-color-paper)",
      borderLeft: "3px solid var(--wb-color-sepia-warning-deep)",
      opacity: 0.95,
      cursor: "pointer",
    };
  }
  return {
    color: "var(--wb-color-hash-gray)",
    border: "var(--wb-color-paper-edge)",
    bg: "var(--wb-color-paper-deep)",
    borderLeft: "3px solid var(--wb-color-hash-gray)",
    opacity: 0.5,
    cursor: "not-allowed",
  };
}

export function ConnectorFirstGrid({
  connectors,
}: {
  connectors: ConnectorCatalogEntry[];
}) {
  const router = useRouter();
  const [comingSoonKind, setComingSoonKind] = useState<string | null>(null);
  const [notifyResult, setNotifyResult] = useState<string | null>(null);

  const byStatus = (s: ConnectorStatus) =>
    connectors.filter((c) => c.status === s);

  const bands: ConnectorStatus[] = ["production", "preview", "coming_soon"];

  const comingSoonEntry = comingSoonKind
    ? (connectors.find((c) => c.kind === comingSoonKind) ?? null)
    : null;

  function onCardClick(c: ConnectorCatalogEntry) {
    if (c.status === "coming_soon") {
      setComingSoonKind(c.kind);
      setNotifyResult(null);
      return;
    }
    router.push(`/onboarding/connect/${c.kind}/start`);
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
        setNotifyResult(
          "noted — we'll surface this in the product analytics ledger",
        );
      } else {
        setNotifyResult(
          "logged locally — server endpoint not yet wired",
        );
      }
    } catch {
      setNotifyResult("logged locally — server endpoint not yet wired");
    }
  }

  return (
    <section
      data-testid="connector-first-grid"
      style={{ display: "flex", flexDirection: "column", gap: 24 }}
    >
      {bands.map((band) => {
        const items = byStatus(band);
        if (items.length === 0) return null;
        return (
          <div
            key={band}
            data-testid={`connector-band-${band}`}
            style={{ display: "flex", flexDirection: "column", gap: 10 }}
          >
            <header
              style={{ display: "flex", flexDirection: "column", gap: 2 }}
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
                {BAND_LABEL[band]}
              </span>
              <span
                style={{
                  fontFamily: "var(--wb-font-serif)",
                  fontStyle: "italic",
                  fontSize: 13,
                  color: "var(--wb-color-aged-ink-soft)",
                }}
              >
                {BAND_BLURB[band]}
              </span>
            </header>
            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(260px, 1fr))",
                gap: 10,
              }}
            >
              {items.map((c) => {
                const v = pillVisuals(c.status);
                const disabled = c.status === "coming_soon";
                return (
                  <button
                    key={c.kind}
                    type="button"
                    data-testid={`connector-first-card-${c.kind}`}
                    data-status={c.status}
                    aria-disabled={disabled}
                    onClick={() => onCardClick(c)}
                    title={c.statusNote}
                    style={{
                      textAlign: "left",
                      border: "1px solid var(--wb-color-paper-edge)",
                      borderLeft: v.borderLeft,
                      background: v.bg,
                      padding: 14,
                      cursor: v.cursor,
                      display: "flex",
                      flexDirection: "column",
                      gap: 8,
                      borderRadius: 0,
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
                        data-testid={`connector-first-pill-${c.kind}`}
                        style={{
                          fontSize: 9,
                          letterSpacing: "0.08em",
                          textTransform: "uppercase",
                          color: v.color,
                          border: `1px solid ${v.border}`,
                          padding: "1px 6px",
                          borderRadius: 0,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {BAND_LABEL[c.status]}
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
                      {c.description}
                    </span>
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
          </div>
        );
      })}

      {comingSoonEntry ? (
        <div
          data-testid={`connector-first-coming-soon-modal-${comingSoonEntry.kind}`}
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
            setComingSoonKind(null);
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
            <header
              style={{ display: "flex", flexDirection: "column", gap: 4 }}
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
                data-testid="connector-first-notify-result"
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
            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
              }}
            >
              <button
                type="button"
                onClick={() => {
                  setComingSoonKind(null);
                  setNotifyResult(null);
                }}
                data-testid="connector-first-modal-close"
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
                data-testid="connector-first-notify-me"
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
