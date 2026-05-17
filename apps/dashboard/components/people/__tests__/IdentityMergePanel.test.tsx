/**
 * Tests for `IdentityMergePanel` (W2.A6).
 *
 * Covers: too-few-Persons empty state, picker behaviour, irreversibility
 * gating (must check ack before the destructive button enables), and the
 * happy-path POST to `/api/people/merge`.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { IdentityMergePanel } from "../IdentityMergePanel";
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
    status: "active",
    tenancyRole: over.tenancyRole ?? "member",
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

describe("IdentityMergePanel", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders an empty state when fewer than two Persons exist", () => {
    render(<IdentityMergePanel persons={[person({ personId: "p1" })]} />);
    expect(screen.getByTestId("identity-merge-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("identity-merge-keeper")).not.toBeInTheDocument();
  });

  it("disables Review merge until both pickers carry distinct selections", () => {
    const ps = [
      person({ personId: "p1", displayName: "Alice" }),
      person({ personId: "p2", displayName: "Alice (discord)" }),
    ];
    render(<IdentityMergePanel persons={ps} />);
    const review = screen.getByTestId("identity-merge-open-confirm");
    expect(review).toBeDisabled();

    fireEvent.change(screen.getByTestId("identity-merge-keeper"), {
      target: { value: "p1" },
    });
    expect(review).toBeDisabled(); // still missing mergee

    fireEvent.change(screen.getByTestId("identity-merge-mergee"), {
      target: { value: "p2" },
    });
    expect(review).not.toBeDisabled();
  });

  it("opens a confirmation modal with explicit irreversible copy", () => {
    const ps = [
      person({ personId: "p1", displayName: "Alice" }),
      person({
        personId: "p2",
        displayName: "Alice (discord)",
        identities: [
          { platform: "discord", platformUserId: "alice#1234" },
        ],
      }),
    ];
    render(<IdentityMergePanel persons={ps} />);
    fireEvent.change(screen.getByTestId("identity-merge-keeper"), {
      target: { value: "p1" },
    });
    fireEvent.change(screen.getByTestId("identity-merge-mergee"), {
      target: { value: "p2" },
    });
    fireEvent.click(screen.getByTestId("identity-merge-open-confirm"));

    expect(
      screen.getByTestId("identity-merge-confirm-modal"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("identity-merge-irreversible-copy"),
    ).toHaveTextContent(/this is irreversible/i);
    expect(screen.getByTestId("identity-merge-confirm-run")).toBeDisabled();
  });

  it("acknowledgement gate enables the destructive button", () => {
    const ps = [
      person({ personId: "p1" }),
      person({ personId: "p2" }),
    ];
    render(<IdentityMergePanel persons={ps} />);
    fireEvent.change(screen.getByTestId("identity-merge-keeper"), {
      target: { value: "p1" },
    });
    fireEvent.change(screen.getByTestId("identity-merge-mergee"), {
      target: { value: "p2" },
    });
    fireEvent.click(screen.getByTestId("identity-merge-open-confirm"));

    const run = screen.getByTestId("identity-merge-confirm-run");
    expect(run).toBeDisabled();
    fireEvent.click(screen.getByTestId("identity-merge-acknowledge"));
    expect(run).not.toBeDisabled();
  });

  it("renders an admin-only role-gated panel when the viewer is not an admin (D2)", () => {
    const ps = [
      person({ personId: "p1", displayName: "Alice" }),
      person({ personId: "p2", displayName: "Alice (whatsapp)" }),
    ];
    render(<IdentityMergePanel persons={ps} isAdmin={false} />);
    expect(screen.getByTestId("identity-merge-role-gated")).toBeInTheDocument();
    expect(screen.queryByTestId("identity-merge-keeper")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("identity-merge-open-confirm"),
    ).not.toBeInTheDocument();
  });

  it("threads adminPersonId through `merged_by` when provided (D2)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        keeper_id: "p1",
        mergee_id: "p2",
        identities_moved: 1,
      }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const ps = [
      person({ personId: "p1", displayName: "Alice" }),
      person({ personId: "p2", displayName: "Alice (whatsapp)" }),
    ];
    render(
      <IdentityMergePanel
        persons={ps}
        adminPersonId="admin-real-uuid"
        isAdmin={true}
      />,
    );
    fireEvent.change(screen.getByTestId("identity-merge-keeper"), {
      target: { value: "p1" },
    });
    fireEvent.change(screen.getByTestId("identity-merge-mergee"), {
      target: { value: "p2" },
    });
    fireEvent.click(screen.getByTestId("identity-merge-open-confirm"));
    fireEvent.click(screen.getByTestId("identity-merge-acknowledge"));
    fireEvent.click(screen.getByTestId("identity-merge-confirm-run"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.merged_by).toBe("admin-real-uuid");
  });

  it("POSTs to /api/people/merge with the picked ids on confirm", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        keeper_id: "p1",
        mergee_id: "p2",
        identities_moved: 1,
      }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const ps = [
      person({ personId: "p1", displayName: "Alice" }),
      person({
        personId: "p2",
        displayName: "Alice (discord)",
        identities: [
          { platform: "discord", platformUserId: "alice#1234" },
        ],
      }),
    ];
    render(<IdentityMergePanel persons={ps} />);
    fireEvent.change(screen.getByTestId("identity-merge-keeper"), {
      target: { value: "p1" },
    });
    fireEvent.change(screen.getByTestId("identity-merge-mergee"), {
      target: { value: "p2" },
    });
    fireEvent.click(screen.getByTestId("identity-merge-open-confirm"));
    fireEvent.click(screen.getByTestId("identity-merge-acknowledge"));
    fireEvent.click(screen.getByTestId("identity-merge-confirm-run"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/people/merge");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.keeper_id).toBe("p1");
    expect(body.mergee_id).toBe("p2");
    expect(typeof body.merged_by).toBe("string");
  });
});
