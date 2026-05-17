"use client";
/**
 * PositionProposalQueue — admin queue for worm-proposed positions.
 *
 * Wave H Phase 2 Task 2C — Position Auto-Confirm UX.
 *
 * Renders one row per pending ``emit_position_proposed``. Each row carries
 * a Confirm and a Reject button; Reject opens a free-form reason input
 * for trace-UI explainability. Both actions POST to dashboard route
 * proxies, which in turn hit worm-core's confirm/reject HTTP endpoints
 * (one PEVR cycle each, 4 ledger entries).
 *
 * Empty-state honest: when the queue is empty, the panel renders a
 * "no pending proposals" line — it does not silently disappear (per the
 * "no demo seams" rule in CLAUDE.md §9).
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@wormbase/design";
import type { PositionProposalRow } from "../../lib/server/worm-core-write";
import { chipStyle, PLATE_RULE } from "./_styles";

export interface PositionProposalQueueProps {
  proposals: PositionProposalRow[];
}

export function PositionProposalQueue({
  proposals,
}: PositionProposalQueueProps) {
  const router = useRouter();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [rejectFor, setRejectFor] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<string>("");

  async function confirmRow(p: PositionProposalRow) {
    setBusyId(p.person_id);
    setError(null);
    setSuccess(null);
    try {
      const res = await fetch(
        `/api/v1/people/${encodeURIComponent(p.person_id)}/position/confirm`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ position: p.position }),
        },
      );
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `confirm failed (${res.status})`);
      }
      setSuccess(`Confirmed ${p.position} for ${p.person_name}.`);
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  async function rejectRow(p: PositionProposalRow) {
    setBusyId(p.person_id);
    setError(null);
    setSuccess(null);
    try {
      const res = await fetch(
        `/api/v1/people/${encodeURIComponent(p.person_id)}/position/reject`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            position: p.position,
            reason: rejectReason.trim() || null,
          }),
        },
      );
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `reject failed (${res.status})`);
      }
      setSuccess(`Rejected ${p.position} for ${p.person_name}.`);
      setRejectFor(null);
      setRejectReason("");
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section
      data-testid="position-proposal-queue"
      style={{
        border: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper)",
        padding: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <header
        style={{
          padding: "16px 20px",
          borderBottom: "1px solid var(--wb-color-aged-ink)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 16,
          flexWrap: "wrap",
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
            Pl. IV.b · Position review queue
          </span>
          <h2
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 22,
              fontWeight: 500,
            }}
          >
            Pending position proposals · {proposals.length}
          </h2>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-aged-ink-soft)",
              fontSize: 13,
            }}
          >
            The worm proposes positions from chatter signal. Confirm to
            keep, reject to clear the inferred role and free the dedup
            gate so a richer-signal proposal can follow.
          </p>
        </div>
      </header>

      {error ? (
        <p
          role="alert"
          className="wb-mono"
          style={{
            margin: 0,
            padding: "12px 20px",
            borderBottom: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-sepia-warning-soft)",
            color: "var(--wb-color-sepia-warning-deep)",
            fontSize: 12,
          }}
        >
          {error}
        </p>
      ) : null}
      {success ? (
        <p
          className="wb-mono"
          style={{
            margin: 0,
            padding: "12px 20px",
            borderBottom: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-botanical-green-soft)",
            color: "var(--wb-color-botanical-green-deep)",
            fontSize: 12,
          }}
        >
          {success}
        </p>
      ) : null}

      {proposals.length === 0 ? (
        <p
          style={{
            margin: 0,
            padding: "24px 20px",
            color: "var(--wb-color-aged-ink-soft)",
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
          }}
        >
          No pending position proposals. The worm has not crossed the
          inference threshold for any Person yet — wait for more chatter
          to accumulate, or assign a position directly from the People
          page.
        </p>
      ) : (
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontFamily: "var(--wb-font-serif)",
            fontSize: 14,
          }}
        >
          <thead>
            <tr style={PLATE_RULE}>
              <th style={th}>Person</th>
              <th style={th}>Proposed position</th>
              <th style={th}>Confidence</th>
              <th style={th}>Signals</th>
              <th style={th}>Proposed at</th>
              <th style={{ ...th, textAlign: "right" }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {proposals.map((p) => (
              <tr key={p.person_id} style={tr}>
                <td style={td}>
                  <span style={{ display: "flex", flexDirection: "column" }}>
                    <span style={{ fontWeight: 500 }}>{p.person_name}</span>
                    <span
                      className="wb-mono"
                      style={{
                        fontSize: 10,
                        color: "var(--wb-color-hash-gray)",
                      }}
                    >
                      {p.person_id.slice(0, 8)}
                    </span>
                  </span>
                </td>
                <td style={td}>
                  <span style={chipStyle("ink")}>{p.position}</span>
                </td>
                <td style={td} className="wb-mono">
                  {(p.confidence * 100).toFixed(0)}%
                </td>
                <td style={td}>
                  <span
                    style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}
                  >
                    {p.signals.length === 0 ? (
                      <span
                        style={{
                          color: "var(--wb-color-hash-gray)",
                          fontSize: 12,
                        }}
                      >
                        —
                      </span>
                    ) : (
                      p.signals.map((s) => (
                        <span key={s} style={chipStyle("muted")}>
                          {s}
                        </span>
                      ))
                    )}
                  </span>
                </td>
                <td style={td} className="wb-mono">
                  {p.proposed_at
                    ? new Date(p.proposed_at).toISOString().slice(0, 19) + "Z"
                    : "—"}
                </td>
                <td style={{ ...td, textAlign: "right" }}>
                  <span
                    style={{
                      display: "inline-flex",
                      gap: 8,
                      justifyContent: "flex-end",
                    }}
                  >
                    <Button
                      variant="secondary"
                      onClick={() => confirmRow(p)}
                      disabled={busyId !== null}
                      data-testid={`confirm-${p.person_id}`}
                    >
                      Confirm
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setRejectFor(
                          rejectFor === p.person_id ? null : p.person_id,
                        );
                        setRejectReason("");
                      }}
                      disabled={busyId !== null}
                      data-testid={`reject-${p.person_id}`}
                    >
                      Reject
                    </Button>
                  </span>
                  {rejectFor === p.person_id ? (
                    <div
                      style={{
                        marginTop: 8,
                        display: "flex",
                        flexDirection: "column",
                        gap: 6,
                        textAlign: "left",
                      }}
                    >
                      <label
                        htmlFor={`reject-reason-${p.person_id}`}
                        className="wb-mono"
                        style={{
                          fontSize: 10,
                          letterSpacing: "0.12em",
                          textTransform: "uppercase",
                          color: "var(--wb-color-hash-gray)",
                        }}
                      >
                        Reason (optional)
                      </label>
                      <textarea
                        id={`reject-reason-${p.person_id}`}
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        rows={2}
                        style={{
                          width: "100%",
                          fontFamily: "var(--wb-font-serif)",
                          fontSize: 13,
                          padding: 8,
                          border: "1px solid var(--wb-color-aged-ink)",
                          background: "var(--wb-color-paper-deep)",
                          color: "var(--wb-color-aged-ink)",
                        }}
                      />
                      <span style={{ display: "flex", gap: 8 }}>
                        <Button
                          variant="primary"
                          onClick={() => rejectRow(p)}
                          disabled={busyId !== null}
                          data-testid={`reject-confirm-${p.person_id}`}
                        >
                          Reject this proposal
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => {
                            setRejectFor(null);
                            setRejectReason("");
                          }}
                          disabled={busyId !== null}
                        >
                          Cancel
                        </Button>
                      </span>
                    </div>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

const th = {
  padding: "10px 16px",
  textAlign: "left" as const,
  fontFamily: "var(--wb-font-serif)",
  fontWeight: 500,
  fontSize: 12,
  textTransform: "uppercase" as const,
  letterSpacing: "0.08em",
  color: "var(--wb-color-aged-ink-soft)",
  borderBottom: "1px solid var(--wb-color-aged-ink)",
};

const tr = {
  borderBottom: "1px solid var(--wb-color-paper-edge)",
};

const td = {
  padding: "12px 16px",
  verticalAlign: "top" as const,
};
