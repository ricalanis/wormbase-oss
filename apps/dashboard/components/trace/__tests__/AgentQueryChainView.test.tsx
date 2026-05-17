/**
 * AgentQueryChainView — chronological PEVR + chained-entry timeline tests
 * (Wave 3 Task 3 — SOC-2-credibility view).
 *
 * Validates the per-kind detail renders (agent_query, inference_served,
 * credential, query_correction_suggested, query_outcome_recorded) and
 * the gate-denied highlight that makes auditors zero in on red rows.
 */
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { AgentQueryChainView } from "../AgentQueryChainView";
import type { AgentQueryChain, ChainEntry } from "../../../lib/agent-query-chain";

const ROOT_AUDIT = "00000000-0000-0000-0000-00000000aaaa";

function pevrEntry(
  seq: string,
  phase: "propose" | "execute" | "verify" | "resolve",
  ts: string,
  extra: Record<string, unknown> = {},
): ChainEntry {
  return {
    seq,
    envelopeKind: phase,
    kind: "agent_query",
    auditTrailId: ROOT_AUDIT,
    causedBy: null,
    ts,
    phase,
    hashHex: `hash-${seq}`,
    payload: {
      agent_id: "agent-1",
      mcp_tool: "lake.semantic.metric",
      args: { name: "revenue_q3" },
      route_mode: "broker",
      phase,
      audit_trail_id: ROOT_AUDIT,
      row_count: phase === "resolve" ? 4 : null,
      cost_usd: phase === "resolve" ? "0.013" : null,
      latency_ms: phase === "resolve" ? 420 : null,
      ...extra,
    },
  };
}

function inferenceEntry(seq: string, ts: string): ChainEntry {
  return {
    seq,
    envelopeKind: "execute",
    kind: "inference_served",
    auditTrailId: null,
    causedBy: ROOT_AUDIT,
    ts,
    phase: null,
    hashHex: `hash-${seq}`,
    payload: {
      kind: "inference_served",
      caused_by: ROOT_AUDIT,
      served_by: "kimi",
      latency_ms: 380,
      cost_usd: "0.004",
    },
  };
}

function credentialEntry(seq: string, ts: string): ChainEntry {
  return {
    seq,
    envelopeKind: "resolve",
    kind: "credential",
    auditTrailId: null,
    causedBy: ROOT_AUDIT,
    ts,
    phase: null,
    hashHex: `hash-${seq}`,
    payload: {
      agent_id: "agent-1",
      credential_kind: "data",
      target: "snowflake://X.Y.Z",
      status: "active",
      ttl_expires_at: "2026-05-11T18:00:00Z",
      issued_by: "agent-gateway",
      caused_by: ROOT_AUDIT,
    },
  };
}

function happyChain(): AgentQueryChain {
  return {
    rootAuditTrailId: ROOT_AUDIT,
    agentId: "agent-1",
    mcpTool: "lake.semantic.metric",
    routeMode: "broker",
    status: "resolve",
    totalLatencyMs: 420,
    totalCostUsd: "0.0130",
    entries: [
      pevrEntry("100", "propose", "2026-05-10T10:00:00Z"),
      pevrEntry("101", "execute", "2026-05-10T10:00:01Z"),
      inferenceEntry("102", "2026-05-10T10:00:01.5Z"),
      credentialEntry("103", "2026-05-10T10:00:02Z"),
      pevrEntry("104", "verify", "2026-05-10T10:00:02.5Z"),
      pevrEntry("105", "resolve", "2026-05-10T10:00:03Z"),
    ],
  };
}

describe("AgentQueryChainView · happy chain", () => {
  it("renders the chain container", () => {
    render(<AgentQueryChainView chain={happyChain()} />);
    expect(screen.getByTestId("agent-query-chain")).toBeInTheDocument();
  });

  it("renders header roll-up (agent, tool, status, latency, cost)", () => {
    render(<AgentQueryChainView chain={happyChain()} />);
    const header = screen.getByTestId("agent-query-chain-header");
    expect(within(header).getByText("agent-1")).toBeInTheDocument();
    expect(within(header).getByText("lake.semantic.metric")).toBeInTheDocument();
    expect(within(header).getByText("broker")).toBeInTheDocument();
    expect(within(header).getByText("resolve")).toBeInTheDocument();
    expect(within(header).getByText("420ms")).toBeInTheDocument();
    expect(within(header).getByText("$0.0130")).toBeInTheDocument();
    expect(within(header).getByText("6")).toBeInTheDocument();
  });

  it("renders an entry card per chain entry", () => {
    render(<AgentQueryChainView chain={happyChain()} />);
    const cards = screen.getAllByTestId(/^chain-card-/);
    expect(cards).toHaveLength(6);
  });

  it("renders agent_query phase + mcp_tool + route in agent_query detail", () => {
    render(<AgentQueryChainView chain={happyChain()} />);
    const details = screen.getAllByTestId("chain-detail-agent_query");
    expect(details.length).toBeGreaterThanOrEqual(4);
    // The resolve-phase row shows row_count + latency + cost.
    const text = details[details.length - 1].textContent ?? "";
    expect(text).toContain("lake.semantic.metric");
    expect(text).toContain("broker");
  });

  it("renders inference_served detail with served_by + latency", () => {
    render(<AgentQueryChainView chain={happyChain()} />);
    const detail = screen.getByTestId("chain-detail-inference_served");
    const text = detail.textContent ?? "";
    expect(text).toContain("kimi");
    expect(text).toContain("380ms");
  });

  it("renders credential detail with kind + target + ttl + status", () => {
    render(<AgentQueryChainView chain={happyChain()} />);
    const detail = screen.getByTestId("chain-detail-credential");
    const text = detail.textContent ?? "";
    expect(text).toContain("data");
    expect(text).toContain("snowflake://X.Y.Z");
    expect(text).toContain("active");
  });

  it("emits a copy-hash button for every entry", () => {
    render(<AgentQueryChainView chain={happyChain()} />);
    const buttons = screen.getAllByTestId(/^chain-copy-hash-/);
    expect(buttons).toHaveLength(6);
  });
});

