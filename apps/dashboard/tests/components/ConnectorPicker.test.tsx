/**
 * D4 — ConnectorPicker.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { ConnectorPicker } from "../../components/sources/ConnectorPicker";
import { CONNECTOR_CATALOG } from "../../lib/connectors-catalog";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ConnectorPicker", () => {
  it("renders one card per connector kind from the catalog", () => {
    render(<ConnectorPicker connectors={CONNECTOR_CATALOG} />);
    for (const c of CONNECTOR_CATALOG) {
      expect(
        screen.getByTestId(`connector-card-${c.kind}`),
      ).toBeInTheDocument();
    }
  });

  it("flags ready vs stub connectors via the data-ready attribute", () => {
    render(<ConnectorPicker connectors={CONNECTOR_CATALOG} />);
    const csv = screen.getByTestId("connector-card-csv_local");
    expect(csv.getAttribute("data-ready")).toBe("true");
    const bigquery = screen.getByTestId("connector-card-bigquery");
    expect(bigquery.getAttribute("data-ready")).toBe("false");
  });

  it("renders capability badges per connector", () => {
    render(<ConnectorPicker connectors={CONNECTOR_CATALOG} />);
    const caps = screen.getByTestId("connector-caps-stripe");
    expect(caps.textContent).toMatch(/discover/);
    expect(caps.textContent).toMatch(/profile/);
    expect(caps.textContent).toMatch(/sample/);
    expect(caps.textContent).toMatch(/watch/);
  });

  it("mounts the ConnectorConfigForm when a card is selected", () => {
    render(<ConnectorPicker connectors={CONNECTOR_CATALOG} />);
    expect(
      screen.queryByTestId("connector-config-form-csv_local"),
    ).toBeNull();
    fireEvent.click(screen.getByTestId("connector-card-csv_local"));
    expect(
      screen.getByTestId("connector-config-form-csv_local"),
    ).toBeInTheDocument();
    // postgres form not rendered until clicked
    expect(
      screen.queryByTestId("connector-config-form-postgres"),
    ).toBeNull();
  });

  it("the config form renders one input per field with required-marker on required ones", () => {
    render(<ConnectorPicker connectors={CONNECTOR_CATALOG} />);
    fireEvent.click(screen.getByTestId("connector-card-postgres"));
    expect(screen.getByTestId("connector-config-field-dsn")).toBeInTheDocument();
  });

  // ------------------------------------------------------------------
  // Capability-honesty: status badges + coming_soon UX
  // ------------------------------------------------------------------

  it("renders a 'production' status pill on production connectors", () => {
    render(<ConnectorPicker connectors={CONNECTOR_CATALOG} />);
    const pill = screen.getByTestId("connector-status-pill-csv_local");
    expect(pill.textContent?.toLowerCase()).toContain("production");
  });

  it("renders a 'coming soon' status pill on skeletal connectors", () => {
    render(<ConnectorPicker connectors={CONNECTOR_CATALOG} />);
    const pill = screen.getByTestId("connector-status-pill-notion");
    expect(pill.textContent?.toLowerCase()).toContain("coming soon");
  });

  it("propagates data-status onto connector cards", () => {
    render(<ConnectorPicker connectors={CONNECTOR_CATALOG} />);
    expect(
      screen.getByTestId("connector-card-csv_local").getAttribute("data-status"),
    ).toBe("production");
    expect(
      screen.getByTestId("connector-card-notion").getAttribute("data-status"),
    ).toBe("coming_soon");
  });

  it("opens a coming-soon modal (NOT the config form) when a coming_soon card is clicked", () => {
    render(<ConnectorPicker connectors={CONNECTOR_CATALOG} />);
    fireEvent.click(screen.getByTestId("connector-card-notion"));
    expect(
      screen.getByTestId("connector-coming-soon-modal-notion"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("connector-config-form-notion"),
    ).toBeNull();
  });

  it("the coming-soon modal renders the status note and a notify-me button", () => {
    render(<ConnectorPicker connectors={CONNECTOR_CATALOG} />);
    fireEvent.click(screen.getByTestId("connector-card-notion"));
    expect(screen.getByTestId("coming-soon-notify-me")).toBeInTheDocument();
    // The status note text appears in the modal — scope the lookup
    // to the modal (the same "v1.5" string also appears on the picker
    // card itself, since coming-soon cards inline-render their note).
    const modal = screen.getByTestId("connector-coming-soon-modal-notion");
    expect(modal.textContent).toMatch(/v1\.5/i);
  });

  it("coming-soon modal closes when close is clicked", () => {
    render(<ConnectorPicker connectors={CONNECTOR_CATALOG} />);
    fireEvent.click(screen.getByTestId("connector-card-notion"));
    expect(
      screen.getByTestId("connector-coming-soon-modal-notion"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("coming-soon-modal-close"));
    expect(
      screen.queryByTestId("connector-coming-soon-modal-notion"),
    ).toBeNull();
  });
});
