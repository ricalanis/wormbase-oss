/**
 * StrategyStatusBanner component tests — L3 Sub-wave D.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { StrategyStatusBanner } from "../StrategyStatusBanner";
import type { LineageStrategyStatus } from "../../../lib/lineage";

function row(partial: Partial<LineageStrategyStatus>): LineageStrategyStatus {
  return {
    strategy: partial.strategy ?? "dbt_manifest",
    configured: partial.configured ?? false,
    productive: partial.productive ?? false,
    note: partial.note ?? "default note",
  };
}

describe("StrategyStatusBanner", () => {
  it("labels productive strategies with the productive badge", () => {
    render(
      <StrategyStatusBanner
        rows={[
          row({
            strategy: "dbt_manifest",
            configured: true,
            productive: true,
          }),
        ]}
      />,
    );
    expect(
      screen.getByTestId("strategy-status-badge-dbt_manifest-productive"),
    ).toHaveTextContent("productive");
  });

  it("labels configured-but-stubbed strategies with the stubbed badge", () => {
    render(
      <StrategyStatusBanner
        rows={[
          row({
            strategy: "sample_overlap",
            configured: true,
            productive: false,
            note: "NoopSampler stub",
          }),
        ]}
      />,
    );
    expect(
      screen.getByTestId("strategy-status-badge-sample_overlap-stubbed"),
    ).toHaveTextContent("configured · stubbed");
  });

  it("labels disabled strategies with the disabled badge", () => {
    render(
      <StrategyStatusBanner
        rows={[
          row({
            strategy: "naming_heuristic",
            configured: false,
            productive: false,
          }),
        ]}
      />,
    );
    expect(
      screen.getByTestId("strategy-status-badge-naming_heuristic-disabled"),
    ).toHaveTextContent("disabled");
  });
});
