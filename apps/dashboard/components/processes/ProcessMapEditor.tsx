"use client";
/**
 * ProcessMapEditor — admin-authored process map for the /processes tab
 * (W2.A7 of the production-hardening plan).
 *
 * Process maps normally auto-build from chat via the worm's
 * ``process_extractor`` loop. This editor backs the manual entry
 * affordance — used when an admin wants to author or canonicalise a
 * process by hand (onboarding seed, retro outcome, vendor handoff,
 * board-attested workflow).
 *
 * On submit POSTs to /api/v1/processes which routes to worm-core's
 * ``propose_process_map`` orchestrator (full PEVR cycle, lands
 * ``emit_process_map_proposed``).
 *
 * Steps editor: an array of {actor, action} rows; orderings are derived
 * from row position. Add / remove rows; minimum two for a valid sequence.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Input } from "@wormbase/design";

interface DraftStep {
  actor: string;
  action: string;
}

const DOMAIN_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "general", label: "general" },
  { value: "finance", label: "finance" },
  { value: "sales", label: "sales" },
  { value: "engineering", label: "engineering" },
  { value: "ops", label: "ops" },
  { value: "marketing", label: "marketing" },
  { value: "people", label: "people" },
  { value: "data", label: "data" },
];

export function ProcessMapEditor() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [processName, setProcessName] = useState("");
  const [domain, setDomain] = useState("general");
  const [steps, setSteps] = useState<DraftStep[]>([
    { actor: "", action: "" },
    { actor: "", action: "" },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setProcessName("");
    setDomain("general");
    setSteps([
      { actor: "", action: "" },
      { actor: "", action: "" },
    ]);
    setError(null);
  }

  function close() {
    setOpen(false);
    reset();
  }

  function updateStep(idx: number, key: keyof DraftStep, value: string) {
    setSteps((current) =>
      current.map((s, i) => (i === idx ? { ...s, [key]: value } : s)),
    );
  }

  function addStep() {
    setSteps((current) => [...current, { actor: "", action: "" }]);
  }

  function removeStep(idx: number) {
    setSteps((current) =>
      current.length > 2 ? current.filter((_, i) => i !== idx) : current,
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const name = processName.trim();
    if (!name) {
      setError("process name is required");
      return;
    }
    const cleaned = steps
      .map((s) => ({ actor: s.actor.trim(), action: s.action.trim() }))
      .filter((s) => s.actor && s.action);
    if (cleaned.length < 2) {
      setError("at least two complete steps (actor + action) are required");
      return;
    }
    setBusy(true);
    try {
      const res = await fetch("/api/v1/processes", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          process_name: name,
          domain,
          steps: cleaned.map((s, i) => ({
            order: i + 1,
            actor: s.actor,
            action: s.action,
            source_message_id: "",
          })),
          confidence: 0.95,
          proposed_by: "dashboard-admin",
        }),
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
        data-testid="process-editor-open"
        variant="ghost"
        size="sm"
        onClick={() => setOpen(true)}
      >
        Author process by hand
      </Button>
      {open ? (
        <div
          data-testid="process-editor-modal"
          role="dialog"
          aria-label="Author process map"
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
            data-testid="process-editor-scrim"
            aria-label="Close process editor"
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
            data-testid="process-editor-form"
            style={{
              position: "relative",
              width: "min(620px, 94vw)",
              maxHeight: "90vh",
              overflowY: "auto",
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
                Processes · Admin author
              </span>
              <h2
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 24,
                  fontWeight: 500,
                }}
              >
                Author a process map
              </h2>
              <p
                data-testid="process-editor-help"
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 13,
                  fontStyle: "italic",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                Process maps normally build from chat. Use this editor to
                seed an onboarding workflow, canonicalise a retro outcome,
                or attest a vendor handoff. The map lands as
                ``emit_process_map_proposed`` in the ledger.
              </p>
            </header>
            <Input
              label="Process name"
              data-testid="process-editor-name"
              value={processName}
              onChange={(e) => setProcessName(e.currentTarget.value)}
              placeholder="Q3 close"
              helperText="required"
            />
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
              Domain
              <select
                data-testid="process-editor-domain"
                value={domain}
                onChange={(e) => setDomain(e.currentTarget.value)}
                style={{
                  fontFamily: "var(--wb-font-mono)",
                  fontSize: 13,
                  padding: "6px 10px",
                  borderRadius: 0,
                  border: "1px solid var(--wb-color-aged-ink)",
                  background: "var(--wb-color-paper)",
                }}
              >
                {DOMAIN_OPTIONS.map((d) => (
                  <option key={d.value} value={d.value}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>
            <section
              data-testid="process-editor-steps"
              style={{ display: "flex", flexDirection: "column", gap: 8 }}
            >
              <span
                className="wb-mono"
                style={{
                  fontSize: 11,
                  letterSpacing: "0.16em",
                  textTransform: "uppercase",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                Steps
              </span>
              {steps.map((s, i) => (
                <div
                  key={i}
                  data-testid={`process-editor-step-${i}`}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "32px 1fr 1.6fr auto",
                    gap: 8,
                    alignItems: "center",
                  }}
                >
                  <span
                    className="wb-mono"
                    style={{
                      fontSize: 11,
                      color: "var(--wb-color-hash-gray)",
                    }}
                  >
                    #{i + 1}
                  </span>
                  <Input
                    label=""
                    data-testid={`process-editor-actor-${i}`}
                    value={s.actor}
                    onChange={(e) =>
                      updateStep(i, "actor", e.currentTarget.value)
                    }
                    placeholder="actor (Bob / Finance / cron)"
                  />
                  <Input
                    label=""
                    data-testid={`process-editor-action-${i}`}
                    value={s.action}
                    onChange={(e) =>
                      updateStep(i, "action", e.currentTarget.value)
                    }
                    placeholder="action (export, review, approve)"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => removeStep(i)}
                    disabled={steps.length <= 2}
                    data-testid={`process-editor-remove-${i}`}
                  >
                    Remove
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={addStep}
                data-testid="process-editor-add-step"
              >
                Add step
              </Button>
            </section>
            {error ? (
              <div
                data-testid="process-editor-error"
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
                data-testid="process-editor-cancel"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={busy}
                data-testid="process-editor-submit"
              >
                {busy ? "Authoring…" : "Author process map"}
              </Button>
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}
