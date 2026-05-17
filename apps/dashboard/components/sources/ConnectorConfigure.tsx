"use client";
/**
 * ConnectorConfigure — the per-connector configuration body.
 *
 * W2.A5 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Owns the field map state for one connector kind. Surfaces:
 *   - Field inputs generated from `entry.config_schema`
 *   - A `TestConnectionPanel` that calls
 *     `/api/v1/connectors/test/{kind}` (which proxies to worm-core)
 *   - A "propose source" button that POSTs to `/api/sources/propose`
 *     with the field map + last successful test hash. Disabled
 *     until at least one passing test result lands.
 *
 * Coming-soon connectors render a banner + disabled form — the
 * worm-core test endpoint rejects coming-soon kinds with 409 so
 * the picker UI never lies about capability.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { ConnectorEntry } from "../../app/api/v1/connectors/list/route";
import {
  TestConnectionPanel,
  type TestResult,
  configIsComplete,
} from "./TestConnectionPanel";
import { CredentialRefInput } from "./CredentialRefInput";
import { isOpaqueSecretKind } from "../../lib/opaque-secret-connectors";

export function ConnectorConfigure({ entry }: { entry: ConnectorEntry }) {
  const router = useRouter();
  const [values, setValues] = useState<Record<string, string>>({});
  const [lastTest, setLastTest] = useState<TestResult | null>(null);
  const [proposing, setProposing] = useState(false);
  const [proposeError, setProposeError] = useState<string | null>(null);
  // ``credentialRef`` is the operator-pasted broker slot key for
  // opaque-secret connectors. Empty for URI-shaped kinds — the
  // CredentialRefInput component returns null when kind is not opaque,
  // so the value never leaves "" for those flows.
  const [credentialRef, setCredentialRef] = useState<string>("");

  const isComingSoon = entry.status === "coming_soon";
  const complete = configIsComplete(entry.config_schema, values);
  const opaqueKind = isOpaqueSecretKind(entry.kind);

  function setField(name: string, v: string) {
    setValues((prev) => ({ ...prev, [name]: v }));
    // Mutating any field invalidates the previous test result —
    // capability honesty: the receipt belonged to the old config.
    if (lastTest) setLastTest(null);
  }

  async function proposeSource() {
    if (!lastTest?.ok) return;
    setProposing(true);
    setProposeError(null);
    try {
      const trimmedRef = credentialRef.trim();
      const res = await fetch("/api/sources/propose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: entry.kind,
          uri: deriveUri(entry, values),
          owner: "dashboard",
          classification:
            entry.classification_hints[0] ?? "internal",
          credential_ref: opaqueKind && trimmedRef ? trimmedRef : null,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        setProposeError(`propose failed: ${res.status} ${text.slice(0, 200)}`);
        return;
      }
      router.push("/sources");
    } catch (err) {
      setProposeError((err as Error).message ?? String(err));
    } finally {
      setProposing(false);
    }
  }

  if (isComingSoon) {
    return (
      <section
        data-testid="connector-coming-soon-banner"
        style={{
          border: "1px solid var(--wb-color-hash-gray)",
          background: "var(--wb-color-paper-deep)",
          padding: 18,
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
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
          coming soon
        </span>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            color: "var(--wb-color-aged-ink)",
            lineHeight: 1.5,
          }}
        >
          {entry.status_note} The configure form is intentionally disabled
          until the implementation lands so the picker stays
          capability-honest. Watch the changelog or pin the issue.
        </p>
      </section>
    );
  }

  return (
    <section
      data-testid={`connector-configure-${entry.kind}`}
      style={{ display: "flex", flexDirection: "column", gap: 14 }}
    >
      {entry.status === "preview" ? (
        <div
          data-testid="connector-preview-banner"
          role="note"
          style={{
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            background: "var(--wb-color-paper-deep)",
            padding: 12,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-sepia-warning-deep)",
            }}
          >
            preview connector
          </span>
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontSize: 12,
              color: "var(--wb-color-aged-ink)",
              lineHeight: 1.5,
            }}
          >
            {entry.status_note}
          </span>
        </div>
      ) : null}

      <div
        data-testid="connector-config-fields"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          border: "1px solid var(--wb-color-aged-ink)",
          padding: 18,
          background: "var(--wb-color-paper)",
        }}
      >
        {entry.config_schema.length === 0 ? (
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              fontSize: 12,
              color: "var(--wb-color-hash-gray)",
            }}
          >
            This connector takes no configuration — auto-detected at
            install time. You can still run a test to verify the runtime
            handle.
          </span>
        ) : (
          entry.config_schema.map((f) => (
            <label
              key={f.name}
              className="wb-mono"
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
              {f.label}
              {f.required ? (
                <span style={{ color: "var(--wb-color-sepia-warning-deep)" }}>
                  {" *"}
                </span>
              ) : null}
              <input
                data-testid={`config-field-${f.name}`}
                type={f.type === "password" ? "password" : "text"}
                value={values[f.name] ?? ""}
                onChange={(e) => setField(f.name, e.target.value)}
                placeholder={f.placeholder ?? ""}
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
              {f.description ? (
                <span
                  style={{
                    fontFamily: "var(--wb-font-serif)",
                    fontStyle: "italic",
                    fontSize: 11,
                    color: "var(--wb-color-hash-gray)",
                    textTransform: "none",
                    letterSpacing: 0,
                  }}
                >
                  {f.description}
                </span>
              ) : null}
            </label>
          ))
        )}
      </div>

      <CredentialRefInput
        connectorKind={entry.kind}
        value={credentialRef}
        onChange={setCredentialRef}
        disabled={proposing}
      />

      <TestConnectionPanel
        kind={entry.kind}
        config={values}
        onResult={(r) => setLastTest(r)}
      />

      <section
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {proposeError ? (
          <div
            data-testid="propose-error"
            className="wb-mono"
            style={{
              fontSize: 11,
              color: "var(--wb-color-sepia-warning-deep)",
              wordBreak: "break-all",
            }}
          >
            {proposeError}
          </div>
        ) : null}
        <button
          type="button"
          data-testid="propose-source-button"
          onClick={proposeSource}
          disabled={!lastTest?.ok || !complete || proposing}
          className="wb-mono"
          style={{
            alignSelf: "flex-start",
            fontSize: 11,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "8px 14px",
            border: "1px solid var(--wb-color-aged-ink)",
            background:
              lastTest?.ok && complete && !proposing
                ? "var(--wb-color-botanical-green-soft)"
                : "var(--wb-color-paper-edge)",
            color: "var(--wb-color-aged-ink)",
            cursor:
              lastTest?.ok && complete && !proposing ? "pointer" : "not-allowed",
            borderRadius: 0,
          }}
        >
          {proposing ? "proposing…" : "propose source"}
        </button>
        {!lastTest?.ok ? (
          <span
            style={{
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              fontSize: 12,
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Run a successful test connection above before proposing — the
            ledger entry references the test hash receipt.
          </span>
        ) : null}
      </section>
    </section>
  );
}

/**
 * Best-effort URI synthesizer — feeds /api/sources/propose's `uri`
 * field. For Postgres this is the DSN (less the password); for CSV
 * it's the path; otherwise the kind label is used as a placeholder.
 */
function deriveUri(
  entry: ConnectorEntry,
  values: Record<string, string>,
): string {
  if (entry.kind === "postgres" && values.dsn) {
    try {
      const u = new URL(values.dsn);
      u.password = "";
      return u.toString();
    } catch {
      return values.dsn.replace(/:[^:@]*@/, ":***@");
    }
  }
  if (entry.kind === "csv_local" && values.path) return values.path;
  if (entry.kind === "http_csv" && values.url) return values.url;
  if (entry.kind === "s3_csv" && values.bucket) {
    const prefix = values.prefix ? `/${values.prefix}` : "";
    return `s3://${values.bucket}${prefix}`;
  }
  if (entry.kind === "snowflake" && values.account) {
    return `snowflake://${values.account}/${values.database ?? ""}`;
  }
  // Default: no URI surfacing — propose endpoint will still write a
  // receipt with a placeholder we can audit via /trace.
  return `${entry.kind}://configured`;
}
