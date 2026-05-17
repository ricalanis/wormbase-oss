/**
 * SnowflakeCatalogImportForm — admin form for
 * /onboarding/connect/snowflake-catalog (Wave 3.2 Hole #2).
 *
 * Fields mirror `SnowflakeNativeCatalogSource.required_secrets`:
 *   * `account` — required, Snowflake account locator
 *   * `user` — required, Snowflake user
 *   * `database` — required, target database for INFORMATION_SCHEMA read
 *   * `schema` — required, schema to mirror
 *   * `warehouse` — required, compute warehouse for catalog queries
 *   * `role` — optional, defaults to user's default role
 *   * `domain_id` — required, governance domain binding
 *
 * The form NEVER asks for password / private-key material — credentials
 * are captured server-side via the worm-core CredentialBroker. This form
 * only carries the *shape* of the connection.
 *
 * Submission calls the injected `importAction` server action. On success
 * (`{ok: true, sourceId}`), the form navigates to `/sources`. On failure,
 * the error string surfaces inline; the form stays mounted for retry.
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type {
  ImportSnowflakeCatalogFormData,
  ImportSnowflakeCatalogResult,
} from "../../app/onboarding/connect/snowflake-catalog/actions";
import type { DomainRow } from "../../lib/ledger-client.types";

type Action = (
  formData: ImportSnowflakeCatalogFormData,
) => Promise<ImportSnowflakeCatalogResult>;

export interface SnowflakeCatalogImportFormProps {
  domains: DomainRow[];
  /** Server action injected by the page. Tests pass a stub. */
  importAction: Action;
}

const LABEL_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 13,
};

const INPUT_STYLE: React.CSSProperties = {
  padding: "6px 8px",
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 13,
  background: "var(--wb-color-paper, #f6f1e7)",
};

const BUTTON_PRIMARY: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: 0,
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 13,
  border: "1px solid var(--wb-color-botanical-green-deep, #2a5b3f)",
  background: "var(--wb-color-botanical-green, #3c7a55)",
  color: "var(--wb-color-paper, #f6f1e7)",
  cursor: "pointer",
};

const BUTTON_GHOST: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: 0,
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 13,
  border: "1px solid var(--wb-color-aged-ink, #4b3f2f)",
  background: "transparent",
  color: "var(--wb-color-aged-ink, #4b3f2f)",
  cursor: "pointer",
  textDecoration: "none",
  display: "inline-block",
};

interface FormState {
  account: string;
  user: string;
  database: string;
  schema: string;
  warehouse: string;
  role: string;
  domainId: string;
}

const INITIAL: FormState = {
  account: "",
  user: "",
  database: "",
  schema: "",
  warehouse: "",
  role: "",
  domainId: "",
};

