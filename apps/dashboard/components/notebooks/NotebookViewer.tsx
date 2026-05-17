"use client";
/**
 * NotebookViewer — cell-by-cell display of a notebook with its latest run.
 *
 * Markdown cells render as text (no full markdown engine — Thursday-shippable
 * monospace passthrough). Code cells render in a <pre>. Run outputs surface
 * stdout / value beside their corresponding cell.
 */
import { useState } from "react";
import type {
  NotebookRow,
  NotebookRunRow,
} from "../../lib/ledger-client.types";
import { chipStyle } from "../people/_styles";

interface Props {
  notebook: NotebookRow;
  runs: NotebookRunRow[];
}

interface CellOutput {
  status?: string;
  stdout?: string;
  stderr?: string;
  value?: unknown;
  error?: string | null;
  kind?: string;
}

function statusTone(s: string) {
  if (s === "published") return "green" as const;
  if (s === "run") return "neutral" as const;
  if (s === "archived") return "muted" as const;
  return "sepia" as const;
}

const PRE_STYLE: React.CSSProperties = {
  background: "var(--wb-color-paper-deep)",
  border: "1px solid var(--wb-color-paper-edge)",
  padding: "10px 12px",
  fontFamily: "var(--wb-font-mono)",
  fontSize: 12,
  whiteSpace: "pre-wrap",
  margin: 0,
};

export function NotebookViewer({ notebook, runs }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const latestRun = runs.length > 0 ? runs[runs.length - 1] : null;
  const outputs: CellOutput[] = (latestRun?.cellOutputs ?? []) as CellOutput[];

  async function handleRun() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/notebooks/${notebook.notebookId}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        setError(`run failed (${res.status})`);
      } else {
        window.location.reload();
      }
    } catch (err) {
      setError(`run failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="notebook-viewer" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <header style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 28,
            fontWeight: 500,
          }}
        >
          {notebook.name}
        </h1>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={chipStyle("neutral")}>{notebook.kernel}</span>
          <span style={chipStyle(statusTone(notebook.status))}>
            {notebook.status}
          </span>
          {notebook.version ? (
            <span style={chipStyle("ink")}>v{notebook.version}</span>
          ) : null}
          <span
            className="wb-mono"
            style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
          >
            {notebook.notebookId}
          </span>
        </div>
      </header>

      <section>
        <button
          onClick={handleRun}
          disabled={busy}
          data-testid="notebook-run-button"
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
          {busy ? "Running…" : "Run notebook"}
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

      <section style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {notebook.cells.map((cell, idx) => {
          const out = outputs[idx];
          return (
            <article
              key={idx}
              data-testid={`notebook-cell-${idx}`}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 12,
                borderTop: "1px solid var(--wb-color-paper-edge)",
                paddingTop: 12,
              }}
            >
              <div>
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: "var(--wb-color-hash-gray)",
                  }}
                >
                  cell {idx + 1} · {cell.kind}
                </span>
                {cell.kind === "markdown" ? (
                  <pre
                    style={{
                      ...PRE_STYLE,
                      fontFamily: "var(--wb-font-serif)",
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {cell.source}
                  </pre>
                ) : (
                  <pre style={PRE_STYLE}>{cell.source}</pre>
                )}
              </div>
              <div>
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: "var(--wb-color-hash-gray)",
                  }}
                >
                  output
                  {out?.status ? ` · ${out.status}` : ""}
                </span>
                {out ? (
                  <pre style={PRE_STYLE}>
                    {out.error
                      ? out.error
                      : (out.stdout ?? "") +
                        (out.value !== undefined && out.value !== null
                          ? `\n=> ${JSON.stringify(out.value)}`
                          : "")}
                  </pre>
                ) : (
                  <pre
                    style={{ ...PRE_STYLE, color: "var(--wb-color-hash-gray)" }}
                  >
                    (no run yet)
                  </pre>
                )}
              </div>
            </article>
          );
        })}
      </section>

      {runs.length > 1 ? (
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
            {runs.map((r) => (
              <li
                key={r.runId}
                style={{ color: "var(--wb-color-hash-gray)" }}
              >
                <span>{new Date(r.ts).toISOString().slice(0, 19)}Z</span>
                {" — "}
                <span>{r.status}</span>
                {" — "}
                <span>{r.runBy}</span>
                {" — "}
                <span>{r.durationMs}ms</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
