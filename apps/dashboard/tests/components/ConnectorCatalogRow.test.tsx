/**
 * ConnectorCatalogRow render tests — Sub-wave D polish coverage.
 *
 * Validates the probe-badge surface + the per-connector Add-source
 * routing. Stripe routes to ``/sources/new/stripe`` (OAuth-graduated
 * landing); everything else routes to ``/sources/new/{kind}``.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { ConnectorCatalogRow } from "../../components/lake/ConnectorCatalogRow";
import type { ConnectorCatalogRow as Row } from "../../lib/connectors";

function makeRow(overrides: Partial<Row> = {}): Row {
  return {
    kind: "stripe",
    label: "Stripe",
    description: "Payments + revenue",
    status: "production",
    statusNote: "",
    capabilities: ["discover", "profile"],
    connectionState: "disconnected",
    activeSourceCount: 0,
    probe: { kind: "stripe", state: "unknown", reason: "probe not wired" },
    ...overrides,
  };
}

describe("ConnectorCatalogRow", () => {
  it("renders probe badge with 'unknown' when probe not wired", () => {
    render(
      <ul>
        <ConnectorCatalogRow row={makeRow()} />
      </ul>,
    );
    const probe = screen.getByTestId("connector-probe-stripe");
    expect(probe.textContent?.toLowerCase()).toContain("unknown");
  });

  it("renders probe badge with 'works' when probe is healthy", () => {
    render(
      <ul>
        <ConnectorCatalogRow
          row={makeRow({
            kind: "csv_local",
            label: "Local CSV",
            connectionState: "available",
            probe: { kind: "csv_local", state: "works", reason: null },
          })}
        />
      </ul>,
    );
    const probe = screen.getByTestId("connector-probe-csv_local");
    expect(probe.textContent?.toLowerCase()).toContain("works");
  });

  it("Stripe Add-source CTA routes to /sources/new/stripe", () => {
    render(
      <ul>
        <ConnectorCatalogRow row={makeRow()} />
      </ul>,
    );
    const link = screen.getByTestId("connector-add-source-stripe");
    expect(link.getAttribute("href")).toBe("/sources/new/stripe");
  });

  it("Non-Stripe Add-source CTA routes to /sources/new/{kind}", () => {
    render(
      <ul>
        <ConnectorCatalogRow
          row={makeRow({
            kind: "postgres",
            label: "Postgres",
          })}
        />
      </ul>,
    );
    const link = screen.getByTestId("connector-add-source-postgres");
    expect(link.getAttribute("href")).toBe("/sources/new/postgres");
  });

  it("coming_soon rows do NOT render a probe badge", () => {
    render(
      <ul>
        <ConnectorCatalogRow
          row={makeRow({
            kind: "salesforce",
            status: "coming_soon",
            probe: null,
          })}
        />
      </ul>,
    );
    expect(screen.queryByTestId("connector-probe-salesforce")).toBeNull();
  });

  it("probe reason is wired as a tooltip", () => {
    render(
      <ul>
        <ConnectorCatalogRow
          row={makeRow({
            probe: {
              kind: "stripe",
              state: "unknown",
              reason: "probe not yet implemented for kind 'stripe'",
            },
          })}
        />
      </ul>,
    );
    const probe = screen.getByTestId("connector-probe-stripe");
    expect(probe.getAttribute("title")).toContain("probe not yet implemented");
  });
});
