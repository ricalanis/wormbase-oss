"use client";
/**
 * DataProductDrawer — drill-in view for one data product.
 *
 * F3 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Renders:
 * - Header with name + kind + status chip + receipt
 * - Source hashes (the audit trail of what fed this artifact)
 * - Replay button (POST /api/data-products/{id}/regenerate)
 * - Consumption history table
 * - Inline preview of the artifact (HTML / JSON / image — best-effort)
 *
 * Records a consumption event on mount via POST /api/data-products/{id}/consume
 * (surface=dashboard) so the consumption trace stays accurate.
 */
import { useEffect, useState } from "react";
import type {
  DataProductRow,
  DataProductRunRow,
  DataProductConsumptionRow,
} from "../../lib/ledger-client.types";
import { chipStyle } from "../people/_styles";

interface Props {
  dataProduct: DataProductRow;
  runs: DataProductRunRow[];
  consumption: DataProductConsumptionRow[];
}

export function DataProductDrawer({
  dataProduct,
  runs,
  consumption,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Best-effort consumption record on mount. We swallow errors — failure to
  // record consumption shouldn't block the drawer from rendering.
  useEffect(() => {
    fetch(`/api/data-products/${dataProduct.dataProductId}/consume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ surface: "dashboard" }),
    }).catch(() => {});
  }, [dataProduct.dataProductId]);

  async function handleReplay() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/data-products/${dataProduct.dataProductId}/regenerate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        },
      );
      if (!res.ok) {
        setError(`replay failed (${res.status})`);
      } else {
        // Page reloads to surface the new run.
        window.location.reload();
      }
    } catch (err) {
      setError(`replay failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const latestRun = runs.length > 0 ? runs[runs.length - 1] : null;

  return (
    <div data-testid="data-product-drawer" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <header style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 28,
            fontWeight: 500,
          }}
        >
          {dataProduct.name}
        </h1>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={chipStyle("neutral")}>{dataProduct.kind}</span>
          <span
            style={chipStyle(
              dataProduct.status === "generated"
                ? "green"
                : dataProduct.status === "archived"
                  ? "muted"
                  : "sepia",
            )}
          >
            {dataProduct.status}
          </span>
          <span
            className="wb-mono"
            style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
          >
            {dataProduct.dataProductId}
          </span>
        </div>
      </header>

      <section>
        <h2
          style={{
            margin: "0 0 8px 0",
            fontFamily: "var(--wb-font-serif)",
            fontSize: 16,
            fontWeight: 500,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          Provenance
        </h2>
        <dl
          className="wb-mono"
          style={{
            display: "grid",
            gridTemplateColumns: "max-content 1fr",
            gap: "4px 16px",
            fontSize: 12,
            margin: 0,
          }}
        >
          <dt>Content hash</dt>
          <dd style={{ margin: 0 }}>{dataProduct.contentHash ?? "—"}</dd>
          <dt>Contents URI</dt>
          <dd style={{ margin: 0, wordBreak: "break-all" }}>
            {dataProduct.contentsUri ?? "—"}
          </dd>
          <dt>Generated at</dt>
          <dd style={{ margin: 0 }}>
            {dataProduct.generatedAt
              ? new Date(dataProduct.generatedAt).toISOString()
              : "—"}
          </dd>
          <dt>Source hashes</dt>
          <dd style={{ margin: 0 }}>
            {latestRun?.sourceHashes.length
              ? latestRun.sourceHashes.join(", ")
              : "—"}
          </dd>
        </dl>
      </section>

      <section>
        <button
          onClick={handleReplay}
          disabled={busy}
          data-testid="replay-button"
          style={{
            fontFamily: "var(--wb-font-mono)",
            fontSize: 12,
            textTransform: "uppercase",
            letterSpacing: "0.1em",
            padding: "8px 16px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: busy
              ? "var(--wb-color-paper-deep)"
              : "var(--wb-color-paper)",
            color: "var(--wb-color-aged-ink)",
            cursor: busy ? "wait" : "pointer",
            borderRadius: 0,
          }}
        >
          {busy ? "Replaying…" : "Replay against pinned source-hashes"}
        </button>
        {error ? (
          <p
            style={{
              margin: "8px 0 0",
              color: "var(--wb-color-sepia-warning-deep)",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 11,
            }}
          >
            {error}
          </p>
        ) : null}
      </section>

      <section>
        <h2
          style={{
            margin: "0 0 8px 0",
            fontFamily: "var(--wb-font-serif)",
            fontSize: 16,
            fontWeight: 500,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          Run history ({runs.length})
        </h2>
        {runs.length === 0 ? (
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            No runs yet.
          </p>
        ) : (
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 12,
              borderTop: "1px solid var(--wb-color-aged-ink)",
            }}
          >
            <thead>
              <tr style={{ borderBottom: "1px solid var(--wb-color-paper-edge)" }}>
                <th style={{ textAlign: "left", padding: "6px 8px" }}>ts</th>
                <th style={{ textAlign: "left", padding: "6px 8px" }}>by</th>
                <th style={{ textAlign: "left", padding: "6px 8px" }}>
                  content_hash
                </th>
                <th style={{ textAlign: "left", padding: "6px 8px" }}>ms</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr
                  key={r.runId}
                  style={{ borderBottom: "1px solid var(--wb-color-paper-edge)" }}
                >
                  <td style={{ padding: "6px 8px" }}>
                    {new Date(r.ts).toISOString().slice(0, 19)}Z
                  </td>
                  <td style={{ padding: "6px 8px" }}>{r.generatedBy}</td>
                  <td style={{ padding: "6px 8px" }}>
                    {r.contentHash.slice(0, 12)}…
                  </td>
                  <td style={{ padding: "6px 8px" }}>{r.durationMs}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2
          style={{
            margin: "0 0 8px 0",
            fontFamily: "var(--wb-font-serif)",
            fontSize: 16,
            fontWeight: 500,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          }}
        >
          Consumption ({consumption.length})
        </h2>
        {consumption.length === 0 ? (
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            No views recorded yet.
          </p>
        ) : (
          <ul
            className="wb-mono"
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              fontSize: 12,
              display: "flex",
              flexDirection: "column",
              gap: 4,
            }}
          >
            {consumption.map((c) => (
              <li
                key={c.consumptionId}
                style={{ color: "var(--wb-color-hash-gray)" }}
              >
                <span>{new Date(c.ts).toISOString().slice(0, 19)}Z</span>
                {" — "}
                <span>{c.surface}</span>
                {" — "}
                <span>{c.personId.slice(0, 8)}…</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
