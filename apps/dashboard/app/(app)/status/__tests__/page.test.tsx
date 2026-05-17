/**
 * /status/[object_kind]/[object_id] — page-level tests
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
    getObjectStatus: vi.fn(async () => ({
      kind: "channel" as const,
      objectId: "install-1",
      state: "works" as const,
      summary: "slack install is active.",
      recoveryHint: null,
      capabilities: ["ingest", "send"],
      label: "Channel adapter · slack",
      probeImplemented: false,
    })),
    isStatusKind: actual.isStatusKind,
  };
});

const { notFoundCalls } = vi.hoisted(() => ({ notFoundCalls: { count: 0 } }));

vi.mock("next/navigation", () => ({
  notFound: () => {
    notFoundCalls.count++;
    throw new Error("NEXT_NOT_FOUND");
  },
}));

import ObjectStatusPage from "../[object_kind]/[object_id]/page";

describe("/status/[object_kind]/[object_id] page", () => {
  it("renders the status view for a valid kind + id", async () => {
    const ui = await ObjectStatusPage({
      params: Promise.resolve({
        object_kind: "channel",
        object_id: "install-1",
      }),
    });
    render(ui);
    expect(screen.getByTestId("object-status-channel")).toBeInTheDocument();
    expect(screen.getByTestId("object-status-id-channel")).toHaveTextContent(
      "install-1",
    );
  });

  it("renders the works accent for healthy objects", async () => {
    const ui = await ObjectStatusPage({
      params: Promise.resolve({
        object_kind: "channel",
        object_id: "install-1",
      }),
    });
    render(ui);
    expect(
      screen.getByTestId("capability-status-channel-install-1-works"),
    ).toBeInTheDocument();
  });

  it("calls notFound for an unknown object_kind", async () => {
    notFoundCalls.count = 0;
    await expect(
      ObjectStatusPage({
        params: Promise.resolve({
          object_kind: "garbage",
          object_id: "id",
        }),
      }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFoundCalls.count).toBe(1);
  });
});
