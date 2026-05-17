/**
 * Tests for `BulkConfirmDrawer` (W2.A6).
 *
 * Covers: empty-state suppression, default-all selection, toggle / select-all,
 * single-POST contract for the chosen ids, and error / success surfaces.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { BulkConfirmDrawer } from "../BulkConfirmDrawer";
import type { PersonRow } from "../../../lib/ledger-client.types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: vi.fn(),
    push: vi.fn(),
    replace: vi.fn(),
  }),
}));

function person(over: Partial<PersonRow>): PersonRow {
  return {
    personId: over.personId ?? "00000000-0000-0000-0000-000000000001",
    displayName: over.displayName ?? "Carol",
    email: over.email ?? null,
    position: over.position ?? null,
    status: "proposed",
    tenancyRole: null,
    identities: over.identities ?? [
      { platform: "slack", platformUserId: "U-1" },
    ],
    domainGrantCount: 0,
    resourceGrantCount: 0,
    roles: [],
    ownedDomains: [],
    ownedResources: [],
    receipt: {
      hash: "abc",
      source: "people-projection",
      owner: "system",
      classification: "internal",
    },
  } as unknown as PersonRow;
}

describe("BulkConfirmDrawer", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders nothing when there are no proposals", () => {
    const { container } = render(<BulkConfirmDrawer proposals={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("defaults to all rows selected and renders one row per proposal", () => {
    const proposals = [
      person({ personId: "p1", displayName: "Carol" }),
      person({ personId: "p2", displayName: "Bob" }),
      person({ personId: "p3", displayName: "Alice" }),
    ];
    render(<BulkConfirmDrawer proposals={proposals} />);
    expect(screen.getAllByTestId(/^bulk-confirm-row-/)).toHaveLength(3);
    expect(screen.getByTestId("bulk-confirm-check-p1")).toBeChecked();
    expect(screen.getByTestId("bulk-confirm-check-p2")).toBeChecked();
    expect(screen.getByTestId("bulk-confirm-check-p3")).toBeChecked();
    expect(screen.getByTestId("bulk-confirm-submit")).toHaveTextContent(
      /Confirm 3\/3/,
    );
  });

  it("Select-all toggles between all and none", () => {
    const proposals = [
      person({ personId: "p1" }),
      person({ personId: "p2" }),
    ];
    render(<BulkConfirmDrawer proposals={proposals} />);
    fireEvent.click(screen.getByTestId("bulk-confirm-toggle-all"));
    expect(screen.getByTestId("bulk-confirm-check-p1")).not.toBeChecked();
    expect(screen.getByTestId("bulk-confirm-check-p2")).not.toBeChecked();
    expect(screen.getByTestId("bulk-confirm-submit")).toBeDisabled();
    fireEvent.click(screen.getByTestId("bulk-confirm-toggle-all"));
    expect(screen.getByTestId("bulk-confirm-check-p1")).toBeChecked();
    expect(screen.getByTestId("bulk-confirm-check-p2")).toBeChecked();
  });

  it("POSTs all selected ids in one body", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        confirmed_count: 2,
        person_ids: ["p1", "p2"],
        entry_ids: ["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"],
      }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const proposals = [
      person({ personId: "p1" }),
      person({ personId: "p2" }),
    ];
    render(<BulkConfirmDrawer proposals={proposals} />);
    fireEvent.click(screen.getByTestId("bulk-confirm-submit"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/people/bulk-confirm");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.person_ids).toEqual(["p1", "p2"]);

    await waitFor(() =>
      expect(screen.getByTestId("bulk-confirm-success")).toHaveTextContent(
        /2 proposals confirmed/i,
      ),
    );
  });

  it("only submits checked rows after a partial deselect", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        confirmed_count: 1,
        person_ids: ["p1"],
        entry_ids: ["e1", "e2", "e3", "e4"],
      }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const proposals = [
      person({ personId: "p1" }),
      person({ personId: "p2" }),
    ];
    render(<BulkConfirmDrawer proposals={proposals} />);
    fireEvent.click(screen.getByTestId("bulk-confirm-check-p2"));
    expect(screen.getByTestId("bulk-confirm-check-p2")).not.toBeChecked();
    fireEvent.click(screen.getByTestId("bulk-confirm-submit"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.person_ids).toEqual(["p1"]);
  });

  it("renders WhatsApp organic-discovery provenance with +E.164", () => {
    const proposals = [
      person({
        personId: "p-wa",
        displayName: "+5215512345678",
        identities: [
          {
            platform: "whatsapp",
            platformUserId: "5215512345678@s.whatsapp.net",
            proposedBy: "worm:whatsapp_organic_discovery",
            addedAt: new Date(Date.now() - 2 * 60_000).toISOString(),
          },
        ],
      }),
    ];
    render(<BulkConfirmDrawer proposals={proposals} />);
    const provenance = screen.getByTestId("bulk-confirm-provenance-p-wa");
    expect(provenance).toHaveAttribute(
      "data-provenance-kind",
      "whatsapp_dm",
    );
    expect(provenance.textContent ?? "").toContain(
      "Proposed from WhatsApp DM with",
    );
    expect(provenance.textContent ?? "").toContain("+5215512345678");
    expect(provenance.textContent ?? "").toMatch(/2 minutes ago/);
  });

  it("renders a Slack-rooted proposal with the system provenance line", () => {
    const proposals = [
      person({
        personId: "p-slack",
        identities: [
          {
            platform: "slack",
            platformUserId: "U-1",
            proposedBy: "worm",
            addedAt: null,
          },
        ],
      }),
    ];
    render(<BulkConfirmDrawer proposals={proposals} />);
    const provenance = screen.getByTestId("bulk-confirm-provenance-p-slack");
    expect(provenance).toHaveAttribute("data-provenance-kind", "system");
    expect(provenance.textContent ?? "").toContain("Proposed by worm");
  });

  it("renders a system fallback when proposedBy is missing", () => {
    const proposals = [
      person({
        personId: "p-legacy",
        identities: [
          {
            platform: "slack",
            platformUserId: "U-2",
          },
        ],
      }),
    ];
    render(<BulkConfirmDrawer proposals={proposals} />);
    const provenance = screen.getByTestId(
      "bulk-confirm-provenance-p-legacy",
    );
    expect(provenance).toHaveAttribute("data-provenance-kind", "system");
    expect(provenance.textContent ?? "").toContain("Proposed by system");
  });

  it("surfaces upstream errors and preserves selection", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({ message: "boom" }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const proposals = [person({ personId: "p1" })];
    render(<BulkConfirmDrawer proposals={proposals} />);
    fireEvent.click(screen.getByTestId("bulk-confirm-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("bulk-confirm-error")).toHaveTextContent(/boom/),
    );
    // Selection survives the error so the admin can retry.
    expect(screen.getByTestId("bulk-confirm-check-p1")).toBeChecked();
  });
});
