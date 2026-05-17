"use client";
/**
 * DecisionDetailDrawer — slide-in inspector + manual record affordance
 * for the /decisions tab (W2.A7).
 *
 * Two modes:
 *   * `mode="inspect"` — drawer renders the full decision: text, channel,
 *     deciders, evidence message ids (each linked to /trace), confidence,
 *     receipt. Read-only.
 *   * `mode="record"` — drawer collects decision_text + channel_id +
 *     evidence + confidence and POSTs to /api/v1/decisions, which routes
 *     to worm-core's record-decision orchestrator (full PEVR cycle, lands
 *     ``emit_decision_recorded``). On success the drawer closes and the
 *     page refreshes.
 *
 * Decisions normally auto-extract from chat — the manual path exists for
 * canonicalising decisions the worm hasn't yet caught (audit replay,
 * board minutes, etc.).
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Input } from "@wormbase/design";
import type { DecisionRow } from "../../lib/ledger-client.types";
import { Receipt } from "../../lib/receipts";

export interface DecisionDetailDrawerProps {
  /** Inspect: existing row. Record: null + mode="record". */
  decision: DecisionRow | null;
  open: boolean;
  mode: "inspect" | "record";
  onClose: () => void;
}

export function DecisionDetailDrawer({
  decision,
  open,
  mode,
  onClose,
}: DecisionDetailDrawerProps) {
  if (!open) return null;
  return (
    <div
      data-testid="decision-detail-drawer"
      role="dialog"
      aria-label={mode === "record" ? "Record decision" : "Decision detail"}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 60,
        display: "flex",
        justifyContent: "flex-end",
      }}
    >
      <button
        data-testid="decision-drawer-scrim"
        aria-label="Close decision drawer"
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
      <aside
        style={{
          position: "relative",
          width: "min(560px, 96vw)",
          background: "var(--wb-color-paper)",
          borderLeft: "1px solid var(--wb-color-aged-ink)",
          padding: "24px 28px",
          overflowY: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        {mode === "record" ? (
          <RecordForm onClose={onClose} />
        ) : decision ? (
          <InspectView decision={decision} onClose={onClose} />
        ) : (
          <p
            data-testid="decision-drawer-empty"
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            No decision selected.
          </p>
        )}
      </aside>
    </div>
  );
}

function InspectView({
  decision,
  onClose,
}: {
  decision: DecisionRow;
  onClose: () => void;
}) {
  return (
    <>
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
          Decision · {decision.channelId}
        </span>
        <h2
          data-testid="decision-drawer-title"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
          }}
        >
          {decision.decisionText}
        </h2>
        <p
          className="wb-mono"
          style={{
            margin: 0,
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {decision.decisionAt} · confidence{" "}
          {(decision.confidence * 100).toFixed(0)}%
        </p>
      </header>
      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Decided by
        </span>
        {decision.decidedByPersons.length === 0 ? (
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            (no attributed persons)
          </span>
        ) : (
          <ul
            data-testid="decision-deciders"
            style={{ margin: 0, padding: 0, listStyle: "none" }}
          >
            {decision.decidedByPersons.map((p) => (
              <li
                key={p}
                className="wb-mono"
                style={{ fontSize: 12, padding: "2px 0" }}
              >
                {p}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Evidence messages
        </span>
        <ul
          data-testid="decision-evidence-list"
          style={{ margin: 0, padding: 0, listStyle: "none" }}
        >
          {decision.evidenceMessageIds.map((mid) => (
            <li key={mid} style={{ padding: "2px 0" }}>
              <a
                href={`/trace?evidence=${encodeURIComponent(mid)}`}
                className="wb-mono"
                style={{
                  fontSize: 12,
                  borderBottom: "1px dotted var(--wb-color-botanical-green)",
                  color: "var(--wb-color-aged-ink)",
                }}
              >
                {mid}
              </a>
            </li>
          ))}
        </ul>
      </section>
      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Receipt
        </span>
        <Receipt
          hash={decision.receipt.hash}
          source={decision.receipt.source}
          owner={decision.receipt.owner}
          classification={decision.receipt.classification}
        />
      </section>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onClose}
          data-testid="decision-drawer-close"
        >
          Close
        </Button>
      </div>
    </>
  );
}

function RecordForm({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [decisionText, setDecisionText] = useState("");
  const [channelId, setChannelId] = useState("");
  const [evidenceCsv, setEvidenceCsv] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const text = decisionText.trim();
    const channel = channelId.trim();
    if (!text) {
      setError("decision_text is required");
      return;
    }
    if (!channel) {
      setError("channel_id is required");
      return;
    }
    const evidence = evidenceCsv
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    setBusy(true);
    try {
      const res = await fetch("/api/v1/decisions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          decision_text: text,
          channel_id: channel,
          evidence_message_ids: evidence,
          confidence: 0.95,
          proposed_by: "dashboard-admin",
        }),
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `record failed (${res.status})`);
      }
      onClose();
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      data-testid="decision-record-form"
      style={{ display: "flex", flexDirection: "column", gap: 14 }}
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
          Decisions · Admin record
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
          }}
        >
          Record a decision
        </h2>
        <p
          data-testid="decision-record-help"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Decisions normally auto-extract from chat. Use this form to
          canonicalise a decision the worm hasn't yet caught — board
          minutes, retro outcomes, replayed audit findings.
        </p>
      </header>
      <Input
        label="Decision text"
        data-testid="decision-record-text"
        value={decisionText}
        onChange={(e) => setDecisionText(e.currentTarget.value)}
        placeholder="We decided to push Q3 close to Friday."
        helperText="required"
      />
      <Input
        label="Channel id"
        data-testid="decision-record-channel"
        value={channelId}
        onChange={(e) => setChannelId(e.currentTarget.value)}
        placeholder="C0SLACK / dm-bob / dashboard"
        helperText="required — where the decision was attested"
      />
      <Input
        label="Evidence message ids"
        data-testid="decision-record-evidence"
        value={evidenceCsv}
        onChange={(e) => setEvidenceCsv(e.currentTarget.value)}
        placeholder="msg-abc, msg-def"
        helperText="optional — comma-separated platform message ids"
      />
      {error ? (
        <div
          data-testid="decision-record-error"
          role="alert"
          className="wb-mono"
          style={{
            fontSize: 12,
            color: "var(--wb-color-sepia-warning-deep)",
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            padding: "6px 10px",
            background: "var(--wb-color-sepia-warning-soft)",
          }}
        >
          {error}
        </div>
      ) : null}
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          gap: 10,
          marginTop: 6,
        }}
      >
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onClose}
          data-testid="decision-record-cancel"
        >
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={busy}
          data-testid="decision-record-submit"
        >
          {busy ? "Recording…" : "Record decision"}
        </Button>
      </div>
    </form>
  );
}
