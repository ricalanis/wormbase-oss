/**
 * decision-chain — pure-logic tests for the Decision → Bytes chain walker
 * (Phase 3 Task 3C).
 *
 * The walker resolves a chain of ledger entries:
 *
 *   decision_recorded  →  process_map_proposed  →  kpi_node  →
 *     source_proposed  →  source_bronzed
 *
 * We test the pure selectors (`selectChainSteps`) so the chain logic is
 * exercised without needing a live Postgres tenant. The DB-bound entry
 * point (`getDecisionChain`) is a thin wrapper that calls these selectors
 * after fetching candidate rows.
 */
import { describe, it, expect } from "vitest";
import {
  selectChainSteps,
  type CandidateLedgerRow,
} from "../../lib/decision-chain";

const sampleRows: CandidateLedgerRow[] = [
  // 1) the decision
  {
    seq: "100",
    tool: "emit_decision_recorded",
    ts: "2026-04-30T08:00:00Z",
    hashHex: "decisionhash00000000000000000000",
    args: {
      decision_id: "dec-q3-close",
      decision_text: "We decided to push Q3 close to Friday.",
      decision_at: "2026-04-30T08:00:00Z",
      channel_id: "C0FINANCE",
      evidence_message_ids: ["msg_111", "msg_222"],
    },
  },
  // 2) a process map for the same channel that cites msg_111
  {
    seq: "90",
    tool: "emit_process_map_proposed",
    ts: "2026-04-29T14:00:00Z",
    hashHex: "processhash000000000000000000000",
    args: {
      process_id: "proc-q3-close",
      process_name: "Q3 close",
      domain: "finance",
      steps: [
        { order: 1, actor: "alice", action: "exports", source_message_id: "msg_111" },
        { order: 2, actor: "bob", action: "reconciles", source_message_id: "msg_333" },
      ],
    },
  },
  // 3) a KPI node referencing the source
  {
    seq: "80",
    tool: "emit_kpi_node",
    ts: "2026-04-29T10:00:00Z",
    hashHex: "kpihash00000000000000000000000000",
    args: {
      id: "revenue.q3",
      name: "Q3 revenue",
      formula: "SUM(amount)",
      source_ids: ["src-finance-csv"],
    },
  },
  // 4) the source proposed
  {
    seq: "70",
    tool: "emit_source_proposed",
    ts: "2026-04-28T12:00:00Z",
    hashHex: "sourcehash0000000000000000000000",
    args: {
      source_id: "src-finance-csv",
      uri: "s3://wormbase/finance/q3.csv",
      source_kind: "csv",
    },
  },
  // 5) bronze
  {
    seq: "75",
    tool: "emit_source_bronzed",
    ts: "2026-04-28T12:05:00Z",
    hashHex: "bronzehash0000000000000000000000",
    args: {
      source_id: "src-finance-csv",
      byte_count: 1024,
      schema_hash: "sha256:abc",
    },
  },
];

describe("selectChainSteps · happy path", () => {
  it("walks decision → process_map → kpi → source → bronze", () => {
    const chain = selectChainSteps(sampleRows, "dec-q3-close");
    expect(chain.decision).not.toBeNull();
    expect(chain.decision!.entryHash).toBe(
      "decisionhash00000000000000000000",
    );
    expect(chain.decision!.kind).toBe("decision_recorded");

    expect(chain.processMap).not.toBeNull();
    expect(chain.processMap!.kind).toBe("process_map_proposed");
    expect(chain.processMap!.entryHash).toBe(
      "processhash000000000000000000000",
    );

    expect(chain.kpi).not.toBeNull();
    expect(chain.kpi!.kind).toBe("kpi_node");
    expect(chain.kpi!.entryHash).toBe("kpihash00000000000000000000000000");

    expect(chain.source).not.toBeNull();
    expect(chain.source!.kind).toBe("source_proposed");
    expect(chain.source!.entryHash).toBe("sourcehash0000000000000000000000");

    expect(chain.bronze).not.toBeNull();
    expect(chain.bronze!.kind).toBe("source_bronzed");
    expect(chain.bronze!.entryHash).toBe("bronzehash0000000000000000000000");

    expect(chain.missing).toEqual([]);
  });

  it("populates each step with a human-readable summary", () => {
    const chain = selectChainSteps(sampleRows, "dec-q3-close");
    expect(chain.decision!.summary.toLowerCase()).toContain("q3 close");
    expect(chain.processMap!.summary.toLowerCase()).toContain("q3 close");
    expect(chain.kpi!.summary.toLowerCase()).toContain("q3 revenue");
    expect(chain.source!.summary).toContain("q3.csv");
    // bytes are locale-formatted ("1,024" or "1024" depending on locale).
    expect(chain.bronze!.summary).toMatch(/1[,.]?024/);
    expect(chain.bronze!.summary).toContain("sha256:abc");
  });
});

