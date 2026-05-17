"use client";
/**
 * IdentityForm — pre-connect installer-identity capture (Block G2 / PRD §17).
 *
 * Shown only for connectors that don't carry installer identity natively
 * (csv_local, postgres, snowflake, http_csv). OAuth connectors (stripe,
 * salesforce, hubspot, gsheets) skip this form because the OAuth profile
 * already carries name + email + platform_user_id.
 *
 * The form posts to ``/api/people`` (the dashboard-side proxy that calls
 * worm-core ``POST /api/v1/people``); on success the parent flow
 * proceeds to the connector-specific connect step. Org-size is collected
 * for product analytics + for the wizard's domain-pack default.
 */
import { useState, type FormEvent } from "react";

const ORG_SIZES = [
  { value: "1", label: "Just me" },
  { value: "2-10", label: "2-10" },
  { value: "11-50", label: "11-50" },
  { value: "51-200", label: "51-200" },
  { value: "200+", label: "200+" },
];

const POSITIONS = [
  "founder",
  "ceo",
  "cfo",
  "cto",
  "cdo",
  "vp_engineering",
  "vp_data",
  "data_engineer",
  "analytics_engineer",
  "data_analyst",
  "data_scientist",
  "ml_engineer",
  "operations",
  "finance",
  "other",
];

export interface IdentitySubmitArgs {
  name: string;
  email: string;
  position: string;
  orgSize: string;
}

export function IdentityForm({
  onSubmitted,
  connectorKind,
  connectorLabel,
}: {
  onSubmitted: (args: IdentitySubmitArgs) => Promise<void> | void;
  connectorKind: string;
  connectorLabel: string;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [position, setPosition] = useState("");
  const [orgSize, setOrgSize] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim() || !email.trim() || !position.trim() || !orgSize.trim()) {
      setError("All fields are required");
      return;
    }
    setBusy(true);
    try {
      await onSubmitted({
        name: name.trim(),
        email: email.trim(),
        position: position.trim(),
        orgSize: orgSize.trim(),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      data-testid="identity-form"
      data-connector-kind={connectorKind}
      onSubmit={onSubmit}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 14,
        border: "1px solid var(--wb-color-paper-edge)",
        background: "var(--wb-color-paper)",
        padding: 20,
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
          tell us about you
        </span>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 20,
            fontWeight: 500,
          }}
        >
          Connect {connectorLabel}
        </h3>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-aged-ink-soft)",
            fontSize: 13,
            lineHeight: 1.5,
          }}
        >
          {connectorLabel} doesn't carry your identity. Four fields and we'll
          provision your tenant; the worm starts cascading the moment your
          source connects.
        </p>
      </header>

      <Field label="Name" htmlFor="identity-name">
        <input
          id="identity-name"
          data-testid="identity-name-input"
          type="text"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="name"
          style={inputStyle}
        />
      </Field>

      <Field label="Email" htmlFor="identity-email">
        <input
          id="identity-email"
          data-testid="identity-email-input"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          style={inputStyle}
        />
      </Field>

      <Field label="Position" htmlFor="identity-position">
        <select
          id="identity-position"
          data-testid="identity-position-select"
          required
          value={position}
          onChange={(e) => setPosition(e.target.value)}
          style={inputStyle}
        >
          <option value="">Pick one…</option>
          {POSITIONS.map((p) => (
            <option key={p} value={p}>
              {p.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Org size" htmlFor="identity-org-size">
        <select
          id="identity-org-size"
          data-testid="identity-org-size-select"
          required
          value={orgSize}
          onChange={(e) => setOrgSize(e.target.value)}
          style={inputStyle}
        >
          <option value="">Pick one…</option>
          {ORG_SIZES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </Field>

      {error ? (
        <div
          data-testid="identity-form-error"
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-sepia-warning-deep)",
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            background: "var(--wb-color-sepia-warning-soft)",
            padding: "8px 12px",
          }}
        >
          {error}
        </div>
      ) : null}

      <button
        type="submit"
        data-testid="identity-submit-button"
        disabled={busy}
        className="wb-mono"
        style={{
          fontSize: 12,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "10px 16px",
          border: "1px solid var(--wb-color-aged-ink)",
          background: busy
            ? "var(--wb-color-paper-deep)"
            : "var(--wb-color-botanical-green-soft)",
          color: "var(--wb-color-aged-ink)",
          cursor: busy ? "wait" : "pointer",
          borderRadius: 0,
          alignSelf: "flex-start",
        }}
      >
        {busy ? "connecting…" : `connect ${connectorLabel.toLowerCase()}`}
      </button>
    </form>
  );
}

const inputStyle: React.CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontSize: 14,
  padding: "8px 10px",
  border: "1px solid var(--wb-color-paper-edge)",
  background: "var(--wb-color-paper)",
  borderRadius: 0,
};

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <label
      htmlFor={htmlFor}
      style={{ display: "flex", flexDirection: "column", gap: 4 }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {label}
      </span>
      {children}
    </label>
  );
}
