/**
 * /logs/[object_kind]/[object_id] — page-level tests
 * (Onboarding Sub-wave B, 2026-05-30).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../../../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () => "tenant-uuid",
}));

vi.mock("../../../../lib/onboard", async () => {
  const actual = await vi.importActual<typeof import("../../../../lib/onboard")>(
    "../../../../lib/onboard",
  );
  return {
    ...actual,
    getObjectLogs: vi.fn(async () => ({
      entries: [
        {
          hash: "abc123def456",
          ts: "2026-05-30T10:00:00Z",
          kind: "source_proposed",
          quadrant: "execute" as const,
          summary: '{"args":{"source_id":"src-1"}}',
        },
      ],
      total: 1,
      nextOffset: null,
      scanned: true,
    })),
    isStatusKind: actual.isStatusKind,
  };
});

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

import ObjectLogsPage from "../[object_kind]/[object_id]/page";

describe("/logs/[object_kind]/[object_id] page", () => {
  it("renders the logs table for a valid kind + id", async () => {
    const ui = await ObjectLogsPage({
      params: Promise.resolve({
        object_kind: "connector",
        object_id: "src-1",
      }),
      searchParams: Promise.resolve({}),
    });
    render(ui);
    expect(screen.getByTestId("object-logs-connector")).toBeInTheDocument();
    expect(
      screen.getByTestId("object-logs-table-connector"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("object-log-row-abc123def456"),
    ).toBeInTheDocument();
  });

  it("renders the empty-state when no entries match", async () => {
    const lo = await import("../../../../lib/onboard");
    vi.mocked(lo.getObjectLogs).mockResolvedValueOnce({
      entries: [],
      total: 0,
      nextOffset: null,
      scanned: true,
    });
    const ui = await ObjectLogsPage({
      params: Promise.resolve({
        object_kind: "person",
        object_id: "nope",
      }),
      searchParams: Promise.resolve({}),
    });
    render(ui);
    expect(screen.getByTestId("object-logs-empty-person")).toBeInTheDocument();
  });

  it("calls notFound for an unknown object_kind", async () => {
    await expect(
      ObjectLogsPage({
        params: Promise.resolve({
          object_kind: "garbage",
          object_id: "id",
        }),
        searchParams: Promise.resolve({}),
      }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
