import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { PersonRow } from "../../components/people/PersonRow";
import type { PersonRow as PersonRowModel } from "../../lib/ledger-client.types";

const row: PersonRowModel = {
  personId: "p_x",
  displayName: "carla-bot",
  email: null,
  position: "data-engineer",
  status: "active",
  tenancyRole: null,
  identities: [],
  domainGrantCount: 2,
  resourceGrantCount: 1,
  roles: ["data-engineer"],
  ownedDomains: ["Product", "Finance"],
  ownedResources: ["events × users"],
  receipt: {
    hash: "abcd1234",
    source: "people-projection",
    owner: "carla-bot",
    classification: "internal",
  },
};

describe("PersonRow", () => {
  it("renders rectangular chips (NOT rounded pills) for owned domains", () => {
    const { container } = render(
      <table><tbody><PersonRow row={row} alt={false} /></tbody></table>
    );
    const chips = container.querySelectorAll("[data-chip]");
    expect(chips.length).toBe(2);
    for (const chip of Array.from(chips) as HTMLElement[]) {
      expect(chip.style.borderRadius).toBe("0px");
    }
  });

  it("alternates row background to paper-deep when alt=true", () => {
    const { container } = render(
      <table><tbody><PersonRow row={row} alt /></tbody></table>
    );
    const tr = container.querySelector(`[data-testid="person-${row.personId}"]`) as HTMLElement;
    expect(tr.style.background).toContain("paper-deep");
  });

  it("renders a Receipt inline", () => {
    const { container } = render(
      <table><tbody><PersonRow row={row} alt={false} /></tbody></table>
    );
    expect(container.querySelector("[data-receipt]")).toBeTruthy();
  });
});
