import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { AddSourceButton } from "../AddSourceButton";

describe("AddSourceButton (W2.A5)", () => {
  it("renders with the expected label and routes to /sources/new", () => {
    render(<AddSourceButton />);
    const link = screen.getByTestId("add-source-button");
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/sources/new");
    expect(link.textContent).toMatch(/Add source/);
  });
});
