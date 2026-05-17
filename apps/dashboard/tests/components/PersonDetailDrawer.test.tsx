/**
 * PersonDetailDrawer — fetches identities + roles + audit on open;
 * renders sections; "Unlink" calls DELETE with correct path; "Grant role"
 * form submission calls POST with correct payload.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

import { PersonDetailDrawer } from "../../components/people/PersonDetailDrawer";

const PERSON_ID = "p_abc";

const personPayload = {
  person: {
    personId: PERSON_ID,
    displayName: "Alice Reyes",
    email: "alice@x.co",
    position: "Analyst",
    status: "active",
    tenancyRole: "admin",
    identities: [],
    domainGrantCount: 1,
    resourceGrantCount: 0,
    roles: ["admin"],
    ownedDomains: [],
    ownedResources: [],
    receipt: {
      hash: "abc012345678",
      source: "people-projection",
      owner: PERSON_ID,
      classification: "internal",
    },
  },
};

const identitiesPayload = {
  identities: [
    {
      platform: "slack",
      platformUserId: "U-alice",
      displayName: "alice",
      addedAt: "2026-04-26T10:00:00.000Z",
    },
  ],
};

const rolesPayload = {
  roles: [
    {
      facet: "tenancy",
      role: "admin",
      scopeId: null,
      scopeType: null,
      grantedBy: "system",
      grantedAt: "2026-04-26T10:00:00.000Z",
      revokedAt: null,
    },
    {
      facet: "domain",
      role: "owner",
      scopeId: "d_finance",
      scopeType: "domain",
      grantedBy: "admin",
      grantedAt: "2026-04-26T10:00:00.000Z",
      revokedAt: null,
    },
  ],
};

const auditPayload = {
  entries: [
    {
      seq: "42",
      ts: "2026-04-26T10:00:00.000Z",
      kind: "execute",
      tool: "emit_role_assigned",
      hash: "deadbeef0000",
      args: {},
    },
    {
      seq: "41",
      ts: "2026-04-26T09:30:00.000Z",
      kind: "execute",
      tool: "emit_person_confirmed",
      hash: "cafebabe0000",
      args: {},
    },
  ],
};

function stubFetch(impl: (url: string, init?: RequestInit) => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl) as unknown as typeof fetch);
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

function defaultFetch(extra?: (url: string, init?: RequestInit) => Promise<Response> | null) {
  return async (url: string, init?: RequestInit) => {
    if (extra) {
      const r = await extra(url, init);
      if (r) return r;
    }
    if (url === `/api/people/${PERSON_ID}`) {
      return new Response(JSON.stringify(personPayload), { status: 200 });
    }
    if (url === `/api/people/${PERSON_ID}/identities`) {
      return new Response(JSON.stringify(identitiesPayload), { status: 200 });
    }
    if (url === `/api/people/${PERSON_ID}/roles`) {
      return new Response(JSON.stringify(rolesPayload), { status: 200 });
    }
    if (url.startsWith(`/api/people/${PERSON_ID}/audit`)) {
      return new Response(JSON.stringify(auditPayload), { status: 200 });
    }
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  };
}

describe("PersonDetailDrawer", () => {
  it("fetches the four endpoints on open and renders the sections", async () => {
    const seen: string[] = [];
    stubFetch(async (url, init) => {
      seen.push(String(url));
      return defaultFetch()(url, init);
    });

    render(
      <PersonDetailDrawer personId={PERSON_ID} onClose={() => {}} />,
    );

    await waitFor(() => {
      expect(seen).toEqual(
        expect.arrayContaining([
          `/api/people/${PERSON_ID}`,
          `/api/people/${PERSON_ID}/identities`,
          `/api/people/${PERSON_ID}/roles`,
          `/api/people/${PERSON_ID}/audit?limit=20`,
        ]),
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("drawer-name").textContent).toBe(
        "Alice Reyes",
      );
    });

    expect(screen.getByTestId("drawer-identities-section")).toBeInTheDocument();
    expect(screen.getByTestId("drawer-roles-section")).toBeInTheDocument();
    expect(screen.getByTestId("drawer-audit-section")).toBeInTheDocument();
    expect(screen.getByTestId("identity-row-slack-U-alice")).toBeInTheDocument();
    expect(screen.getByTestId("audit-row-42")).toBeInTheDocument();
  });

  it("Unlink calls DELETE on the correct identity path with unlinked_by", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    stubFetch(async (url, init) => {
      calls.push({ url, init });
      return defaultFetch()(url, init);
    });

    render(
      <PersonDetailDrawer
        personId={PERSON_ID}
        onClose={() => {}}
        adminPersonId="admin-uuid"
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId("identity-row-slack-U-alice")).toBeInTheDocument(),
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("identity-unlink-slack-U-alice"));
    });
    await waitFor(() => {
      const del = calls.find(
        (c) => c.init?.method === "DELETE" && c.url.includes("/identities/"),
      );
      expect(del).toBeTruthy();
      expect(del!.url).toBe(
        `/api/people/${PERSON_ID}/identities/slack/U-alice`,
      );
      const body = JSON.parse(String(del!.init!.body));
      expect(body.unlinked_by).toBe("admin-uuid");
    });
  });

  it("Grant role form submits the right payload for tenancy facet", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    stubFetch(async (url, init) => {
      calls.push({ url, init });
      return defaultFetch()(url, init);
    });

    render(
      <PersonDetailDrawer
        personId={PERSON_ID}
        onClose={() => {}}
        adminPersonId="admin-uuid"
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId("grant-submit")).toBeInTheDocument(),
    );

    // Default facet is tenancy with role "installer" — change role to "member"
    const roleSel = screen.getByTestId("grant-role") as HTMLSelectElement;
    fireEvent.change(roleSel, { target: { value: "member" } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("grant-submit"));
    });

    await waitFor(() => {
      const post = calls.find(
        (c) =>
          c.init?.method === "POST" &&
          c.url === `/api/people/${PERSON_ID}/roles`,
      );
      expect(post).toBeTruthy();
      const body = JSON.parse(String(post!.init!.body));
      expect(body).toEqual({
        facet: "tenancy",
        role: "member",
        granted_by: "admin-uuid",
      });
    });
  });

  it("Grant role for domain facet validates scope_id", async () => {
    stubFetch(defaultFetch());
    render(
      <PersonDetailDrawer
        personId={PERSON_ID}
        onClose={() => {}}
        adminPersonId="admin-uuid"
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("grant-facet")).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByTestId("grant-facet"), {
      target: { value: "domain" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("grant-submit"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("grant-error").textContent).toContain(
        "scope_id",
      );
    });
  });

  it("calls onClose when the close button is clicked", async () => {
    stubFetch(defaultFetch());
    const onClose = vi.fn();
    render(<PersonDetailDrawer personId={PERSON_ID} onClose={onClose} />);
    await waitFor(() =>
      expect(screen.getByTestId("drawer-close")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("drawer-close"));
    expect(onClose).toHaveBeenCalled();
  });
});
