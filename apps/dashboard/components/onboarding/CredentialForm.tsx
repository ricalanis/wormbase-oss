"use client";
/**
 * CredentialForm — Tier 1 credential paste form (Block G3 / PRD §17).
 *
 * Schema-driven from a connector catalog entry. Combines the
 * IdentityForm (name + email + position + org_size) with the
 * connector's JSON-schema fields (DSN, API key, etc.) into a single
 * submission.
 *
 * On submit, POSTs to /onboarding/connect/{kind}/connect which:
 *   1. proposeInstaller_FromForm (writes installer Person + roles +
 *      emit_install_completed).
 *   2. Calls the Python connector's authenticate + discover via
 *      worm-core (a connector-bridge endpoint, scoped to this kind).
 *   3. Writes emit_source_proposed + bronze + silver + gold cascade.
 *   4. Returns a redirect target (typically /onboarding/whats-next).
 *
 * The page never stores plaintext credentials — they're sent over HTTPS
 * to the dashboard's connect handler, KMS-wrapped via lib/server/install,
 * and the wrapped reference is what reaches the ledger.
 */
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import type {
  ConnectorCatalogEntry,
  ConnectorJsonField,
} from "../../lib/lake-surfaces-catalog";
import { IdentityForm, type IdentitySubmitArgs } from "./IdentityForm";

type CredentialValues = Record<string, string>;

export function CredentialForm({
  connector,
}: {
  connector: ConnectorCatalogEntry;
}) {
  const router = useRouter();
  const [phase, setPhase] = useState<"identity" | "credentials" | "submitting">(
    "identity",
  );
  const [identity, setIdentity] = useState<IdentitySubmitArgs | null>(null);
  const [creds, setCreds] = useState<CredentialValues>({});
  const [error, setError] = useState<string | null>(null);

  function onIdentitySubmitted(args: IdentitySubmitArgs) {
    setIdentity(args);
    setPhase("credentials");
  }

  async function onCredentialsSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!identity) return;
    for (const f of connector.fields) {
      if (f.required && !creds[f.name]?.trim()) {
        setError(`${f.label} is required`);
        return;
      }
    }
    setPhase("submitting");
    try {
      const res = await fetch(
        `/onboarding/connect/${connector.kind}/connect`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ identity, credentials: creds }),
        },
      );
      const text = await res.text();
      let body: { redirect?: string; error?: string };
      try {
        body = JSON.parse(text);
      } catch {
        throw new Error(`server returned non-JSON: ${text.slice(0, 200)}`);
      }
      if (!res.ok) {
        throw new Error(body.error || `connect failed (${res.status})`);
      }
      router.push(body.redirect || "/onboarding/whats-next");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("credentials");
    }
  }

  if (phase === "identity") {
    return (
      <IdentityForm
        connectorKind={connector.kind}
        connectorLabel={connector.label}
        onSubmitted={onIdentitySubmitted}
      />
    );
  }

  return (
    <form
      data-testid="credential-form"
      data-connector-kind={connector.kind}
      onSubmit={onCredentialsSubmit}
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
          credentials
        </span>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 20,
            fontWeight: 500,
          }}
        >
          {connector.label}
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
          Credentials reach worm-core over HTTPS, are KMS-wrapped, and only
          the opaque reference enters the ledger. Plaintext is never persisted.
        </p>
      </header>

      {connector.fields.map((f) => (
        <CredentialField
          key={f.name}
          field={f}
          value={creds[f.name] ?? ""}
          onChange={(v) =>
            setCreds((prev) => ({ ...prev, [f.name]: v }))
          }
        />
      ))}

      {error ? (
        <div
          data-testid="credential-form-error"
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
        data-testid="credential-submit-button"
        disabled={phase === "submitting"}
        className="wb-mono"
        style={{
          fontSize: 12,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "10px 16px",
          border: "1px solid var(--wb-color-aged-ink)",
          background:
            phase === "submitting"
              ? "var(--wb-color-paper-deep)"
              : "var(--wb-color-botanical-green-soft)",
          color: "var(--wb-color-aged-ink)",
          cursor: phase === "submitting" ? "wait" : "pointer",
          borderRadius: 0,
          alignSelf: "flex-start",
        }}
      >
        {phase === "submitting" ? "connecting…" : "connect & cascade"}
      </button>
    </form>
  );
}

function CredentialField({
  field,
  value,
  onChange,
}: {
  field: ConnectorJsonField;
  value: string;
  onChange: (v: string) => void;
}) {
  const inputType =
    field.type === "password"
      ? "password"
      : field.type === "number"
        ? "number"
        : "text";
  return (
    <label
      htmlFor={`cred-${field.name}`}
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
        {field.label}
        {field.required ? " *" : ""}
      </span>
      <input
        id={`cred-${field.name}`}
        data-testid={`credential-field-${field.name}`}
        type={inputType}
        required={field.required}
        placeholder={field.placeholder ?? ""}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        style={{
          fontFamily:
            field.type === "password"
              ? "var(--wb-font-mono)"
              : "var(--wb-font-serif)",
          fontSize: 14,
          padding: "8px 10px",
          border: "1px solid var(--wb-color-paper-edge)",
          background: "var(--wb-color-paper)",
          borderRadius: 0,
        }}
      />
      {field.description ? (
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 11,
            color: "var(--wb-color-aged-ink-soft)",
          }}
        >
          {field.description}
        </span>
      ) : null}
    </label>
  );
}
