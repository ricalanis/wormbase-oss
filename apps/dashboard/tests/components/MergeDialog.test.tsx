/**
 * MergeDialog — fetches /api/people on open; admin selects a mergee from
 * the candidates list; "Merge & archive mergee" POSTs to /api/people/merge.
 *
 * A6 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

import { MergeDialog } from "../../components/people/MergeDialog";

const KEEPER_ID = "00000000-0000-0000-0000-000000000001";
const MERGEE_ID = "00000000-0000-0000-0000-000000000002";

const peoplePayload = {
  persons: [
    {
      personId: KEEPER_ID,
      displayName: "Bob (Slack)",
      email: "bob@x.co",
      position: null,
      status: "active",
      tenancyRole: "member",
      identities: [{ platform: "slack", platformUserId: "U-bob" }],
      domainGrantCount: 0,
      resourceGrantCount: 0,
      roles: [],
      ownedDomains: [],
      ownedResources: [],
      receipt: { hash: "h", source: "p", owner: KEEPER_ID, classification: "internal" },
    },
    {
      personId: MERGEE_ID,
      displayName: "Bob (Discord)",
      email: "bob@x.co",
      position: null,
      status: "active",
      tenancyRole: "member",
      identities: [{ platform: "discord", platformUserId: "bob#1234" }],
      domainGrantCount: 0,
      resourceGrantCount: 0,
      roles: [],
      ownedDomains: [],
      ownedResources: [],
      receipt: { hash: "h", source: "p", owner: MERGEE_ID, classification: "internal" },
    },
  ],
};

beforeEach(() => {
  vi.unstubAllGlobals();
});

function defaultFetch(opts?: {
  mergeStatus?: number;
  mergeBody?: unknown;
}) {
  return async (url: string, init?: RequestInit) => {
    if (url === "/api/people") {
      return new Response(JSON.stringify(peoplePayload), { status: 200 });
    }
    if (url === "/api/people/merge" && init?.method === "POST") {
      return new Response(
        JSON.stringify(
          opts?.mergeBody ?? {
            keeper_id: KEEPER_ID,
            mergee_id: MERGEE_ID,
            identities_moved: 1,
            entry_ids: [],
          },
        ),
        { status: opts?.mergeStatus ?? 200 },
      );
    }
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  };
}

describe("MergeDialog", () => {
  it("loads /api/people on open and lists other Persons as candidates (excluding self)", async () => {
    vi.stubGlobal("fetch", vi.fn(defaultFetch()));
    render(
      <MergeDialog
        keeperId={KEEPER_ID}
        keeperName="Bob (Slack)"
        open={true}
        onClose={() => {}}
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByTestId(`merge-candidate-${MERGEE_ID}`),
      ).toBeInTheDocument();
    });
    // Self should not appear as a candidate.
    expect(
      screen.queryByTestId(`merge-candidate-${KEEPER_ID}`),
    ).not.toBeInTheDocument();
  });

  it("disables the confirm button until a mergee is picked, then POSTs to /api/people/merge", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        return defaultFetch()(url, init);
      }),
    );

    render(
      <MergeDialog
        keeperId={KEEPER_ID}
        keeperName="Bob (Slack)"
        open={true}
        onClose={() => {}}
        adminPersonId="admin-uuid"
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByTestId(`merge-candidate-${MERGEE_ID}`),
      ).toBeInTheDocument(),
    );

    // Confirm starts disabled.
    expect(
      (screen.getByTestId("merge-confirm") as HTMLButtonElement).disabled,
    ).toBe(true);

    // Pick the mergee.
    fireEvent.click(screen.getByTestId(`merge-candidate-${MERGEE_ID}`));

    // Side-by-side preview now visible.
    expect(screen.getByTestId("merge-preview")).toBeInTheDocument();

    // Click confirm.
    await act(async () => {
      fireEvent.click(screen.getByTestId("merge-confirm"));
    });

    await waitFor(() => {
      const post = calls.find(
        (c) => c.url === "/api/people/merge" && c.init?.method === "POST",
      );
      expect(post).toBeTruthy();
      const body = JSON.parse(String(post!.init!.body));
      expect(body).toEqual({
        keeper_id: KEEPER_ID,
        mergee_id: MERGEE_ID,
        merged_by: "admin-uuid",
      });
    });
  });

  it("shows an error when /api/people/merge returns 4xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        defaultFetch({
          mergeStatus: 502,
          mergeBody: { message: "worm-core unreachable" },
        }),
      ),
    );

    render(
      <MergeDialog
        keeperId={KEEPER_ID}
        keeperName="Bob (Slack)"
        open={true}
        onClose={() => {}}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByTestId(`merge-candidate-${MERGEE_ID}`),
      ).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId(`merge-candidate-${MERGEE_ID}`));
    await act(async () => {
      fireEvent.click(screen.getByTestId("merge-confirm"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("merge-error").textContent).toMatch(
        /worm-core unreachable/,
      );
    });
  });
});