export function SnowflakeCatalogImportForm({
  domains,
  importAction,
}: SnowflakeCatalogImportFormProps): JSX.Element {
  const router = useRouter();
  const [form, setForm] = useState<FormState>({
    ...INITIAL,
    domainId: domains[0]?.domainId ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function set<K extends keyof FormState>(key: K, value: FormState[K]): void {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function submit(): void {
    setError(null);
    startTransition(async () => {
      const result = await importAction({
        account: form.account.trim(),
        user: form.user.trim(),
        database: form.database.trim(),
        schema: form.schema.trim(),
        warehouse: form.warehouse.trim(),
        role: form.role.trim() || undefined,
        domainId: form.domainId,
      });
      if (result.ok && result.sourceId) {
        router.push("/sources");
      } else {
        setError(result.error ?? "unknown error");
      }
    });
  }

  const requiredFilled =
    form.account.trim() &&
    form.user.trim() &&
    form.database.trim() &&
    form.schema.trim() &&
    form.warehouse.trim() &&
    form.domainId;
  const submitDisabled = pending || !requiredFilled;

  return (
    <form
      data-testid="snowflake-catalog-import-form"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        maxWidth: 640,
      }}
    >
      <label style={LABEL_STYLE}>
        Account
        <input
          type="text"
          required
          maxLength={256}
          data-testid="snowflake-account"
          value={form.account}
          onChange={(e) => set("account", e.target.value)}
          style={INPUT_STYLE}
          placeholder="e.g. abc12345.us-east-1.aws"
        />
      </label>

      <label style={LABEL_STYLE}>
        User
        <input
          type="text"
          required
          maxLength={256}
          data-testid="snowflake-user"
          value={form.user}
          onChange={(e) => set("user", e.target.value)}
          style={INPUT_STYLE}
          placeholder="e.g. WORMBASE_INGEST"
        />
      </label>

      <label style={LABEL_STYLE}>
        Database
        <input
          type="text"
          required
          maxLength={256}
          data-testid="snowflake-database"
          value={form.database}
          onChange={(e) => set("database", e.target.value)}
          style={INPUT_STYLE}
          placeholder="e.g. ANALYTICS"
        />
      </label>

      <label style={LABEL_STYLE}>
        Schema
        <input
          type="text"
          required
          maxLength={256}
          data-testid="snowflake-schema"
          value={form.schema}
          onChange={(e) => set("schema", e.target.value)}
          style={INPUT_STYLE}
          placeholder="e.g. MARTS"
        />
      </label>

      <label style={LABEL_STYLE}>
        Warehouse
        <input
          type="text"
          required
          maxLength={256}
          data-testid="snowflake-warehouse"
          value={form.warehouse}
          onChange={(e) => set("warehouse", e.target.value)}
          style={INPUT_STYLE}
          placeholder="e.g. WORMBASE_WH"
        />
      </label>

      <label style={LABEL_STYLE}>
        Role (optional)
        <input
          type="text"
          maxLength={256}
          data-testid="snowflake-role"
          value={form.role}
          onChange={(e) => set("role", e.target.value)}
          style={INPUT_STYLE}
          placeholder="leave blank for user default"
        />
        <span
          style={{
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontStyle: "italic",
            fontSize: 11,
            color: "var(--wb-color-hash-gray, #6b6256)",
          }}
        >
          Defaults to the Snowflake user&apos;s default role when omitted.
        </span>
      </label>

      <label style={LABEL_STYLE}>
        Bind to domain
        {domains.length === 0 ? (
          <p
            data-testid="snowflake-catalog-domains-empty"
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif, Georgia, serif)",
              fontStyle: "italic",
              fontSize: 12,
              color: "var(--wb-color-hash-gray, #6b6256)",
            }}
          >
            No domains yet — add one via{" "}
            <Link href="/onboarding/tier2" style={{ color: "inherit" }}>
              Tier 2 onboarding
            </Link>{" "}
            first. Imported tables need a governance domain at ingest time.
          </p>
        ) : (
          <select
            data-testid="snowflake-catalog-domain"
            value={form.domainId}
            onChange={(e) => set("domainId", e.target.value)}
            style={INPUT_STYLE}
          >
            {domains.map((d) => (
              <option key={d.domainId} value={d.domainId}>
                {d.name}
              </option>
            ))}
          </select>
        )}
      </label>

      <p
        style={{
          margin: 0,
          fontFamily: "var(--wb-font-serif, Georgia, serif)",
          fontStyle: "italic",
          fontSize: 11,
          color: "var(--wb-color-hash-gray, #6b6256)",
        }}
      >
        Credentials are captured server-side via the worm-core CredentialBroker
        after submission. This form only carries the connection shape.
      </p>

      {error ? (
        <p
          data-testid="snowflake-catalog-import-error"
          role="alert"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontSize: 12,
            color: "var(--wb-color-error, #b03a2e)",
            background: "var(--wb-color-error-bg, rgba(176,58,46,0.08))",
            padding: "8px 10px",
            border: "1px solid var(--wb-color-error, #b03a2e)",
          }}
        >
          {error}
        </p>
      ) : null}

      <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
        <button
          type="submit"
          data-testid="snowflake-catalog-submit"
          disabled={Boolean(submitDisabled)}
          style={{
            ...BUTTON_PRIMARY,
            opacity: submitDisabled ? 0.6 : 1,
            cursor: submitDisabled ? "default" : "pointer",
          }}
        >
          {pending ? "Importing…" : "Import Snowflake catalog"}
        </button>
        <Link
          href="/onboarding/tier3"
          data-testid="snowflake-catalog-cancel"
          style={BUTTON_GHOST}
        >
          Cancel
        </Link>
      </div>
    </form>
  );
}
