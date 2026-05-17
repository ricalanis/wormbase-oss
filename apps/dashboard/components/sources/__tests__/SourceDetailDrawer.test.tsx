import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SourceDetailDrawer } from "../SourceDetailDrawer";
import type { SourceRow as SourceRowModel } from "../../../lib/ledger-client.types";

function makeRow(overrides: Partial<SourceRowModel> = {}): SourceRowModel {
  return {
    sourceId: "00000000-0000-0000-0000-000000000001",
    uri: "postgres://example/db",
    kind: "postgres",
    addedByPerson: "ricardo",
    addedAt: "2026-04-27T12:00:00Z",
    addedViaFlow: "dashboard_form",
    addedInResponseTo: null,
    rowCount: 1234,
    lastProfileTs: "2026-04-27T12:30:00Z",
    receipt: {
      hash: "abcdefabcdef",
      source: "postgres://example/db",
      owner: "ricardo",
      classification: "internal",
    },
    bronzed: true,
    silvered: false,
    golded: false,
    classification: "internal",
    maintainerPersonId: null,
    maintainerName: null,
    ownerDomain: null,
    ...overrides,
  };
}

describe("SourceDetailDrawer (W2.A5)", () => {
  let originalFetch: typeof globalThis.fetch | undefined;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    if (originalFetch) globalThis.fetch = originalFetch;
  });

  it("renders the source receipt + classification select", () => {
    render(
      <SourceDetailDrawer
        source={makeRow()}
        currentPersonId="11111111-1111-1111-1111-111111111111"
        onClose={() => {}}
      />,
    );
    expect(screen.getByTestId("source-detail-drawer")).toBeInTheDocument();
    expect(
      screen.getByTestId("drawer-classification-select"),
    ).toHaveValue("internal");
  });

  it("posts to /api/sources/{id}/classification when classification changes", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      return new Response(
        JSON.stringify({
          ok: true,
          persisted: true,
          receipt: { hash: "feedface1234", source: "x", classification: "pii" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof globalThis.fetch;

    const updates: Partial<SourceRowModel>[] = [];
    render(
      <SourceDetailDrawer
        source={makeRow()}
        currentPersonId="11111111-1111-1111-1111-111111111111"
        onClose={() => {}}
        onSourceUpdated={(next) => updates.push(next)}
      />,
    );
    fireEvent.change(screen.getByTestId("drawer-classification-select"), {
      target: { value: "pii" },
    });
    fireEvent.click(screen.getByTestId("drawer-classification-save"));
    await waitFor(() => {
      expect(screen.getByTestId("drawer-save-result")).toBeInTheDocument();
    });
    expect(calls.length).toBe(1);
    expect(calls[0].url).toMatch(
      /\/api\/sources\/00000000-0000-0000-0000-000000000001\/classification$/,
    );
    expect(updates).toContainEqual({ classification: "pii" });
  });

  it("writes emit_resource_role_assigned via /api/people/{id}/roles for maintainer", async () => {
    const calls: { url: string; body?: string }[] = [];
    globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), body: String(init?.body ?? "") });
      return new Response(
        JSON.stringify({
          entry_ids: ["aaaaaaaaaaaa1111", "aaaaaaaaaaaa2222"],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof globalThis.fetch;

    render(
      <SourceDetailDrawer
        source={makeRow()}
        people={[
          { personId: "22222222-2222-2222-2222-222222222222", displayName: "Alice" },
        ]}
        currentPersonId="11111111-1111-1111-1111-111111111111"
        onClose={() => {}}
      />,
    );
    fireEvent.change(screen.getByTestId("drawer-maintainer-select"), {
      target: { value: "22222222-2222-2222-2222-222222222222" },
    });
    fireEvent.click(screen.getByTestId("drawer-maintainer-save"));
    await waitFor(() => {
      expect(screen.getByTestId("drawer-save-result")).toBeInTheDocument();
    });
    expect(calls[0].url).toMatch(
      /\/api\/people\/22222222-2222-2222-2222-222222222222\/roles$/,
    );
    const sentBody = JSON.parse(calls[0].body ?? "{}");
    expect(sentBody).toMatchObject({
      facet: "resource",
      role: "maintainer",
      scope_id: "00000000-0000-0000-0000-000000000001",
      scope_type: "source",
      granted_by: "11111111-1111-1111-1111-111111111111",
    });
  });

  it("renders the default-lake notice for the provisioned-at-install lake", () => {
    render(
      <SourceDetailDrawer
        source={makeRow({
          kind: "local_lake",
          addedViaFlow: "provisioned_at_install",
        })}
        currentPersonId="11111111-1111-1111-1111-111111111111"
        onClose={() => {}}
      />,
    );
    expect(screen.getByTestId("drawer-default-lake-note")).toBeInTheDocument();
  });

  it("invokes onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(
      <SourceDetailDrawer
        source={makeRow()}
        currentPersonId="11111111-1111-1111-1111-111111111111"
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId("drawer-close"));
    expect(onClose).toHaveBeenCalled();
  });
});
