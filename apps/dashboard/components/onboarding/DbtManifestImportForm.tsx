/**
 * DbtManifestImportForm — admin form for /onboarding/connect/dbt-manifest
 * (Wave 3.2 Hole #2).
 *
 * Fields:
 *   * `manifest_uri` — free text, required. Local path, https URL, or
 *     `dbt-cloud://` reference resolved by worm-core's CatalogMirror layer.
 *   * `domain_id` — select bound to existing governance domains. Required.
 *     The imported tables are tagged with this domain at ingest time.
 *
 * Submission calls the injected `importAction` server action. On success
 * (`{ok: true, sourceId}`), the form navigates to `/sources`. On failure,
 * the error string from the action surfaces inline; the form stays mounted
 * so the admin can retry.
 *
 * Empty-state copy when no domains exist: a callout points to Tier 2
 * onboarding (`/onboarding/tier2` is where the domain pack lands).
 */

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type {
  ImportDbtManifestFormData,
  ImportDbtManifestResult,
} from "../../app/onboarding/connect/dbt-manifest/actions";
import type { DomainRow } from "../../lib/ledger-client.types";

type Action = (
  formData: ImportDbtManifestFormData,
) => Promise<ImportDbtManifestResult>;

export interface DbtManifestImportFormProps {
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
  manifestUri: string;
  domainId: string;
}

export function DbtManifestImportForm({
  domains,
  importAction,
}: DbtManifestImportFormProps): JSX.Element {
  const router = useRouter();
  const [form, setForm] = useState<FormState>({
    manifestUri: "",
    domainId: domains[0]?.domainId ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit(): void {
    setError(null);
    startTransition(async () => {
      const result = await importAction({
        manifestUri: form.manifestUri.trim(),
        domainId: form.domainId,
      });
      if (result.ok && result.sourceId) {
        router.push("/sources");
      } else {
        setError(result.error ?? "unknown error");
      }
    });
  }

  const submitDisabled =
    pending ||
    form.manifestUri.trim().length === 0 ||
    form.domainId.length === 0;

  return (
    <form
      data-testid="dbt-manifest-import-form"
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
        Manifest URI
        <input
          type="text"
          required
          maxLength={1024}
          data-testid="dbt-manifest-uri"
          value={form.manifestUri}
          onChange={(e) =>
            setForm((f) => ({ ...f, manifestUri: e.target.value }))
          }
          style={INPUT_STYLE}
          placeholder="e.g. https://artifacts.example.com/dbt/manifest.json"
        />
        <span
          style={{
            fontFamily: "var(--wb-font-serif, Georgia, serif)",
            fontStyle: "italic",
            fontSize: 11,
            color: "var(--wb-color-hash-gray, #6b6256)",
          }}
        >
          Local path, https URL, or <code>dbt-cloud://&lt;account&gt;/&lt;project&gt;</code>{" "}
          reference. The CatalogMirror layer resolves the manifest at ingest time.
        </span>
      </label>

      <label style={LABEL_STYLE}>
        Bind to domain
        {domains.length === 0 ? (
          <p
            data-testid="dbt-manifest-domains-empty"
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
            data-testid="dbt-manifest-domain"
            value={form.domainId}
            onChange={(e) =>
              setForm((f) => ({ ...f, domainId: e.target.value }))
            }
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

      {error ? (
        <p
          data-testid="dbt-manifest-import-error"
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
          data-testid="dbt-manifest-submit"
          disabled={submitDisabled}
          style={{
            ...BUTTON_PRIMARY,
            opacity: submitDisabled ? 0.6 : 1,
            cursor: submitDisabled ? "default" : "pointer",
          }}
        >
          {pending ? "Importing…" : "Import manifest"}
        </button>
        <Link
          href="/onboarding/tier3"
          data-testid="dbt-manifest-cancel"
          style={BUTTON_GHOST}
        >
          Cancel
        </Link>
      </div>
    </form>
  );
}