describe("selectChainSteps · missing decision", () => {
  it("returns null decision and lists the gap when decision_id not found", () => {
    const chain = selectChainSteps(sampleRows, "dec-not-found");
    expect(chain.decision).toBeNull();
    expect(chain.processMap).toBeNull();
    expect(chain.kpi).toBeNull();
    expect(chain.source).toBeNull();
    expect(chain.bronze).toBeNull();
    expect(chain.missing).toContain("decision_recorded");
  });
});

describe("selectChainSteps · partial chains (don't crash)", () => {
  it("returns process_map=null + missing=['process_map_proposed'] when no process touches evidence", () => {
    const rowsWithoutProcess = sampleRows.filter(
      (r) => r.tool !== "emit_process_map_proposed",
    );
    const chain = selectChainSteps(rowsWithoutProcess, "dec-q3-close");
    expect(chain.decision).not.toBeNull();
    expect(chain.processMap).toBeNull();
    expect(chain.missing).toContain("process_map_proposed");
    // Walking still continues — KPI is independently resolvable.
    expect(chain.kpi).not.toBeNull();
  });

  it("returns kpi=null when no kpi_node exists, but still walks to source via decision channel", () => {
    const rowsWithoutKpi = sampleRows.filter(
      (r) => r.tool !== "emit_kpi_node",
    );
    const chain = selectChainSteps(rowsWithoutKpi, "dec-q3-close");
    expect(chain.kpi).toBeNull();
    expect(chain.missing).toContain("kpi_node");
    // We still find a source as a best-effort tail (most-recent
    // emit_source_proposed for the tenant).
    expect(chain.source).not.toBeNull();
    expect(chain.bronze).not.toBeNull();
  });

  it("returns bronze=null + missing=['source_bronzed'] when no bronze entry exists for the source", () => {
    const rowsWithoutBronze = sampleRows.filter(
      (r) => r.tool !== "emit_source_bronzed",
    );
    const chain = selectChainSteps(rowsWithoutBronze, "dec-q3-close");
    expect(chain.source).not.toBeNull();
    expect(chain.bronze).toBeNull();
    expect(chain.missing).toContain("source_bronzed");
  });
});

describe("selectChainSteps · process-map matching", () => {
  it("prefers a process_map whose step.source_message_id matches an evidence id", () => {
    const extraRows: CandidateLedgerRow[] = [
      ...sampleRows,
      {
        // unrelated process_map for a different channel; should NOT win
        seq: "95",
        tool: "emit_process_map_proposed",
        ts: "2026-04-30T07:00:00Z",
        hashHex: "unrelatedprocesshash0000000000",
        args: {
          process_id: "proc-other",
          process_name: "Other process",
          domain: "marketing",
          steps: [
            { order: 1, actor: "x", action: "y", source_message_id: "msg_other" },
          ],
        },
      },
    ];
    const chain = selectChainSteps(extraRows, "dec-q3-close");
    expect(chain.processMap!.entryHash).toBe(
      "processhash000000000000000000000",
    );
  });
});

describe("selectChainSteps · KPI/source linkage", () => {
  it("when KPI carries source_ids, picks the source_proposed for that source_id", () => {
    const rowsTwoSources: CandidateLedgerRow[] = [
      ...sampleRows,
      {
        seq: "60",
        tool: "emit_source_proposed",
        ts: "2026-04-25T12:00:00Z",
        hashHex: "othersrchash000000000000000000",
        args: {
          source_id: "src-other-csv",
          uri: "s3://wormbase/other.csv",
          source_kind: "csv",
        },
      },
    ];
    const chain = selectChainSteps(rowsTwoSources, "dec-q3-close");
    expect(chain.source!.entryHash).toBe("sourcehash0000000000000000000000");
  });
});
