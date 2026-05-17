"use client";
/**
 * TestConnectionPanel — runs Connector.authenticate against the
 * supplied config and renders the result with a hash receipt.
 *
 * W2.A5 of `docs/superpowers/plans/2026-04-28-production-hardening.md`.
 *
 * Calls the dashboard's `/api/v1/connectors/test/{kind}` route which
 * proxies to worm-core's `/api/v1/connectors/{kind}/test` — same code
 * path the source-builder uses at runtime. No stub, no fixture.
 *
 * The hash receipt is deterministic over (kind, handle_id) so an
 * operator can paste it into /trace and find the underlying ledger
 * row when the source is ultimately proposed.
 */
import { useState } from "react";
import type { ConnectorField } from "../../app/api/v1/connectors/list/route";

export interface TestResult {
  ok: boolean;
  kind: string;
  handle_id?: string;
  version?: string;
  hash?: string;
  error?: string;
}

export function TestConnectionPanel({
  kind,
  config,
  onResult,
}: {
  kind: string;
  /** Field map produced by the per-connector form. */
  config: Record<string, unknown>;
  /** Optional callback fired after each test attempt — lets the
   *  parent form decide whether to enable a downstream "create source"
   *  button. */
  onResult?: (result: TestResult) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);

  async function runTest() {
    setBusy(true);
    setResult(null);
    try {
      const res = await fetch(
        `/api/v1/connectors/test/${encodeURIComponent(kind)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ config }),
        },
      );
      const body = (await res.json().catch(() => ({}))) as TestResult;
      const normalized: TestResult = body.ok
        ? body
        : {
            ok: false,
            kind: body.kind ?? kind,
            error:
              typeof body.error === "string"
                ? body.error
                : `request failed: ${res.status}`,
          };
      setResult(normalized);
      onResult?.(normalized);
    } catch (err) {
      const e: TestResult = {
        ok: false,
        kind,
        error: (err as Error).message ?? String(err),
      };
      setResult(e);
      onResult?.(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      data-testid="test-connection-panel"
      aria-label="Test connection"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        border: "1px dashed var(--wb-color-paper-edge)",
        padding: 12,
        background: "var(--wb-color-paper-deep)",
      }}
    >
      <header
        style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}
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
          test connection
        </span>
        <button
          type="button"
          data-testid="test-connection-button"
          onClick={runTest}
          disabled={busy}
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            padding: "6px 12px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: busy
              ? "var(--wb-color-paper-edge)"
              : "var(--wb-color-paper)",
            cursor: busy ? "wait" : "pointer",
            borderRadius: 0,
          }}
        >
          {busy ? "testing…" : "run test"}
        </button>
      </header>
      {result ? (
        result.ok ? (
          <div
            data-testid="test-connection-success"
            style={{ display: "flex", flexDirection: "column", gap: 4 }}
          >
            <span
              className="wb-mono"
              style={{
                fontSize: 11,
                color: "var(--wb-color-botanical-green-deep)",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              ok · authenticated
            </span>
            <span
              data-testid="test-connection-receipt"
              className="wb-mono"
              style={{
                fontSize: 11,
                color: "var(--wb-color-aged-ink)",
                wordBreak: "break-all",
              }}
            >
              receipt {result.hash ?? "—"} · handle {result.handle_id ?? "—"}
              {result.version ? ` · ${result.version}` : ""}
            </span>
          </div>
        ) : (
          <div
            data-testid="test-connection-failure"
            style={{ display: "flex", flexDirection: "column", gap: 4 }}
          >
            <span
              className="wb-mono"
              style={{
                fontSize: 11,
                color: "var(--wb-color-sepia-warning-deep)",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              failed
            </span>
            <span
              className="wb-mono"
              style={{
                fontSize: 11,
                color: "var(--wb-color-aged-ink)",
                wordBreak: "break-all",
              }}
            >
              {result.error ?? "unknown error"}
            </span>
          </div>
        )
      ) : (
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 12,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Click run test to call Connector.authenticate against worm-core
          with the values above. The hash is content-addressed over
          (kind, handle_id).
        </span>
      )}
    </section>
  );
}

/**
 * Helper exposed for tests / per-connector forms — returns true when
 * every required field has a non-empty value.
 */
export function configIsComplete(
  fields: ConnectorField[],
  values: Record<string, unknown>,
): boolean {
  for (const f of fields) {
    if (!f.required) continue;
    const v = values[f.name];
    if (v === undefined || v === null) return false;
    if (typeof v === "string" && v.trim() === "") return false;
  }
  return true;
}
