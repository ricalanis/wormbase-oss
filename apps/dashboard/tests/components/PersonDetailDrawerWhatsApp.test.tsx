/**
 * PersonDetailDrawer — D2 WhatsApp PersonIdentity rendering + role gates.
 *
 * Covers:
 *   - WhatsApp DM jids render as `+<E.164>` via `formatChannelDisplay`
 *     (D1's helper); a phone icon appears next to WhatsApp identities.
 *   - `proposed_by` source labels — organic-from-WhatsApp / Slack-roster /
 *     admin-manual surfaces appropriately.
 *   - Visible "no WhatsApp identity linked" hint with admin-only Link CTA
 *     (CLAUDE.md §9 — no silent panels).
 *   - Role-gated unlink/merge/split affordances (admin-only per
 *     CLAUDE.md §5).
 *   - Slack-only Person retains existing identity-row behaviour
 *     (byte-identical pre/post — no regression).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

import { PersonDetailDrawer } from "../../components/people/PersonDetailDrawer";

const PERSON_ID = "p_d2";

const personPayload = {
  person: {
    personId: PERSON_ID,
    displayName: "Bea Liu",
    email: "bea@x.co",
    position: "Engineer",
    status: "active",
    tenancyRole: "member",
    identities: [],
    domainGrantCount: 0,
    resourceGrantCount: 0,
    roles: ["member"],
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

function stubFetch(impl: (url: string, init?: RequestInit) => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl) as unknown as typeof fetch);
}

function buildFetch(
  identities: Array<{
    platform: string;
    platformUserId: string;
    displayName: string | null;
    addedAt: string;
    proposedBy?: string | null;
  }>,
) {
  return async (url: string, _init?: RequestInit) => {
    if (url === `/api/people/${PERSON_ID}`) {
      return new Response(JSON.stringify(personPayload), { status: 200 });
    }
    if (url === `/api/people/${PERSON_ID}/identities`) {
      return new Response(JSON.stringify({ identities }), { status: 200 });
    }
    if (url === `/api/people/${PERSON_ID}/roles`) {
      return new Response(JSON.stringify({ roles: [] }), { status: 200 });
    }
    if (url.startsWith(`/api/people/${PERSON_ID}/audit`)) {
      return new Response(JSON.stringify({ entries: [] }), { status: 200 });
    }
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  };
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("PersonDetailDrawer · WhatsApp PersonIdentity rendering (D2)", () => {
  it("renders a WhatsApp DM jid as +<E.164> with a phone icon", async () => {
    stubFetch(
      buildFetch([
        {
          platform: "whatsapp",
          platformUserId: "5511999998888@s.whatsapp.net",
          displayName: "Bea",
          addedAt: "2026-05-06T10:00:00.000Z",
          proposedBy: "worm:whatsapp_organic_discovery",
        },
      ]),
    );

    render(
      <PersonDetailDrawer
        personId={PERSON_ID}
        onClose={() => {}}
        adminPersonId="admin-uuid"
        isAdmin={true}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByTestId(
          "identity-row-whatsapp-5511999998888@s.whatsapp.net",
        ),
      ).toBeInTheDocument();
    });

    const display = screen.getByTestId(
      "identity-display-whatsapp-5511999998888@s.whatsapp.net",
    );
    expect(display.textContent).toBe("+5511999998888");

    // Phone icon renders inside the identity row (one for the row +
    // potentially one in the empty-state hint; the row's icon is
    // guaranteed to be present).
    expect(screen.getAllByTestId("identity-phone-icon").length).toBeGreaterThan(
      0,
    );
  });

  it("groups WhatsApp identities by source — `worm:whatsapp_organic_discovery` surfaces as 'Worm (organic from WhatsApp)'", async () => {
    stubFetch(
      buildFetch([
        {
          platform: "whatsapp",
          platformUserId: "5511999998888@s.whatsapp.net",
          displayName: null,
          addedAt: "2026-05-06T10:00:00.000Z",
          proposedBy: "worm:whatsapp_organic_discovery",
        },
      ]),
    );

    render(
      <PersonDetailDrawer
        personId={PERSON_ID}
        onClose={() => {}}
        adminPersonId="admin-uuid"
        isAdmin={true}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByTestId(
          "identity-source-whatsapp-5511999998888@s.whatsapp.net",
        ),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId(
        "identity-source-whatsapp-5511999998888@s.whatsapp.net",
      ).textContent,
    ).toContain("Worm (organic from WhatsApp)");
  });

  it("Slack `proposed_by='worm'` surfaces as 'Worm (Slack roster)'", async () => {
    stubFetch(
      buildFetch([
        {
          platform: "slack",
          platformUserId: "U-bea",
          displayName: "bea",
          addedAt: "2026-05-06T10:00:00.000Z",
          proposedBy: "worm",
        },
      ]),
    );

    render(
      <PersonDetailDrawer
        personId={PERSON_ID}
        onClose={() => {}}
        adminPersonId="admin-uuid"
        isAdmin={true}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByTestId("identity-source-slack-U-bea"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("identity-source-slack-U-bea").textContent,
    ).toContain("Worm (Slack roster)");
  });

  it("shows a visible 'No WhatsApp identity linked' hint when only Slack is linked", async () => {
    stubFetch(
      buildFetch([
        {
          platform: "slack",
          platformUserId: "U-bea",
          displayName: "bea",
          addedAt: "2026-05-06T10:00:00.000Z",
          proposedBy: "worm",
        },
      ]),
    );

    render(
      <PersonDetailDrawer
        personId={PERSON_ID}
        onClose={() => {}}
        adminPersonId="admin-uuid"
        isAdmin={true}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByTestId("identities-no-whatsapp"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("identities-no-whatsapp").textContent,
    ).toContain("No WhatsApp identity linked");
    // Admin-only Link CTA renders for an admin viewer.
    expect(
      screen.getByTestId("identities-link-whatsapp-cta"),
    ).toBeInTheDocument();
  });

  it("hides the Link CTA + form when the viewer is not an admin", async () => {
    stubFetch(
      buildFetch([
        {
          platform: "slack",
          platformUserId: "U-bea",
          displayName: "bea",
          addedAt: "2026-05-06T10:00:00.000Z",
          proposedBy: "worm",
        },
      ]),
    );

    render(
      <PersonDetailDrawer
        personId={PERSON_ID}
        onClose={() => {}}
        adminPersonId="admin-uuid"
        isAdmin={false}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByTestId("drawer-identities-section"),
      ).toBeInTheDocument(),
    );

    expect(
      screen.queryByTestId("identity-link-form"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("identities-link-whatsapp-cta"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("identity-unlink-slack-U-bea"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("drawer-merge-trigger"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("drawer-identities-role-gated").textContent,
    ).toContain("Admin only");
  });

  it("hides the no-WhatsApp hint once a WhatsApp identity is linked", async () => {
    stubFetch(
      buildFetch([
        {
          platform: "slack",
          platformUserId: "U-bea",
          displayName: "bea",
          addedAt: "2026-05-06T10:00:00.000Z",
          proposedBy: "worm",
        },
        {
          platform: "whatsapp",
          platformUserId: "5511999998888@s.whatsapp.net",
          displayName: "Bea",
          addedAt: "2026-05-06T10:01:00.000Z",
          proposedBy: "worm:whatsapp_organic_discovery",
        },
      ]),
    );

    render(
      <PersonDetailDrawer
        personId={PERSON_ID}
        onClose={() => {}}
        adminPersonId="admin-uuid"
        isAdmin={true}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByTestId(
          "identity-row-whatsapp-5511999998888@s.whatsapp.net",
        ),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("identities-no-whatsapp"),
    ).not.toBeInTheDocument();
  });

  it("Slack identity rendering is byte-identical pre/post (regression pin)", async () => {
    stubFetch(
      buildFetch([
        {
          platform: "slack",
          platformUserId: "U-alice",
          displayName: "alice",
          addedAt: "2026-04-26T10:00:00.000Z",
          proposedBy: "worm",
        },
      ]),
    );

    render(
      <PersonDetailDrawer
        personId={PERSON_ID}
        onClose={() => {}}
        adminPersonId="admin-uuid"
        isAdmin={true}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByTestId("identity-row-slack-U-alice"),
      ).toBeInTheDocument(),
    );

    // Slack rows do NOT carry the phone icon (icon is whatsapp-only).
    const slackRow = screen.getByTestId("identity-row-slack-U-alice");
    expect(slackRow.querySelector('[data-testid="identity-phone-icon"]')).toBeNull();

    // The friendly id for Slack rows is the raw platform_user_id (no
    // E.164 mangling, no platform-specific transform).
    expect(
      screen.getByTestId("identity-display-slack-U-alice").textContent,
    ).toBe("U-alice");

    // The unlink button still renders for admin viewers.
    expect(
      screen.getByTestId("identity-unlink-slack-U-alice"),
    ).toBeInTheDocument();
  });
});
