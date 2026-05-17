/**
 * Tests for PolicySideBySide (Wave 3 Task 6).
 *
 * Pins:
 *
 *   * One card per upstream policy + one card per WormBase policy.
 *   * NULL body renders the "Body unavailable" placeholder copy
 *     (the S2 spike contract surfacing — see CLAUDE.md).
 *   * Non-NULL body renders verbatim in a monospace block.
 *   * Both columns render headers even when one side is empty;
 *     the empty side shows the "nothing yet" affordance so the
 *     surface doesn't render a silent panel (CLAUDE.md §9).
 *   * Empty + empty still shows both column headers so the page
 *     remains informative.
 *
 * jsdom-flavoured DOM via vitest; the component is a server-friendly
 * pure-presentational React tree.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { PolicySideBySide } from "../PolicySideBySide";
import type {
  ExternalPolicyRow,
  WormbasePolicyRow,
} from "../../../lib/lake-governance";

function externalRow(
  partial: Partial<ExternalPolicyRow> &
    Pick<ExternalPolicyRow, "id" | "policyFqn">,
): ExternalPolicyRow {
  return {
    id: partial.id,
    sourceId:
      partial.sourceId ?? "00000000-0000-0000-0000-000000000001",
    sourceName: partial.sourceName ?? "snowflake_native",
    policyFqn: partial.policyFqn,
    policyKind: partial.policyKind ?? "masking",
    body: partial.body ?? null,
    appliedTo: partial.appliedTo ?? [],
    importedAt: partial.importedAt ?? "2026-05-11T10:00:00.000Z",
  };
}

function wormbaseRow(
  partial: Partial<WormbasePolicyRow> &
    Pick<WormbasePolicyRow, "id" | "policyName">,
): WormbasePolicyRow {
  return {
    id: partial.id,
    policyName: partial.policyName,
    plainLanguage:
      partial.plainLanguage ?? `${partial.policyName} description`,
    scope: partial.scope ?? "global",
    gateImpl: partial.gateImpl ?? "policy.example_v1",
    body: partial.body ?? "policy.example_v1",
  };
}

describe("PolicySideBySide", () => {
  it("renders one card per upstream policy", () => {
    render(
      <PolicySideBySide
        externalPolicies={[
          externalRow({
            id: "ext-1",
            policyFqn: "ACME.RAW.REVENUE_MASK",
            policyKind: "masking",
            body:
              "CASE WHEN current_role() = 'ADMIN' THEN val ELSE NULL END",
            appliedTo: ["ACME.RAW.REVENUE.amount"],
          }),
          externalRow({
            id: "ext-2",
            policyFqn: "ACME.RAW.PII_ROW_ACCESS",
            policyKind: "row_access",
            body: null,
          }),
        ]}
        wormbasePolicies={[]}
      />,
    );

    expect(screen.getByTestId("external-policy-ext-1")).toBeInTheDocument();
    expect(screen.getByTestId("external-policy-ext-2")).toBeInTheDocument();
    // Both policy fqns visible.
    expect(screen.getByText("ACME.RAW.REVENUE_MASK")).toBeInTheDocument();
    expect(
      screen.getByText("ACME.RAW.PII_ROW_ACCESS"),
    ).toBeInTheDocument();
  });

  it("renders the placeholder when body is null (S2 spike contract)", () => {
    render(
      <PolicySideBySide
        externalPolicies={[
          externalRow({
            id: "ext-null",
            policyFqn: "ACME.NULL_BODY",
            body: null,
            appliedTo: ["ACME.X"],
          }),
        ]}
        wormbasePolicies={[]}
      />,
    );

    expect(
      screen.getByTestId("external-policy-body-unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Body unavailable (insufficient APPLY privilege)",
      ),
    ).toBeInTheDocument();
  });

  it("renders the SQL body verbatim when it's present", () => {
    render(
      <PolicySideBySide
        externalPolicies={[
          externalRow({
            id: "ext-body",
            policyFqn: "ACME.HAS_BODY",
            body: "SELECT 1 FROM dual",
          }),
        ]}
        wormbasePolicies={[]}
      />,
    );

    const body = screen.getByTestId("external-policy-body");
    expect(body.textContent).toBe("SELECT 1 FROM dual");
    expect(
      screen.queryByTestId("external-policy-body-unavailable"),
    ).toBeNull();
  });

  it("renders one card per WormBase policy", () => {
    render(
      <PolicySideBySide
        externalPolicies={[]}
        wormbasePolicies={[
          wormbaseRow({
            id: "warmup_pii_redact",
            policyName: "Warmup PII redaction",
            scope: "per-domain",
          }),
          wormbaseRow({
            id: "interjection_budget",
            policyName: "Interjection budget",
            scope: "global",
          }),
        ]}
      />,
    );

    expect(
      screen.getByTestId("wormbase-policy-warmup_pii_redact"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("wormbase-policy-interjection_budget"),
    ).toBeInTheDocument();
    expect(screen.getByText("Warmup PII redaction")).toBeInTheDocument();
  });

  it("renders both column headers even when one column is empty", () => {
    render(
      <PolicySideBySide
        externalPolicies={[]}
        wormbasePolicies={[
          wormbaseRow({
            id: "wb-only",
            policyName: "WormBase only",
          }),
        ]}
      />,
    );

    expect(screen.getByTestId("upstream-column")).toBeInTheDocument();
    expect(screen.getByTestId("wormbase-column")).toBeInTheDocument();
    expect(screen.getByTestId("upstream-empty")).toBeInTheDocument();
    // WormBase side renders the card, not the empty placeholder.
    expect(screen.queryByTestId("wormbase-empty")).toBeNull();
  });

  it("renders both empty affordances when both columns are empty", () => {
    render(
      <PolicySideBySide
        externalPolicies={[]}
        wormbasePolicies={[]}
      />,
    );

    expect(screen.getByTestId("upstream-empty")).toBeInTheDocument();
    expect(screen.getByTestId("wormbase-empty")).toBeInTheDocument();
    // Headers still visible — neither side is hidden.
    expect(
      screen.getByText(/Upstream policies · 0/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/WormBase policies · 0/),
    ).toBeInTheDocument();
  });

  it("renders applied_to references when present", () => {
    render(
      <PolicySideBySide
        externalPolicies={[
          externalRow({
            id: "ext-applied",
            policyFqn: "ACME.MULTI_COL",
            body: "SELECT 1",
            appliedTo: ["ACME.X.col_a", "ACME.X.col_b"],
          }),
        ]}
        wormbasePolicies={[]}
      />,
    );

    const applied = screen.getByTestId("external-policy-applied-to");
    expect(applied.textContent).toBe("ACME.X.col_a, ACME.X.col_b");
  });
});
