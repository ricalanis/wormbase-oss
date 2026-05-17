/**
 * Header PersonChip.
 *
 * Asserts:
 *   - renders name + position + role badge
 *   - links to /people/{id} when personId is provided
 *   - renders inert (no link) when personId is omitted (renderer-side
 *     callers can opt out of linking; the (app)/ layout always passes one)
 *   - position is hidden when null (e.g. installer pre-position)
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { PersonChip } from "../../components/chrome/PersonChip";

describe("PersonChip", () => {
  it("renders name + position + role badge", () => {
    render(
      <PersonChip
        person={{ name: "Carol Reyes", position: "CFO" }}
        role="admin"
      />,
    );
    expect(screen.getByText("Carol Reyes")).toBeInTheDocument();
    expect(screen.getByText("CFO")).toBeInTheDocument();
    expect(screen.getByTestId("role-badge").textContent).toBe("admin");
  });

  it("links to /people/{id} when personId is supplied", () => {
    render(
      <PersonChip
        person={{ name: "Bob Martin", position: "Data Engineer" }}
        role="member"
        personId="abc-123"
      />,
    );
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("/people/abc-123");
  });

  it("renders inert (no link) when personId is omitted", () => {
    render(
      <PersonChip
        person={{ name: "Carol Reyes", position: null }}
        role="admin"
      />,
    );
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByTestId("person-chip")).toBeInTheDocument();
    expect(screen.getByTestId("role-badge").textContent).toBe("admin");
  });

  it("hides the position chip when position is null", () => {
    render(
      <PersonChip
        person={{ name: "Pat", position: null }}
        role="installer"
      />,
    );
    expect(screen.queryByTestId("person-chip-position")).toBeNull();
    expect(screen.getByTestId("role-badge").textContent).toBe("installer");
  });
});
