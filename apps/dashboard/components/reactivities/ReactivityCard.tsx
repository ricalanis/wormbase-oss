"use client";
/**
 * ReactivityCard — one row in the /reactivities table (W5.A5).
 *
 * Editorial chrome: square corners, sepia rule borders, wb-mono labels.
 * Each card shows:
 *   - id + name + scope chip (company / team / domain / person)
 *   - state pill (active = green, proposed = sepia, disabled = grey)
 *   - last-fired timestamp (ISO → human-relative)
 *   - 3 budget bars (per-owner / per-domain / per-tenant) when known
 *   - "Confirm" CTA when state == proposed (admin only)
 *   - "Disable" CTA when state == active
 *   - "Show fires" toggle that mounts ReactivityFiresLog underneath
 *
 * Disabled rows render greyed-out but visible — admins still need to
 * audit them. The /reactivities page's "Show disabled" toggle filters
 * the section, not the card itself.
 */

import { useState } from "react";
import type { Reactivity } from "../../lib/ledger-client.types";
import { ReactivityFiresLog } from "./ReactivityFiresLog";

const SCOPE_TONE: Record<string, string> = {
  company: "var(--wb-color-botanical-green-deep)",
  team: "var(--wb-color-aged-ink)",
  domain: "var(--wb-color-sepia-warning-deep)",
  person: "var(--wb-color-hash-gray)",
};

const STATE_TONE: Record<string, string> = {
  active: "var(--wb-color-botanical-green-deep)",
  proposed: "var(--wb-color-sepia-warning-deep)",
  disabled: "var(--wb-color-hash-gray)",
};

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return iso;
  if (ms < 60_000) return "just now";
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h ago`;
  return `${Math.round(ms / 86_400_000)}d ago`;
}

export interface ReactivityCardProps {
  reactivity: Reactivity;
  /** When true, the Confirm / Disable CTAs are clickable. /reactivities
   *  is admin-only so this defaults to true; observer mode passes false. */
  canMutate?: boolean;
  /** Called after a successful confirm/disable so the parent can refresh. */
  onMutated?: () => void;
}

export function ReactivityCard({
  reactivity,
  canMutate = true,
  onMutated,
}: ReactivityCardProps) {
  const [showFires, setShowFires] = useState(false);
  const [busy, setBusy] = useState<"confirm" | "disable" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const isDisabled = reactivity.state === "disabled";

  async function confirm() {
    if (!canMutate) return;
    setBusy("confirm");
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/reactivities/${encodeURIComponent(reactivity.id)}/confirm`,
        { method: "POST" },
      );
      if (!res.ok) {
        const t = await res.text().catch(() => "");
        throw new Error(t || `confirm failed (${res.status})`);
      }
      onMutated?.();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function disable() {
    if (!canMutate) return;
    if (!reason.trim()) {
      setError("reason is required to disable");
      return;
    }
    setBusy("disable");
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/reactivities/${encodeURIComponent(reactivity.id)}/disable`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason }),
        },
      );
      if (!res.ok) {
        const t = await res.text().catch(() => "");
        throw new Error(t || `disable failed (${res.status})`);
      }
      setReason("");
      onMutated?.();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <article
      data-testid={`reactivity-card-${reactivity.id}`}
      data-state={reactivity.state}
      style={{
        border: "1px solid var(--wb-color-paper-edge)",
        background: isDisabled
          ? "var(--wb-color-paper-deep)"
          : "var(--wb-color-paper)",
        opacity: isDisabled ? 0.65 : 1,
        padding: "16px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {reactivity.id}
          </span>
          <h3
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 20,
              fontWeight: 500,
            }}
          >
            {reactivity.name}
          </h3>
          {reactivity.description ? (
            <p
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                fontStyle: "italic",
                fontSize: 13,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              {reactivity.description}
            </p>
          ) : null}
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span
            data-testid={`reactivity-scope-${reactivity.id}`}
            className="wb-mono"
            style={{
              fontSize: 10,
              padding: "2px 8px",
              border: `1px solid ${SCOPE_TONE[reactivity.scope] ?? "var(--wb-color-aged-ink)"}`,
              color: SCOPE_TONE[reactivity.scope] ?? "var(--wb-color-aged-ink)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
            }}
          >
            {reactivity.scope}
          </span>
          <span
            data-testid={`reactivity-state-${reactivity.id}`}
            className="wb-mono"
            style={{
              fontSize: 10,
              padding: "2px 8px",
              background: STATE_TONE[reactivity.state] ?? "transparent",
              color: "var(--wb-color-paper)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
            }}
          >
            {reactivity.state}
          </span>
        </div>
      </header>

      <div
        className="wb-mono"
        style={{
          fontSize: 11,
          color: "var(--wb-color-hash-gray)",
          letterSpacing: "0.04em",
        }}
      >
        last fired:{" "}
        <span data-testid={`reactivity-last-fired-${reactivity.id}`}>
          {relativeTime(reactivity.lastFiredAt)}
        </span>
      </div>

      {reactivity.disableReason ? (
        <div
          className="wb-mono"
          data-testid={`reactivity-disable-reason-${reactivity.id}`}
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
            fontStyle: "italic",
          }}
        >
          disabled: {reactivity.disableReason}
        </div>
      ) : null}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {reactivity.state === "proposed" ? (
          <button
            type="button"
            data-testid={`reactivity-confirm-${reactivity.id}`}
            onClick={confirm}
            disabled={!canMutate || busy === "confirm"}
            style={{
              padding: "6px 12px",
              border: "1px solid var(--wb-color-botanical-green-deep)",
              background: "var(--wb-color-botanical-green)",
              color: "var(--wb-color-paper)",
              fontFamily: "var(--wb-font-serif)",
              fontSize: 12,
              cursor: canMutate ? "pointer" : "not-allowed",
            }}
          >
            {busy === "confirm" ? "Confirming…" : "Confirm"}
          </button>
        ) : null}
        {reactivity.state === "active" ? (
          <>
            <input
              data-testid={`reactivity-disable-reason-input-${reactivity.id}`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="reason"
              style={{
                padding: "4px 8px",
                fontFamily: "var(--wb-font-mono)",
                fontSize: 12,
                border: "1px solid var(--wb-color-aged-ink)",
                background: "var(--wb-color-paper)",
                width: 200,
              }}
            />
            <button
              type="button"
              data-testid={`reactivity-disable-${reactivity.id}`}
              onClick={disable}
              disabled={!canMutate || busy === "disable"}
              style={{
                padding: "6px 12px",
                border: "1px solid var(--wb-color-aged-ink)",
                background: "transparent",
                fontFamily: "var(--wb-font-serif)",
                fontSize: 12,
                cursor: canMutate ? "pointer" : "not-allowed",
              }}
            >
              {busy === "disable" ? "Disabling…" : "Disable"}
            </button>
          </>
        ) : null}
        <button
          type="button"
          data-testid={`reactivity-show-fires-${reactivity.id}`}
          onClick={() => setShowFires((prev) => !prev)}
          style={{
            padding: "6px 12px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "transparent",
            fontFamily: "var(--wb-font-serif)",
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          {showFires ? "Hide fires" : "Show fires"}
        </button>
      </div>

      {error ? (
        <div
          data-testid={`reactivity-error-${reactivity.id}`}
          role="alert"
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-sepia-warning-deep)",
          }}
        >
          {error}
        </div>
      ) : null}

      {showFires ? (
        <ReactivityFiresLog reactivityId={reactivity.id} />
      ) : null}
    </article>
  );
}
