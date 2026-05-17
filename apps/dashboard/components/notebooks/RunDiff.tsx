"use client";
/**
 * RunDiff — side-by-side diff of two notebook runs.
 *
 * Cell-by-cell comparison; runs that differ in content_hash get a tone-flagged
 * row. Used for sanity-checking replay determinism (PRD §16 acceptance gate m).
 */
import type { NotebookRunRow } from "../../lib/ledger-client.types";

interface CellOutput {
  status?: string;
  stdout?: string;
  value?: unknown;
}

interface Props {
  runA: NotebookRunRow;
  runB: NotebookRunRow;
}

const PRE_STYLE: React.CSSProperties = {
  background: "var(--wb-color-paper-deep)",
  border: "1px solid var(--wb-color-paper-edge)",
  padding: "8px 10px",
  fontFamily: "var(--wb-font-mono)",
  fontSize: 11,
  whiteSpace: "pre-wrap",
  margin: 0,
};

function summarize(o: CellOutput | undefined): string {
  if (!o) return "(no output)";
  return (
    (o.stdout ?? "") +
    (o.value !== undefined && o.value !== null
      ? `\n=> ${JSON.stringify(o.value)}`
      : "")
  );
}

export function RunDiff({ runA, runB }: Props) {
  const cellsA = (runA.cellOutputs ?? []) as CellOutput[];
  const cellsB = (runB.cellOutputs ?? []) as CellOutput[];
  const maxCells = Math.max(cellsA.length, cellsB.length);
  const sameStateHash = runA.kernelStateHash === runB.kernelStateHash;

  return (
    <section data-testid="run-diff" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <header style={{ display: "flex", justifyContent: "space-between" }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            color: sameStateHash
              ? "var(--wb-color-botanical-green-deep)"
              : "var(--wb-color-sepia-warning-deep)",
          }}
        >
          {sameStateHash
            ? "kernel_state_hash matches — runs are deterministic"
            : "kernel_state_hash differs — runs diverged"}
        </span>
        <span
          className="wb-mono"
          style={{ fontSize: 11, color: "var(--wb-color-hash-gray)" }}
        >
          {runA.runId.slice(0, 8)}… vs {runB.runId.slice(0, 8)}…
        </span>
      </header>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 8,
        }}
      >
        {Array.from({ length: maxCells }).map((_, idx) => (
          <article
            key={idx}
            data-testid={`run-diff-cell-${idx}`}
            style={{ display: "contents" }}
          >
            <pre style={PRE_STYLE}>{summarize(cellsA[idx])}</pre>
            <pre style={PRE_STYLE}>{summarize(cellsB[idx])}</pre>
          </article>
        ))}
      </div>
    </section>
  );
}
