"use client";
/**
 * ProposeReactivityModal — natural-language entry point for proposing
 * a new Reactivity from the dashboard (W5.A5).
 *
 * UX:
 *   1. Admin clicks "Propose new reactivity" on /reactivities.
 *   2. Modal opens with a single textarea: "describe the reactivity in
 *      plain English (e.g. 'ping me whenever someone mentions revenue')."
 *   3. On submit, POSTs to /api/v1/reactivities/propose. The worm-core
 *      handler runs the deterministic NL parser and returns a *sketch*:
 *      the parsed predicate / action / scope / budget + a confidence score.
 *   4. The modal flips to a confirmation screen showing the full sketch.
 *      Honest about confidence — confidence < 0.5 surfaces a yellow
 *      banner asking the admin to refine the description before
 *      confirming.
 *   5. Admin clicks "Confirm" to register the reactivity (write the
 *      emit_reactivity_proposed); admin can also "Refine" to go back
 *      and edit the description, or "Reject" to discard and close.
 *
 * The modal does NOT confirm the reactivity itself — the propose write
 * is what lands; an admin still has to flip it to active via the
 * /reactivities table's "Confirm" CTA.
 */

import { useState } from "react";
import type { ReactivitySketch } from "../../lib/ledger-client.types";

type Stage = "compose" | "preview" | "submitting" | "done" | "error";

export interface ProposeReactivityModalProps {
  /** Called on close (X button or background click). */
  onClose: () => void;
  /** Called after a successful propose write so the parent can refresh
   *  the /reactivities listing. */
  onProposed?: (sketch: ReactivitySketch) => void;
}

const CONFIDENCE_THRESHOLD = 0.5;

function confidenceTone(c: number): {
  color: string;
  label: string;
  warn: boolean;
} {
  if (c >= 0.7) {
    return {
      color: "var(--wb-color-botanical-green-deep)",
      label: "high",
      warn: false,
    };
  }
  if (c >= CONFIDENCE_THRESHOLD) {
    return {
      color: "var(--wb-color-aged-ink)",
      label: "medium",
      warn: false,
    };
  }
  return {
    color: "var(--wb-color-sepia-warning-deep)",
    label: "low",
    warn: true,
  };
}

