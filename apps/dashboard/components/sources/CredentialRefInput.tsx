"use client";
/**
 * CredentialRefInput — operator-paste broker slot key for opaque-secret kinds.
 *
 * Carry-forward #1 from the 2026-06-10 CredentialBroker integration
 * close-out, closed by the 2026-06-10 source-builder credential_ref
 * threading bundle.
 *
 * Renders only when ``connectorKind`` is in
 * :data:`OPAQUE_SECRET_CONNECTOR_KINDS` (stripe / salesforce / hubspot /
 * gsheets). URI-shaped kinds (csv_local / postgres / etc.) reconstruct
 * their auth handle from the proposed URI and never need this field —
 * so the component returns ``null`` for them, keeping the picker form
 * honest about what each kind actually requires.
 *
 * Design choice (read-only broker posture):
 * The broker is operator-provisioned out-of-band — secrets land in
 * Vault / a secrets dir via ops process, not via the app server. The
 * dashboard therefore does NOT accept the raw secret; it accepts the
 * operator-known REFERENCE (vault path, env var name, secrets-dir slot
 * key) the broker uses to look up the secret. This keeps the dashboard
 * out of the secret-handling perimeter and aligns with the SaaS
 * deployment story where secrets cross the customer/vendor boundary
 * via the operator, not via a form submit.
 *
 * When the operator hasn't yet provisioned the slot, they can submit
 * the propose without a credential_ref — the source will land in
 * ``proposed`` state and the sampler will return honest-empty until
 * the operator pastes a ref and re-runs.
 */

import { isOpaqueSecretKind } from "../../lib/opaque-secret-connectors";

export interface CredentialRefInputProps {
  /** Connector kind from the picker — gates rendering. */
  connectorKind: string;
  /** Current value (controlled). */
  value: string;
  /** Change handler — parent owns state. */
  onChange: (value: string) => void;
  /** Optional: render disabled (e.g. during a submit). */
  disabled?: boolean;
}

export function CredentialRefInput({
  connectorKind,
  value,
  onChange,
  disabled,
}: CredentialRefInputProps) {
  if (!isOpaqueSecretKind(connectorKind)) {
    return null;
  }
  const placeholder = placeholderForKind(connectorKind);
  return (
    <section
      data-testid="credential-ref-input"
      data-connector-kind={connectorKind}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        border: "1px solid var(--wb-color-aged-ink)",
        padding: 14,
        background: "var(--wb-color-paper-deep)",
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        Credential broker reference
      </span>
      <label
        className="wb-mono"
        htmlFor="credential-ref"
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        Broker slot key
        <input
          id="credential-ref"
          data-testid="credential-ref-input-field"
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          placeholder={placeholder}
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: 13,
            padding: "6px 8px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-paper)",
            borderRadius: 0,
            color: "var(--wb-color-aged-ink)",
          }}
        />
      </label>
      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 12,
          fontStyle: "italic",
          lineHeight: 1.5,
          color: "var(--wb-color-aged-ink)",
        }}
      >
        Opaque-secret connectors ({connectorKind}) require a{" "}
        <strong>CredentialBroker</strong> reference — the slot key your
        operator provisioned out-of-band (vault path, env var name, or
        secrets-dir slot key). The dashboard never receives the raw
        secret; only the reference. Optional at propose time: if the
        slot isn{"'"}t provisioned yet, leave it blank and the source
        lands in <span className="wb-mono">proposed</span> state — the
        sampler will return empty until a ref is added.
      </p>
      <a
        href="/docs/credential-broker"
        className="wb-mono"
        data-testid="credential-ref-input-help"
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wb-color-aged-ink)",
        }}
      >
        How to configure the broker →
      </a>
    </section>
  );
}

function placeholderForKind(kind: string): string {
  switch (kind) {
    case "stripe":
      return "stripe-prod (vault path or env var name)";
    case "salesforce":
      return "salesforce-acme";
    case "hubspot":
      return "hubspot-prod";
    case "gsheets":
      return "gsheets-finance";
    default:
      return "broker slot key";
  }
}
