/**
 * PendingProposals — section hidden when no proposals; visible with
 * proposals; clicking "Confirm" calls fetch with the expected URL/body;
 * clicking "Confirm all" iterates over all proposals.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock, push: vi.fn() }),
}));

import { PendingProposals } from "../../components/people/PendingProposals";
import type { PersonRow } from "../../lib/ledger-client.types";

function proposed(over: Partial<PersonRow> = {}): PersonRow {
  return {
    personId: over.personId ?? "p_pending_a",
    displayName: over.displayName ?? "Carla Pending",
    email: over.email ?? "carla@x.co",
    position: null,
    status: "proposed",
    tenancyRole: null,
    identities: [
      { platform: "slack", platformUserId: "U-carla" },
    ],
    domainGrantCount: 0,
    resourceGrantCount: 0,
    roles: [],
    ownedDomains: [],
    ownedResources: [],
    receipt: {
      hash: "abc0",
      source: "people-projection",
      owner: "auto-discovery",
      classification: "internal",
    },
    ...over,
  };
}

beforeEach(() => {
  refreshMock.mockReset();
  vi.unstubAllGlobals();
});

function stubFetch(impl: (url: string, init?: RequestInit) => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl) as unknown as typeof fetch);
}

describe("PendingProposals", () => {
  it("renders nothing when there are no proposals", () => {
    const { container } = render(<PendingProposals proposals={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders one row per proposal", () => {
    render(
      <PendingProposals
        proposals={[
          proposed({ personId: "p_a", displayName: "Alice P" }),
          proposed({ personId: "p_b", displayName: "Bob P" }),
        ]}
      />,
    );
    expect(screen.getByTestId("pending-proposals")).toBeInTheDocument();
    expect(screen.getByTestId("pending-row-p_a")).toBeInTheDocument();
    expect(screen.getByTestId("pending-row-p_b")).toBeInTheDocument();
  });

  it("clicking Confirm POSTs to /api/people/[id]/confirm with confirmed_by", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    stubFetch(async (url, init) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    });
    render(
      <PendingProposals
        proposals={[proposed({ personId: "p_a", displayName: "Alice" })]}
        adminPersonId="admin-uuid"
      />,
    );
    fireEvent.click(screen.getByTestId("pending-confirm-p_a"));
    await waitFor(() => {
      expect(calls).toHaveLength(1);
    });
    expect(calls[0].url).toBe("/api/people/p_a/confirm");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      confirmed_by: "admin-uuid",
    });
    await waitFor(() => {
      expect(refreshMock).toHaveBeenCalled();
    });
  });

  it("clicking Archive POSTs to /api/people/[id]/archive with reason", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    stubFetch(async (url, init) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    });
    render(
      <PendingProposals
        proposals={[proposed({ personId: "p_a" })]}
        adminPersonId="admin-uuid"
      />,
    );
    fireEvent.click(screen.getByTestId("pending-archive-p_a"));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].url).toBe("/api/people/p_a/archive");
    expect(calls[0].init?.method).toBe("POST");
    const body = JSON.parse(String(calls[0].init?.body));
    expect(body.archived_by).toBe("admin-uuid");
    expect(body.reason).toBeTruthy();
  });

  it("clicking Confirm all iterates over each proposal", async () => {
    const calls: string[] = [];
    stubFetch(async (url) => {
      calls.push(String(url));
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    });
    render(
      <PendingProposals
        proposals={[
          proposed({ personId: "p_a" }),
          proposed({ personId: "p_b" }),
          proposed({ personId: "p_c" }),
        ]}
        adminPersonId="admin-uuid"
      />,
    );
    fireEvent.click(screen.getByTestId("pending-confirm-all"));
    await waitFor(() => expect(calls.length).toBe(3));
    expect(calls).toEqual([
      "/api/people/p_a/confirm",
      "/api/people/p_b/confirm",
      "/api/people/p_c/confirm",
    ]);
  });

  it("does not render Confirm all when only one proposal is pending", () => {
    render(<PendingProposals proposals={[proposed({ personId: "p_a" })]} />);
    expect(screen.queryByTestId("pending-confirm-all")).toBeNull();
  });

  it("surfaces an error message when the POST fails", async () => {
    stubFetch(async () =>
      new Response(JSON.stringify({ message: "kaboom" }), { status: 500 }),
    );
    render(
      <PendingProposals
        proposals={[proposed({ personId: "p_a" })]}
      />,
    );
    fireEvent.click(screen.getByTestId("pending-confirm-p_a"));
    await waitFor(() => {
      expect(screen.getByTestId("pending-error").textContent).toContain(
        "kaboom",
      );
    });
  });
});
