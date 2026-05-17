/**
 * SplitDialog — admin extracts a subset of identities into a new Person.
 *
 * A6 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));

import { SplitDialog } from "../../components/people/SplitDialog";

const SOURCE_ID = "00000000-0000-0000-0000-000000000099";

const identities = [
  {
    platform: "slack",
    platformUserId: "U-alice",
    displayName: "alice",
    addedAt: "2026-04-26T10:00:00.000Z",
  },
  {
    platform: "discord",
    platformUserId: "bob#1234",
    displayName: "Bob",
    addedAt: "2026-04-26T10:00:00.000Z",
  },
];

beforeEach(() => {
  vi.unstubAllGlobals();
});

function defaultFetch(opts?: {
  splitStatus?: number;
  splitBody?: unknown;
}) {
  return async (url: string, init?: RequestInit) => {
    if (
      url === `/api/people/${encodeURIComponent(SOURCE_ID)}/split` &&
      init?.method === "POST"
    ) {
      return new Response(
        JSON.stringify(
          opts?.splitBody ?? {
            source_person_id: SOURCE_ID,
            new_person_id: "new-uuid",
            identities_moved: 1,
            entry_ids: [],
          },
        ),
        { status: opts?.splitStatus ?? 200 },
      );
    }
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  };
}

describe("SplitDialog", () => {
  it("renders identity checkboxes; confirm is disabled until name + selection", async () => {
    vi.stubGlobal("fetch", vi.fn(defaultFetch()));
    render(
      <SplitDialog
        sourcePersonId={SOURCE_ID}
        sourceName="Alice + Bob"
        identities={identities}
        open={true}
        onClose={() => {}}
      />,
    );
    expect(
      screen.getByTestId("split-identity-slack-U-alice"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("split-identity-discord-bob#1234"),
    ).toBeInTheDocument();

    const confirm = screen.getByTestId("split-confirm") as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);

    // Pick one identity but no name yet — still disabled.
    fireEvent.click(screen.getByTestId("split-checkbox-discord-bob#1234"));
    expect(confirm.disabled).toBe(true);

    // Add name — enabled.
    fireEvent.change(screen.getByTestId("split-name"), {
      target: { value: "Bob" },
    });
    expect(confirm.disabled).toBe(false);
  });

  it("POSTs to /api/people/[id]/split with the chosen identities and metadata", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, init });
        return defaultFetch()(url, init);
      }),
    );

    render(
      <SplitDialog
        sourcePersonId={SOURCE_ID}
        sourceName="Alice + Bob"
        identities={identities}
        open={true}
        onClose={() => {}}
        adminPersonId="admin-uuid"
      />,
    );

    fireEvent.click(screen.getByTestId("split-checkbox-discord-bob#1234"));
    fireEvent.change(screen.getByTestId("split-name"), {
      target: { value: "Bob" },
    });
    fireEvent.change(screen.getByTestId("split-email"), {
      target: { value: "bob@x.co" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("split-confirm"));
    });

    await waitFor(() => {
      const post = calls.find(
        (c) =>
          c.url === `/api/people/${encodeURIComponent(SOURCE_ID)}/split` &&
          c.init?.method === "POST",
      );
      expect(post).toBeTruthy();
      const body = JSON.parse(String(post!.init!.body));
      expect(body.new_person_name).toBe("Bob");
      expect(body.new_person_email).toBe("bob@x.co");
      expect(body.split_by).toBe("admin-uuid");
      expect(body.identities_to_move).toEqual([
        { platform: "discord", platform_user_id: "bob#1234" },
      ]);
    });
  });

  it("shows an error when the split endpoint returns 4xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        defaultFetch({
          splitStatus: 502,
          splitBody: { message: "worm-core down" },
        }),
      ),
    );
    render(
      <SplitDialog
        sourcePersonId={SOURCE_ID}
        sourceName="Source"
        identities={identities}
        open={true}
        onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId("split-checkbox-slack-U-alice"));
    fireEvent.change(screen.getByTestId("split-name"), {
      target: { value: "X" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("split-confirm"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("split-error").textContent).toMatch(
        /worm-core down/,
      );
    });
  });
});
