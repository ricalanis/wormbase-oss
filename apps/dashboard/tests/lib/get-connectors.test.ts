/**
 * /lake/connectors accessor tests — L3 Sub-wave D (2026-05-29).
 *
 * Mocks ``fetch`` for the registry endpoint and verifies:
 *
 *   * Real registry response is parsed + grouped by status.
 *   * Registry-unreachable triggers the static fallback + sets the
 *     ``registryUnreachable`` flag.
 *   * Per-tenant connection state folds active sources by kind.
 *   * Status-group bins (production / preview / coming_soon) are
 *     stable and admin-readable.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const COMPANY_ID = "a8989ece-b38a-5811-9625-327a79a65f90";

// Mock next/headers to return a stable host header for the proxy URL
// resolution.
vi.mock("next/headers", () => ({
  headers: async () => new Map<string, string>([["host", "localhost:3000"]]),
}));

// Mock the ledger-client getSources so we can drive connection state
// without standing up Postgres.
vi.mock("../../lib/ledger-client", () => ({
  getSources: vi.fn(async () => []),
}));

const fetchMock = vi.fn();

describe("getConnectorCatalog (registry reachable)", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("groups registry entries by status", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        kinds: [
          {
            kind: "postgres",
            label: "Postgres",
            status: "production",
            status_note: "Production-grade.",
            capabilities: ["discover", "profile", "sample"],
          },
          {
            kind: "whatsapp_send",
            label: "WhatsApp send",
            status: "preview",
            status_note: "Preview — operator-approved scopes required.",
            capabilities: ["send"],
          },
          {
            kind: "discord",
            label: "Discord",
            status: "coming_soon",
            status_note: "Coming soon.",
            capabilities: [],
          },
        ],
      }),
      text: async () => "",
    });

    const mod = await import("../../lib/connectors");
    const catalog = await mod.getConnectorCatalog(COMPANY_ID);
    expect(catalog.production).toHaveLength(1);
    expect(catalog.production[0].kind).toBe("postgres");
    expect(catalog.preview).toHaveLength(1);
    expect(catalog.preview[0].kind).toBe("whatsapp_send");
    expect(catalog.comingSoon).toHaveLength(1);
    expect(catalog.comingSoon[0].kind).toBe("discord");
    expect(catalog.registryUnreachable).toBe(false);
  });

  it("folds active sources into per-kind connection state", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        kinds: [
          {
            kind: "postgres",
            label: "Postgres",
            status: "production",
            status_note: "OK",
            capabilities: ["discover"],
          },
          {
            kind: "snowflake",
            label: "Snowflake",
            status: "production",
            status_note: "OK",
            capabilities: ["discover"],
          },
        ],
      }),
      text: async () => "",
    });

    const ledgerClient = await import("../../lib/ledger-client");
    (ledgerClient.getSources as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      [
        { sourceId: "1", kind: "postgres", uri: "pg://x" },
        { sourceId: "2", kind: "postgres", uri: "pg://y" },
        { sourceId: "3", kind: "snowflake", uri: "sf://z" },
      ],
    );

    const mod = await import("../../lib/connectors");
    const catalog = await mod.getConnectorCatalog(COMPANY_ID);
    const pg = catalog.production.find((c) => c.kind === "postgres");
    const sf = catalog.production.find((c) => c.kind === "snowflake");
    expect(pg?.connectionState).toBe("connected");
    expect(pg?.activeSourceCount).toBe(2);
    expect(sf?.connectionState).toBe("connected");
    expect(sf?.activeSourceCount).toBe(1);
  });
});

describe("getConnectorCatalog (registry unreachable)", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("falls back to the static catalog when fetch throws", async () => {
    fetchMock.mockRejectedValueOnce(new Error("ECONNREFUSED"));
    const mod = await import("../../lib/connectors");
    const catalog = await mod.getConnectorCatalog(COMPANY_ID);
    expect(catalog.registryUnreachable).toBe(true);
    expect(catalog.registryError).toContain("ECONNREFUSED");
    // The static catalog ships >= csv_local + postgres production rows.
    expect(catalog.production.length).toBeGreaterThan(0);
    const kinds = [
      ...catalog.production,
      ...catalog.preview,
      ...catalog.comingSoon,
    ].map((r) => r.kind);
    expect(kinds).toContain("postgres");
  });

  it("flags ``registryUnreachable`` when upstream returns 502", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      text: async () => "bad gateway",
      json: async () => ({}),
    });
    const mod = await import("../../lib/connectors");
    const catalog = await mod.getConnectorCatalog(COMPANY_ID);
    expect(catalog.registryUnreachable).toBe(true);
  });

  it("csv_local renders as always-available even when no active source exists", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        kinds: [
          {
            kind: "csv_local",
            label: "Local CSV",
            status: "production",
            status_note: "OK",
            capabilities: ["discover", "profile", "sample"],
          },
        ],
      }),
      text: async () => "",
    });
    const mod = await import("../../lib/connectors");
    const catalog = await mod.getConnectorCatalog(COMPANY_ID);
    const csv = catalog.production.find((c) => c.kind === "csv_local");
    expect(csv?.connectionState).toBe("available");
  });
});
