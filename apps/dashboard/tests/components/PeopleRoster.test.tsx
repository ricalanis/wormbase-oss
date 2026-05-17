/**
 * PeopleRoster — renders rows, sorts on header click, opens drawer on row
 * click, badge text matches role.
 *
 * The drawer is a heavy client-side fetcher; we mock it out so the roster
 * tests stay focused on roster behavior.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

vi.mock("../../components/people/PersonDetailDrawer", () => ({
  PersonDetailDrawer: ({
    personId,
    onClose,
  }: {
    personId: string;
    onClose: () => void;
  }) => (
    <div data-testid="mock-drawer" data-person-id={personId}>
      <button data-testid="mock-drawer-close" onClick={onClose}>
        close
      </button>
    </div>
  ),
}));

import { PeopleRoster } from "../../components/people/PeopleRoster";
import type { PersonRow } from "../../lib/ledger-client.types";

function person(over: Partial<PersonRow> = {}): PersonRow {
  return {
    personId: "p1",
    displayName: "Carol Reyes",
    email: "carol@x.co",
    position: "CFO",
    status: "active",
    tenancyRole: "admin",
    identities: [],
    domainGrantCount: 2,
    resourceGrantCount: 5,
    roles: ["admin"],
    ownedDomains: [],
    ownedResources: [],
    receipt: {
      hash: "deadbeef0000",
      source: "people-projection",
      owner: "p1",
      classification: "internal",
    },
    ...over,
  };
}

const persons: PersonRow[] = [
  person({
    personId: "p_carol",
    displayName: "Carol Reyes",
    position: "CFO",
    tenancyRole: "admin",
    domainGrantCount: 2,
    resourceGrantCount: 5,
  }),
  person({
    personId: "p_bob",
    displayName: "Bob Martin",
    email: "bob@x.co",
    position: "Data Engineer",
    tenancyRole: "member",
    domainGrantCount: 1,
    resourceGrantCount: 8,
  }),
];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PeopleRoster", () => {
  it("renders one row per Person", () => {
    render(<PeopleRoster persons={persons} />);
    expect(screen.getByTestId("roster-row-p_carol")).toBeInTheDocument();
    expect(screen.getByTestId("roster-row-p_bob")).toBeInTheDocument();
    expect(screen.getByText("Carol Reyes")).toBeInTheDocument();
    expect(screen.getByText("Bob Martin")).toBeInTheDocument();
  });

  it("renders the tenancy role badge with the role text", () => {
    render(<PeopleRoster persons={persons} />);
    expect(screen.getByTestId("roster-tenancy-p_carol").textContent).toBe(
      "admin",
    );
    expect(screen.getByTestId("roster-tenancy-p_bob").textContent).toBe(
      "member",
    );
  });

  it("renders the status badge", () => {
    render(<PeopleRoster persons={persons} />);
    expect(screen.getByTestId("roster-status-p_carol").textContent).toBe(
      "active",
    );
  });

  it("sorts ascending by name by default and toggles to descending on second click", () => {
    render(<PeopleRoster persons={persons} />);
    const rowsAsc = screen
      .getAllByTestId(/roster-row-/)
      .map((r) => r.getAttribute("data-testid"));
    // Asc by name → Bob then Carol
    expect(rowsAsc).toEqual(["roster-row-p_bob", "roster-row-p_carol"]);

    fireEvent.click(screen.getByTestId("roster-header-name"));
    const rowsDesc = screen
      .getAllByTestId(/roster-row-/)
      .map((r) => r.getAttribute("data-testid"));
    expect(rowsDesc).toEqual(["roster-row-p_carol", "roster-row-p_bob"]);
  });

  it("sorts numerically by domain count when the Domains header is clicked", () => {
    render(<PeopleRoster persons={persons} />);
    fireEvent.click(screen.getByTestId("roster-header-domain"));
    const rows = screen
      .getAllByTestId(/roster-row-/)
      .map((r) => r.getAttribute("data-testid"));
    // Asc by domain count → Bob (1) then Carol (2)
    expect(rows).toEqual(["roster-row-p_bob", "roster-row-p_carol"]);
  });

  it("opens the PersonDetailDrawer on row click and closes on close", () => {
    render(<PeopleRoster persons={persons} />);
    expect(screen.queryByTestId("mock-drawer")).toBeNull();

    fireEvent.click(screen.getByTestId("roster-row-p_carol"));
    const drawer = screen.getByTestId("mock-drawer");
    expect(drawer).toBeInTheDocument();
    expect(drawer.getAttribute("data-person-id")).toBe("p_carol");

    fireEvent.click(screen.getByTestId("mock-drawer-close"));
    expect(screen.queryByTestId("mock-drawer")).toBeNull();
  });

  it("renders an empty-state row when there are no persons", () => {
    render(<PeopleRoster persons={[]} />);
    expect(screen.getByTestId("roster-empty")).toBeInTheDocument();
  });
});
