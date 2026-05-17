import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { BusinessDefsPanel } from "../../components/onboarding/BusinessDefsPanel";

const proposals = [
  {
    term: "Active account",
    proposedDefinition: "An account with at least one paying subscription.",
    sourceHash: "abcd1234",
  },
  {
    term: "ARPU",
    proposedDefinition: "Net invoice total / count distinct active accounts.",
    sourceHash: "deadbeef",
  },
];

describe("BusinessDefsPanel", () => {
  it("renders one row per proposal with Accept/Reject", () => {
    render(<BusinessDefsPanel proposals={proposals} />);
    expect(screen.getByTestId("confirm-Active-account")).toBeInTheDocument();
    expect(screen.getByTestId("reject-Active-account")).toBeInTheDocument();
  });

  it("calls onConfirm when accept is clicked, sets data-status=accepted", async () => {
    const onConfirm = vi.fn();
    const { container } = render(
      <BusinessDefsPanel proposals={proposals} onConfirm={onConfirm} />
    );
    fireEvent.click(screen.getByTestId("confirm-Active-account"));
    expect(onConfirm).toHaveBeenCalledWith("Active account");
    const row = container.querySelector(
      "[data-testid='business-def-Active-account']"
    ) as HTMLElement;
    expect(row.getAttribute("data-status")).toBe("accepted");
  });

  it("renders the source hash in mono", () => {
    render(<BusinessDefsPanel proposals={proposals} />);
    expect(screen.getByText(/abcd1234/)).toBeInTheDocument();
  });
});
