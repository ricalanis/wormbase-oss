"use client";
/**
 * ConnectorConfigForm — dynamic form generated from a Connector's
 * field schema.
 *
 * D4 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * For Thursday this is a hand-rolled simple resolver — the field set
 * is small (3-6 fields per connector) and homogeneous (string /
 * password / number / boolean), so importing react-jsonschema-form
 * and its zoo of dependencies isn't worth the bundle weight. When
 * connectors gain conditional fields or oneOf shapes we'll swap in.
 *
 * Submit posts to /api/sources/propose with the connector kind +
 * the field map; the existing source-propose route handles
 * downstream PEVR write.
 */
import { useState } from "react";
import type {
  ConnectorCatalogEntry,
  ConnectorJsonField,
} from "../../lib/lake-surfaces-catalog";

export function ConnectorConfigForm({
  connector,
}: {
  connector: ConnectorCatalogEntry;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function update(field: string, v: string) {
    setValues((prev) => ({ ...prev, [field]: v }));
  }

  function validate(): string | null {
    for (const f of connector.fields) {
      if (f.required && !values[f.name]?.trim()) {
        return `${f.label} is required`;
      }
    }
    return null;
  }

  async function submit() {
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setError(null);
    setResult(null);
    setBusy(true);
    try {
      const res = await fetch("/api/sources/propose", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          kind: connector.kind,
          config: values,
          flow: "dashboard_form",
        }),
      });
      if (!res.ok) {
        const t = await res.text();
        setError(`propose failed: ${res.status} ${t}`);
        return;
      }
      const j = (await res.json().catch(() => null)) as {
        sourceId?: string;
      } | null;
      setResult(j?.sourceId ? `proposed source ${j.sourceId}` : "proposed");
    } catch (err) {
      setError((err as Error).message ?? String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      data-testid={`connector-config-form-${connector.kind}`}
      aria-label={`Configure ${connector.label}`}
      style={{
        border: "1px solid var(--wb-color-aged-ink)",
        padding: 18,
        display: "flex",
        flexDirection: "column",
        gap: 12,
        background: "var(--wb-color-paper)",
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
          configure connector · {connector.kind}
        </span>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 18,
          }}
        >
          {connector.label}
        </h3>
      </header>
      {connector.status === "preview" ? (
        <div
          data-testid={`connector-preview-banner-${connector.kind}`}
          role="note"
          style={{
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            background: "var(--wb-color-paper-deep)",
            padding: 10,
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
            {connector.statusNote}
          </span>
        </div>
      ) : null}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {connector.fields.map((f) => (
          <FormField
            key={f.name}
            field={f}
            value={values[f.name] ?? ""}
            onChange={(v) => update(f.name, v)}
          />
        ))}
      </div>
      {error ? (
        <div
          data-testid="connector-config-error"
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-sepia-warning-deep)",
          }}
        >
          {error}
        </div>
      ) : null}
      {result ? (
        <div
          data-testid="connector-config-result"
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-botanical-green-deep)",
          }}
        >
          {result}
        </div>
      ) : null}
      <button
        type="button"
        data-testid="connector-config-submit"
        onClick={submit}
        disabled={busy}
        className="wb-mono"
        style={{
          alignSelf: "flex-start",
          fontSize: 11,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "8px 14px",
          border: "1px solid var(--wb-color-aged-ink)",
          background: "var(--wb-color-botanical-green-soft)",
          color: "var(--wb-color-aged-ink)",
          cursor: busy ? "wait" : "pointer",
          borderRadius: 0,
        }}
      >
        {busy ? "proposing…" : "propose source"}
      </button>
    </section>
  );
}

function FormField({
  field,
  value,
  onChange,
}: {
  field: ConnectorJsonField;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label
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
      {field.label}
      {field.required ? (
        <span style={{ color: "var(--wb-color-sepia-warning-deep)" }}>
          {" *"}
        </span>
      ) : null}
      <input
        data-testid={`connector-config-field-${field.name}`}
        type={field.type === "password" ? "password" : "text"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={field.placeholder ?? ""}
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
      {field.description ? (
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
          {field.description}
        </span>
      ) : null}
    </label>
  );
}
