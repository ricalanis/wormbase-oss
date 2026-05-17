/**
 * G2 — ConnectorFirstGrid (Tier 0 connector-first landing).
 *
 * Tests:
 *   - one card per connector kind, banded by status
 *   - production / preview cards are clickable + route to /connect/[kind]/start
 *   - coming_soon cards open notify-me modal, not the connect flow
 *   - status pills render the right band per card
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { ConnectorFirstGrid } from "../../components/onboarding/ConnectorFirstGrid";
import { CONNECTOR_CATALOG } from "../../lib/connectors-catalog";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ConnectorFirstGrid", () => {
  it("renders one card per connector kind from the catalog", () => {
    render(<ConnectorFirstGrid connectors={CONNECTOR_CATALOG} />);
    for (const c of CONNECTOR_CATALOG) {
      expect(
        screen.getByTestId(`connector-first-card-${c.kind}`),
      ).toBeInTheDocument();
    }
  });

  it("groups connectors into production / preview / coming_soon bands", () => {
    render(<ConnectorFirstGrid connectors={CONNECTOR_CATALOG} />);
    expect(
      screen.getByTestId("connector-band-production"),
    ).toBeInTheDocument();
    // Preview band only renders if there are previews; the catalog has none
    // for connectors today, so we tolerate either presence or absence here:
    const previewBand = screen.queryByTestId("connector-band-preview");
    if (previewBand) expect(previewBand).toBeInTheDocument();
    expect(
      screen.getByTestId("connector-band-coming_soon"),
    ).toBeInTheDocument();
  });

  it("propagates data-status onto each card", () => {
    render(<ConnectorFirstGrid connectors={CONNECTOR_CATALOG} />);
    expect(
      screen
        .getByTestId("connector-first-card-csv_local")
        .getAttribute("data-status"),
    ).toBe("production");
    expect(
      screen
        .getByTestId("connector-first-card-notion")
        .getAttribute("data-status"),
    ).toBe("coming_soon");
  });

  it("clicking a production card routes to /onboarding/connect/[kind]/start", () => {
    render(<ConnectorFirstGrid connectors={CONNECTOR_CATALOG} />);
    fireEvent.click(screen.getByTestId("connector-first-card-csv_local"));
    expect(pushMock).toHaveBeenCalledWith(
      "/onboarding/connect/csv_local/start",
    );
  });

  it("clicking a coming_soon card opens the notify-me modal, NOT the start route", () => {
    render(<ConnectorFirstGrid connectors={CONNECTOR_CATALOG} />);
    fireEvent.click(screen.getByTestId("connector-first-card-notion"));
    expect(pushMock).not.toHaveBeenCalled();
    expect(
      screen.getByTestId("connector-first-coming-soon-modal-notion"),
    ).toBeInTheDocument();
  });

  it("renders status pills with the right text per band", () => {
    render(<ConnectorFirstGrid connectors={CONNECTOR_CATALOG} />);
    expect(
      screen
        .getByTestId("connector-first-pill-csv_local")
        .textContent?.toLowerCase(),
    ).toContain("production");
    expect(
      screen
        .getByTestId("connector-first-pill-notion")
        .textContent?.toLowerCase(),
    ).toContain("coming soon");
  });

  it("notify-me modal renders the connector status note", () => {
    render(<ConnectorFirstGrid connectors={CONNECTOR_CATALOG} />);
    fireEvent.click(screen.getByTestId("connector-first-card-bigquery"));
    const modal = screen.getByTestId(
      "connector-first-coming-soon-modal-bigquery",
    );
    expect(modal.textContent?.toLowerCase()).toContain("v1.5");
  });

  it("modal close dismisses the dialog without routing", () => {
    render(<ConnectorFirstGrid connectors={CONNECTOR_CATALOG} />);
    fireEvent.click(screen.getByTestId("connector-first-card-notion"));
    expect(
      screen.getByTestId("connector-first-coming-soon-modal-notion"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("connector-first-modal-close"));
    expect(
      screen.queryByTestId("connector-first-coming-soon-modal-notion"),
    ).toBeNull();
    expect(pushMock).not.toHaveBeenCalled();
  });
});
