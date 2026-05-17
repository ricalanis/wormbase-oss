"use client";
/**
 * ProposeKpiModal — admin proposes a KPI tree node from the /kpis tab.
 *
 * W2.A7 of the production-hardening plan
 * (`docs/superpowers/plans/2026-04-28-production-hardening.md`).
 *
 * The /kpis empty state's primary CTA opens this modal; the populated
 * state's "Propose KPI" header button opens it too. On submit:
 *
 *   1. POST /api/v1/kpis/propose with the canonical body.
 *   2. The dashboard route forwards to worm-core (bearer-token authed),
 *      which runs the canonical PEVR cycle and writes
 *      ``emit_kpi_proposed`` — hash-chained, audit-trailed.
 *   3. On success the modal closes and the page refreshes; the proposal
 *      lands in the ledger and the gold-cascade reader threads it into
 *      the visible KPI tree on the next refresh.
 *
 * Editorial chrome — square corners, wb-mono eyebrow, serif body, sepia
 * dashed border. Matches the InviteModal / EmptyState visual language.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Input } from "@wormbase/design";

const UNIT_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "count", label: "count" },
  { value: "currency_usd", label: "USD" },
  { value: "percent", label: "%" },
  { value: "ratio", label: "ratio" },
  { value: "duration_days", label: "days" },
];

export function ProposeKpiModal() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [formula, setFormula] = useState("");
  const [unit, setUnit] = useState("count");
  const [ownerPosition, setOwnerPosition] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setLabel("");
    setFormula("");
    setUnit("count");
    setOwnerPosition("");
    setError(null);
  }

  function close() {
    setOpen(false);
    reset();
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const trimmedLabel = label.trim();
    if (!trimmedLabel) {
      setError("label is required");
      return;
    }
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        label: trimmedLabel,
        formula: formula.trim(),
        unit,
        proposed_by: "dashboard-admin",
      };
      const trimmedOwner = ownerPosition.trim();
      if (trimmedOwner) body.owner_position = trimmedOwner;
      const res = await fetch("/api/v1/kpis/propose", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const j = (await res.json().catch(() => ({}))) as { message?: string };
        throw new Error(j.message ?? `propose failed (${res.status})`);
      }
      close();
      router.refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        data-testid="propose-kpi-open"
        variant="primary"
        size="sm"
        onClick={() => setOpen(true)}
      >
        Propose KPI
      </Button>
      {open ? (
        <div
          data-testid="propose-kpi-modal"
          role="dialog"
          aria-label="Propose KPI"
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
            data-testid="propose-kpi-scrim"
            aria-label="Close propose KPI modal"
            onClick={close}
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
          <form
            onSubmit={submit}
            data-testid="propose-kpi-form"
            style={{
              position: "relative",
              width: "min(540px, 92vw)",
              background: "var(--wb-color-paper)",
              border: "1px solid var(--wb-color-aged-ink)",
              padding: "24px 28px",
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
                KPIs · Admin propose
              </span>
              <h2
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 24,
                  fontWeight: 500,
                }}
              >
                Propose a KPI
              </h2>
              <p
                data-testid="propose-kpi-help"
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                  fontStyle: "italic",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                The KPI lands as ``emit_kpi_proposed`` in the ledger, runs
                through the canonical PEVR cycle, and threads into the
                visible tree on the next refresh. The worm picks it up
                whether you provide a formula or not.
              </p>
            </header>
            <Input
              label="Label"
              data-testid="propose-kpi-label"
              value={label}
              onChange={(e) => setLabel(e.currentTarget.value)}
              placeholder="Q3 net revenue"
              helperText="required"
            />
            <Input
              label="Formula"
              data-testid="propose-kpi-formula"
              value={formula}
              onChange={(e) => setFormula(e.currentTarget.value)}
              placeholder="sum(revenue.amount) - sum(refunds.amount)"
              helperText="optional — pseudocode is fine; the worm refines it"
            />
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 10,
              }}
            >
              <label
                className="wb-mono"
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  fontSize: 11,
                  letterSpacing: "0.16em",
                  textTransform: "uppercase",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                Unit
                <select
                  data-testid="propose-kpi-unit"
                  value={unit}
                  onChange={(e) => setUnit(e.currentTarget.value)}
                  style={{
                    fontFamily: "var(--wb-font-mono)",
                    fontSize: 13,
                    padding: "6px 10px",
                    borderRadius: 0,
                    border: "1px solid var(--wb-color-aged-ink)",
                    background: "var(--wb-color-paper)",
                  }}
                >
                  {UNIT_OPTIONS.map((u) => (
                    <option key={u.value} value={u.value}>
                      {u.label}
                    </option>
                  ))}
                </select>
              </label>
              <Input
                label="Owner position"
                data-testid="propose-kpi-owner-position"
                value={ownerPosition}
                onChange={(e) => setOwnerPosition(e.currentTarget.value)}
                placeholder="CFO"
                helperText="optional"
              />
            </div>
            {error ? (
              <div
                data-testid="propose-kpi-error"
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
                onClick={close}
                data-testid="propose-kpi-cancel"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={busy}
                data-testid="propose-kpi-submit"
              >
                {busy ? "Proposing…" : "Propose KPI"}
              </Button>
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}
