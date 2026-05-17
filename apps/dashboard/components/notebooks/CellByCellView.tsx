"use client";
/**
 * CellByCellView — render a notebook's cells side-by-side with their
 * latest run outputs.
 *
 * W2.A8 of docs/superpowers/plans/2026-04-28-production-hardening.md.
 *
 * Markdown cells render as paragraphs (light heading parsing for `#`
 * lines — kept as plain prose, no full markdown engine because the
 * surface is intent-conveying not blog-shaped). Code/SQL cells render
 * monospace. Outputs land in the right column with stdout / value /
 * error visible.
 *
 * Empty cell list renders an honest empty-state instead of returning
 * null (per the in-project cleanup checklist: silent panels are demo
 * seams disguised as design).
 */
import type { NotebookCell, NotebookRunRow } from "../../lib/ledger-client.types";

interface Props {
  cells: NotebookCell[];
  /** The latest run; its `cellOutputs` are positional with `cells`. */
  latestRun?: NotebookRunRow | null;
}

interface CellOutput {
  status?: string;
  stdout?: string;
  stderr?: string;
  value?: unknown;
  error?: string | null;
  kind?: string;
}

const PRE_STYLE: React.CSSProperties = {
  background: "var(--wb-color-paper-deep)",
  border: "1px solid var(--wb-color-paper-edge)",
  padding: "10px 12px",
  fontFamily: "var(--wb-font-mono)",
  fontSize: 12,
  whiteSpace: "pre-wrap",
  margin: 0,
  overflowX: "auto",
};

const MARKDOWN_STYLE: React.CSSProperties = {
  ...PRE_STYLE,
  fontFamily: "var(--wb-font-serif)",
  fontSize: 13,
  background: "var(--wb-color-paper)",
};

const LABEL_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono)",
  fontSize: 10,
  letterSpacing: "0.1em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
  display: "block",
  marginBottom: 4,
};

function renderMarkdown(source: string): React.ReactNode {
  // Light pass: split on blank lines, strip leading `#` so the heading
  // text renders as bolded prose. Real markdown engines belong in a
  // separate skill — this view only needs intent.
  const blocks = source.split(/\n\s*\n/);
  return (
    <div style={MARKDOWN_STYLE}>
      {blocks.map((block, i) => {
        const trimmed = block.trim();
        const headingMatch = /^(#{1,6})\s+(.*)$/.exec(trimmed);
        if (headingMatch) {
          return (
            <p
              key={i}
              style={{
                margin: i === 0 ? 0 : "12px 0 0",
                fontWeight: 600,
                fontSize: 14,
              }}
            >
              {headingMatch[2]}
            </p>
          );
        }
        return (
          <p
            key={i}
            style={{
              margin: i === 0 ? 0 : "8px 0 0",
              whiteSpace: "pre-wrap",
            }}
          >
            {trimmed}
          </p>
        );
      })}
    </div>
  );
}

function renderOutput(out: CellOutput | undefined): React.ReactNode {
  if (!out) {
    return (
      <pre style={{ ...PRE_STYLE, color: "var(--wb-color-hash-gray)" }}>
        (no run yet)
      </pre>
    );
  }
  if (out.error) {
    return (
      <pre
        style={{ ...PRE_STYLE, color: "var(--wb-color-sepia-warning-deep)" }}
      >
        {out.error}
      </pre>
    );
  }
  const stdout = out.stdout ?? "";
  const value =
    out.value !== undefined && out.value !== null
      ? `\n=> ${typeof out.value === "string" ? out.value : JSON.stringify(out.value)}`
      : "";
  const text = (stdout + value).trim();
  if (!text) {
    return (
      <pre style={{ ...PRE_STYLE, color: "var(--wb-color-hash-gray)" }}>
        (ok · no output)
      </pre>
    );
  }
  return <pre style={PRE_STYLE}>{text}</pre>;
}

export function CellByCellView({ cells, latestRun }: Props) {
  const outputs: CellOutput[] = (latestRun?.cellOutputs ?? []) as CellOutput[];

  if (cells.length === 0) {
    return (
      <div data-testid="cell-by-cell-empty">
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          This notebook has no cells yet. Add a cell to start.
        </p>
      </div>
    );
  }

  return (
    <section
      data-testid="cell-by-cell-view"
      style={{ display: "flex", flexDirection: "column", gap: 16 }}
    >
      {cells.map((cell, idx) => {
        const out = outputs[idx];
        return (
          <article
            key={idx}
            data-testid={`cell-by-cell-cell-${idx}`}
            data-cell-kind={cell.kind}
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 12,
              borderTop: "1px solid var(--wb-color-paper-edge)",
              paddingTop: 12,
            }}
          >
            <div>
              <span style={LABEL_STYLE}>
                cell {idx + 1} · {cell.kind}
              </span>
              {cell.kind === "markdown" ? (
                renderMarkdown(cell.source)
              ) : (
                <pre style={PRE_STYLE} data-testid={`cell-source-${idx}`}>
                  {cell.source}
                </pre>
              )}
            </div>
            <div>
              <span style={LABEL_STYLE}>
                output{out?.status ? ` · ${out.status}` : ""}
              </span>
              <div data-testid={`cell-output-${idx}`}>{renderOutput(out)}</div>
            </div>
          </article>
        );
      })}
    </section>
  );
}