// ─── Gate-denied chain ────────────────────────────────────────────────────

describe("AgentQueryChainView · gate-denied chain", () => {
  it("highlights gate-denied entries with a pill + header pivots to red", () => {
    const denied: AgentQueryChain = {
      ...happyChain(),
      status: "denied",
      entries: [
        pevrEntry("200", "propose", "2026-05-10T10:00:00Z"),
        pevrEntry("201", "execute", "2026-05-10T10:00:01Z"),
        pevrEntry("202", "verify", "2026-05-10T10:00:02Z", { passed: false }),
      ],
    };
    render(<AgentQueryChainView chain={denied} />);
    const pills = screen.getAllByTestId("chain-gate-denied-pill");
    expect(pills.length).toBeGreaterThanOrEqual(1);
    const header = screen.getByTestId("agent-query-chain-header");
    expect(within(header).getByText(/denied/i)).toBeInTheDocument();
  });

  it("marks the denied entry's li with data-denied=true", () => {
    const denied: AgentQueryChain = {
      ...happyChain(),
      status: "denied",
      entries: [
        pevrEntry("200", "propose", "2026-05-10T10:00:00Z"),
        pevrEntry("201", "verify", "2026-05-10T10:00:02Z", { passed: false }),
      ],
    };
    render(<AgentQueryChainView chain={denied} />);
    const deniedLi = screen.getByTestId("chain-entry-agent_query-verify-1");
    expect(deniedLi.getAttribute("data-denied")).toBe("true");
  });
});

// ─── Retry-tree (query_correction_suggested + chained agent_query) ────────

describe("AgentQueryChainView · retry tree", () => {
  it("renders query_correction_suggested detail with failure_kind", () => {
    const chain: AgentQueryChain = {
      ...happyChain(),
      entries: [
        pevrEntry("100", "propose", "2026-05-10T10:00:00Z"),
        pevrEntry("101", "execute", "2026-05-10T10:00:01Z"),
        pevrEntry("102", "verify", "2026-05-10T10:00:02Z"),
        pevrEntry("103", "resolve", "2026-05-10T10:00:03Z"),
        {
          seq: "200",
          envelopeKind: "execute",
          kind: "query_correction_suggested",
          auditTrailId: ROOT_AUDIT,
          causedBy: ROOT_AUDIT,
          ts: "2026-05-10T10:00:04Z",
          phase: null,
          hashHex: "hash-200",
          payload: {
            kind: "query_correction_suggested",
            original_query_id: ROOT_AUDIT,
            failure_kind: "empty",
            failure_detail: "no rows returned",
          },
        },
      ],
    };
    render(<AgentQueryChainView chain={chain} />);
    const detail = screen.getByTestId(
      "chain-detail-query_correction_suggested",
    );
    const text = detail.textContent ?? "";
    expect(text).toContain("empty");
    expect(text).toContain("no rows returned");
  });

  it("renders query_outcome_recorded detail with quality_score", () => {
    const chain: AgentQueryChain = {
      ...happyChain(),
      entries: [
        pevrEntry("100", "propose", "2026-05-10T10:00:00Z"),
        pevrEntry("101", "resolve", "2026-05-10T10:00:03Z"),
        {
          seq: "200",
          envelopeKind: "execute",
          kind: "query_outcome_recorded",
          auditTrailId: ROOT_AUDIT,
          causedBy: ROOT_AUDIT,
          ts: "2026-05-10T10:00:05Z",
          phase: null,
          hashHex: "hash-200",
          payload: {
            kind: "query_outcome_recorded",
            agent_query_id: ROOT_AUDIT,
            used: true,
            useful: true,
            quality_score: "0.92",
          },
        },
      ],
    };
    render(<AgentQueryChainView chain={chain} />);
    const detail = screen.getByTestId("chain-detail-query_outcome_recorded");
    const text = detail.textContent ?? "";
    expect(text).toContain("0.92");
  });
});