export function ProposeReactivityModal({
  onClose,
  onProposed,
}: ProposeReactivityModalProps) {
  const [description, setDescription] = useState("");
  const [stage, setStage] = useState<Stage>("compose");
  const [sketch, setSketch] = useState<ReactivitySketch | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function preview() {
    if (!description.trim()) {
      setError("description is required");
      return;
    }
    setError(null);
    setStage("submitting");
    try {
      // Two-step UX: the propose endpoint itself returns the sketch
      // *and* writes the propose entry. The "preview" step uses a
      // dry-run flag (?preview=1) so the admin can see the parse
      // before the propose lands. The endpoint accepts the flag and
      // skips the registry write when set.
      const res = await fetch(
        "/api/v1/reactivities/propose?preview=1",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ description }),
        },
      );
      if (!res.ok) {
        const t = await res.text().catch(() => "");
        throw new Error(t || `preview failed (${res.status})`);
      }
      const body = (await res.json()) as { sketch?: ReactivitySketch };
      if (!body.sketch) throw new Error("preview returned no sketch");
      setSketch(body.sketch);
      setStage("preview");
    } catch (err) {
      setError((err as Error).message);
      setStage("error");
    }
  }

  async function confirm() {
    if (!sketch) return;
    setStage("submitting");
    setError(null);
    try {
      const res = await fetch("/api/v1/reactivities/propose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description }),
      });
      if (!res.ok) {
        const t = await res.text().catch(() => "");
        throw new Error(t || `propose failed (${res.status})`);
      }
      const body = (await res.json()) as { sketch?: ReactivitySketch };
      const confirmed = body.sketch ?? sketch;
      onProposed?.(confirmed);
      setStage("done");
    } catch (err) {
      setError((err as Error).message);
      setStage("error");
    }
  }

  function refine() {
    setSketch(null);
    setStage("compose");
    setError(null);
  }

  const tone = sketch ? confidenceTone(sketch.confidence) : null;

  return (
    <div
      data-testid="propose-reactivity-modal"
      role="dialog"
      aria-label="Propose new reactivity"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 60,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <button
        data-testid="propose-reactivity-scrim"
        aria-label="Close"
        onClick={onClose}
        style={{
          position: "absolute",
          inset: 0,
          background: "rgba(20, 16, 8, 0.32)",
          border: "none",
          padding: 0,
          margin: 0,
          cursor: "pointer",
        }}
      />
      <article
        style={{
          position: "relative",
          width: "min(640px, 96vw)",
          maxHeight: "90vh",
          overflowY: "auto",
          background: "var(--wb-color-paper)",
          border: "1px solid var(--wb-color-aged-ink)",
          padding: "24px 28px",
          display: "flex",
          flexDirection: "column",
          gap: 18,
        }}
      >
        <header
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
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
              Reactivity · propose
            </span>
            <h2
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                fontSize: 24,
                fontWeight: 500,
              }}
            >
              {stage === "preview" || stage === "done"
                ? "Confirm the sketched reactivity"
                : "Describe a new reactivity"}
            </h2>
          </div>
          <button
            type="button"
            data-testid="propose-reactivity-close"
            onClick={onClose}
            style={{
              padding: "4px 10px",
              border: "1px solid var(--wb-color-aged-ink)",
              background: "transparent",
              fontFamily: "var(--wb-font-serif)",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Close
          </button>
        </header>

        {stage === "compose" || stage === "error" ? (
          <>
            <p
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                fontStyle: "italic",
                fontSize: 13,
                color: "var(--wb-color-hash-gray)",
              }}
            >
              The worm parses the description into a candidate
              predicate (entry kind + topic), action (DM the owner /
              post to channel), scope (person / domain / company), and
              a per-day budget. You see the full sketch before
              confirming — refine the description if the parse is off.
            </p>
            <textarea
              data-testid="propose-reactivity-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={5}
              placeholder="ping me whenever someone mentions revenue"
              style={{
                fontFamily: "var(--wb-font-mono)",
                fontSize: 13,
                padding: "10px 12px",
                border: "1px solid var(--wb-color-aged-ink)",
                background: "var(--wb-color-paper)",
                width: "100%",
                resize: "vertical",
              }}
            />
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                data-testid="propose-reactivity-preview"
                onClick={preview}
                disabled={(stage as Stage) === "submitting"}
                style={{
                  padding: "8px 14px",
                  border: "1px solid var(--wb-color-botanical-green-deep)",
                  background: "var(--wb-color-botanical-green)",
                  color: "var(--wb-color-paper)",
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                Sketch it
              </button>
            </div>
          </>
        ) : null}

        {stage === "preview" && sketch && tone ? (
          <>
            {tone.warn ? (
              <div
                data-testid="propose-reactivity-low-confidence"
                role="alert"
                className="wb-mono"
                style={{
                  fontSize: 12,
                  padding: "8px 10px",
                  border: "1px solid var(--wb-color-sepia-warning-deep)",
                  color: "var(--wb-color-sepia-warning-deep)",
                  background: "var(--wb-color-paper-deep)",
                }}
              >
                Low-confidence parse ({(sketch.confidence * 100).toFixed(0)}%).
                Try refining the description to be more specific about
                what entry kind triggers it (chat, file, kpi) and which
                topic it should match.
              </div>
            ) : null}
            <div
              data-testid="propose-reactivity-sketch"
              style={{
                display: "grid",
                gridTemplateColumns: "auto 1fr",
                gap: "8px 14px",
                padding: "12px 14px",
                background: "var(--wb-color-paper-deep)",
                border: "1px solid var(--wb-color-paper-edge)",
                fontFamily: "var(--wb-font-mono)",
                fontSize: 12,
              }}
            >
              <span style={{ color: "var(--wb-color-hash-gray)" }}>id</span>
              <span data-testid="propose-reactivity-sketch-id">{sketch.id}</span>
              <span style={{ color: "var(--wb-color-hash-gray)" }}>name</span>
              <span>{sketch.name}</span>
              <span style={{ color: "var(--wb-color-hash-gray)" }}>scope</span>
              <span data-testid="propose-reactivity-sketch-scope">
                {sketch.scope}
              </span>
              <span style={{ color: "var(--wb-color-hash-gray)" }}>
                predicate
              </span>
              <span>
                {String(sketch.predicate_spec.entry_kind ?? "—")}
                {sketch.predicate_spec.topic
                  ? ` · topic=${String(sketch.predicate_spec.topic)}`
                  : ""}
              </span>
              <span style={{ color: "var(--wb-color-hash-gray)" }}>
                action
              </span>
              <span>{String(sketch.action_spec.kind ?? "—")}</span>
              <span style={{ color: "var(--wb-color-hash-gray)" }}>
                budget
              </span>
              <span>
                owner={String(sketch.condition_spec.per_owner_per_day ?? 3)}
                /d · domain=
                {String(sketch.condition_spec.per_domain_per_day ?? 10)}
                /d · tenant=
                {String(sketch.condition_spec.per_tenant_per_day ?? 50)}/d
              </span>
              <span style={{ color: "var(--wb-color-hash-gray)" }}>
                confidence
              </span>
              <span
                data-testid="propose-reactivity-sketch-confidence"
                style={{ color: tone.color, fontWeight: 600 }}
              >
                {(sketch.confidence * 100).toFixed(0)}% ({tone.label})
              </span>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                data-testid="propose-reactivity-confirm"
                onClick={confirm}
                style={{
                  padding: "8px 14px",
                  border: "1px solid var(--wb-color-botanical-green-deep)",
                  background: "var(--wb-color-botanical-green)",
                  color: "var(--wb-color-paper)",
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                Confirm propose
              </button>
              <button
                type="button"
                data-testid="propose-reactivity-refine"
                onClick={refine}
                style={{
                  padding: "8px 14px",
                  border: "1px solid var(--wb-color-aged-ink)",
                  background: "transparent",
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                Refine description
              </button>
              <button
                type="button"
                data-testid="propose-reactivity-reject"
                onClick={onClose}
                style={{
                  padding: "8px 14px",
                  border: "1px solid var(--wb-color-aged-ink)",
                  background: "transparent",
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                Reject
              </button>
            </div>
          </>
        ) : null}

        {stage === "done" ? (
          <div
            data-testid="propose-reactivity-done"
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 14,
              color: "var(--wb-color-aged-ink)",
            }}
          >
            Proposed. The reactivity is now in the proposed state — an
            admin needs to confirm it via the table before it fires.
          </div>
        ) : null}

        {error ? (
          <div
            data-testid="propose-reactivity-error"
            role="alert"
            className="wb-mono"
            style={{
              fontSize: 12,
              color: "var(--wb-color-sepia-warning-deep)",
            }}
          >
            {error}
          </div>
        ) : null}
      </article>
    </div>
  );
}
