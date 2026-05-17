import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConnectorCard } from "../ConnectorCard";
import type { ConnectorEntry } from "../../../app/api/v1/connectors/list/route";

function makeEntry(overrides: Partial<ConnectorEntry> = {}): ConnectorEntry {
  return {
    kind: "postgres",
    label: "Postgres",
    status: "production",
    status_note: "Production-grade Postgres connector.",
    capabilities: ["discover", "profile", "sample"],
    classification_hints: [],
    config_schema: [],
    ...overrides,
  };
}

describe("ConnectorCard (W2.A5)", () => {
  it("renders production status with a routable link", () => {
    render(<ConnectorCard entry={makeEntry()} />);
    const card = screen.getByTestId("connector-card-postgres");
    expect(card).toHaveAttribute("data-status", "production");
    expect(card.tagName.toLowerCase()).toBe("a");
    expect(card).toHaveAttribute("href", "/sources/new/postgres");
    expect(screen.getByTestId("connector-status-pill-postgres")).toHaveTextContent(
      "production",
    );
  });

  it("renders preview status with the warning pill", () => {
    render(
      <ConnectorCard
        entry={makeEntry({ kind: "stripe", label: "Stripe", status: "preview" })}
      />,
    );
    expect(screen.getByTestId("connector-status-pill-stripe")).toHaveTextContent(
      "preview",
    );
    const card = screen.getByTestId("connector-card-stripe");
    expect(card.tagName.toLowerCase()).toBe("a");
  });

  it("disables coming_soon connectors and surfaces the ETA tooltip", () => {
    render(
      <ConnectorCard
        entry={makeEntry({
          kind: "bigquery",
          label: "BigQuery",
          status: "coming_soon",
          status_note: "Connector skeleton — google-cloud-bigquery integration lands in v1.5.",
        })}
      />,
    );
    const card = screen.getByTestId("connector-card-bigquery");
    expect(card).toHaveAttribute("data-status", "coming_soon");
    expect(card).toHaveAttribute("aria-disabled", "true");
    // Coming soon cards are not links — they should render as a div.
    expect(card.tagName.toLowerCase()).not.toBe("a");
    expect(card.getAttribute("title") ?? "").toMatch(/ETA per docs/i);
    expect(screen.getByTestId("connector-status-pill-bigquery")).toHaveTextContent(
      "coming soon",
    );
  });

  it("renders capability chips honestly from the registry", () => {
    render(
      <ConnectorCard
        entry={makeEntry({
          kind: "csv_local",
          label: "Local CSV",
          capabilities: ["discover", "profile", "sample"],
        })}
      />,
    );
    const caps = screen.getByTestId("connector-caps-csv_local");
    expect(caps.textContent).toMatch(/discover/);
    expect(caps.textContent).toMatch(/profile/);
    expect(caps.textContent).toMatch(/sample/);
  });
});
