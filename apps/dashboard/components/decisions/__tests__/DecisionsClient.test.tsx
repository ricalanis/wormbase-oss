/**
 * DecisionsClient — opens record drawer on header CTA; opens inspect
 * drawer on row click; closes via scrim (W2.A7).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

import { DecisionsClient } from "../DecisionsClient";
import type { DecisionRow } from "../../../lib/ledger-client.types";

const sample: DecisionRow = {
  decisionId: "dec_1",
  decisionText: "Approved: Tuesday rollout.",
  decisionAt: "2026-04-25T12:00:00Z",
  channelId: "C0OPS",
  decidedByPersons: ["p_alice"],
  evidenceMessageIds: ["msg_1"],
  confidence: 0.88,
  receipt: {
    hash: "deadbeef",
    source: "channel:C0OPS",
    owner: "ops",
    classification: "internal",
  },
};

describe("DecisionsClient", () => {
  it("renders the table and the Record decision CTA", () => {
    render(<DecisionsClient rows={[sample]} />);
    expect(screen.getByTestId("decisions-record-open")).toBeInTheDocument();
    expect(screen.getByTestId(`decision-${sample.decisionId}`)).toBeInTheDocument();
  });

  it("opens the record drawer when the header CTA is clicked", () => {
    render(<DecisionsClient rows={[sample]} />);
    expect(screen.queryByTestId("decision-detail-drawer")).toBeNull();
    fireEvent.click(screen.getByTestId("decisions-record-open"));
    expect(screen.getByTestId("decision-detail-drawer")).toBeInTheDocument();
    expect(screen.getByTestId("decision-record-form")).toBeInTheDocument();
  });

  it("opens the inspect drawer when a row is clicked", () => {
    render(<DecisionsClient rows={[sample]} />);
    fireEvent.click(screen.getByTestId(`decision-${sample.decisionId}`));
    expect(screen.getByTestId("decision-detail-drawer")).toBeInTheDocument();
    expect(screen.getByTestId("decision-drawer-title").textContent).toContain(
      "Tuesday",
    );
  });

  it("closes the drawer when the scrim is clicked", () => {
    render(<DecisionsClient rows={[sample]} />);
    fireEvent.click(screen.getByTestId("decisions-record-open"));
    expect(screen.getByTestId("decision-detail-drawer")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("decision-drawer-scrim"));
    expect(screen.queryByTestId("decision-detail-drawer")).toBeNull();
  });
});
