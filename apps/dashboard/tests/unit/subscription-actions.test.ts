/**
 * Unit tests for /people/agents/[id]/subscriptions/actions.ts (v2.A Task 7).
 *
 * Direct-tests the filter-axis validation + transport validation. Network
 * paths (POST to worm-core) are not exercised here — those live in the
 * worm-core HTTP integration test suite.
 */
import { describe, expect, it } from "vitest";

// Re-export of the validation helper. The action file exposes it via
// __test__ for direct testing without standing up server-side context.
import { __test__ } from "../../app/(app)/people/agents/[id]/subscriptions/actions";

const { validateFilterAxes } = __test__;

describe("validateFilterAxes", () => {
  it("rejects an entirely-empty filter (would match every entry)", () => {
    const result = validateFilterAxes({
      kinds: [],
      domains: [],
      agentIdRef: undefined,
      payloadPathEq: [],
      transport: "mcp_stream",
    });
    expect(result).not.toBeNull();
    expect(result).toContain("wildcard");
  });

  it("rejects whitespace-only payload pairs (would silently widen)", () => {
    const result = validateFilterAxes({
      kinds: [],
      domains: [],
      agentIdRef: "  ",
      payloadPathEq: [["  ", "  "]],
      transport: "mcp_stream",
    });
    expect(result).not.toBeNull();
  });

  it("accepts a filter with only kinds populated", () => {
    const result = validateFilterAxes({
      kinds: ["bad_pattern_proposed"],
      domains: [],
      agentIdRef: undefined,
      payloadPathEq: [],
      transport: "mcp_stream",
    });
    expect(result).toBeNull();
  });

  it("accepts a filter with only domains populated", () => {
    const result = validateFilterAxes({
      kinds: [],
      domains: ["finance"],
      agentIdRef: undefined,
      payloadPathEq: [],
      transport: "mcp_stream",
    });
    expect(result).toBeNull();
  });

  it("accepts a filter with only agent_id_ref populated", () => {
    const result = validateFilterAxes({
      kinds: [],
      domains: [],
      agentIdRef: "agent_xyz",
      payloadPathEq: [],
      transport: "mcp_stream",
    });
    expect(result).toBeNull();
  });

  it("accepts a filter with only a non-empty payload pair", () => {
    const result = validateFilterAxes({
      kinds: [],
      domains: [],
      agentIdRef: undefined,
      payloadPathEq: [["args.canonical_intent", "weekly revenue"]],
      transport: "mcp_stream",
    });
    expect(result).toBeNull();
  });

  it("accepts the most common case (kinds + agent_id_ref)", () => {
    const result = validateFilterAxes({
      kinds: ["bad_pattern_proposed", "semantic_gap_escalated"],
      domains: [],
      agentIdRef: "agent_xyz",
      payloadPathEq: [],
      transport: "mcp_stream",
    });
    expect(result).toBeNull();
  });
});
