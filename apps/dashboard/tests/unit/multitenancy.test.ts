/**
 * Multitenancy unit tests.
 *
 * Three lanes:
 *   1. Tenant slug → company_id derivation matches the upstream UUIDv5.
 *   2. `getTenantFromCookies` reads the cookie + falls back to baseworm.
 *   3. TenantSwitcher renders + calls fetch when a new slug is selected.
 *
 * The cookie-aware tests stub `next/headers` with vi.mock so we can drive
 * the cookie value in isolation. The TenantSwitcher test stubs
 * `next/navigation` and the global fetch.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_TENANT_SLUG,
  WORMBASE_TENANT_NAMESPACE,
  findTenantBySlug,
  getDefaultTenant,
  listKnownTenantsSync,
  tenantToCompanyUuid,
} from "../../lib/tenants";
// uuidv5 lives in the server-only derivation module — node:crypto cannot
// be imported by client components, so it's split out. Tests run in
// vitest (Node) so the import is fine here.
import { uuidv5 } from "../../lib/tenants-derive";

describe("tenantToCompanyUuid (UUIDv5)", () => {
  it("derives the canonical baseworm company_id", () => {
    // Aligned with apps/channel-adapter/.../tenant.py + apps/worm-core/.../service.py.
    expect(tenantToCompanyUuid("baseworm")).toBe(
      "a8989ece-b38a-5811-9625-327a79a65f90",
    );
  });

  it("derives the canonical democorp company_id", () => {
    expect(tenantToCompanyUuid("democorp")).toBe(
      "f9e1af07-371f-538b-bdde-cec81bcb6196",
    );
  });

  it("normalizes whitespace + case", () => {
    expect(tenantToCompanyUuid("  BaseWorm  ")).toBe(
      tenantToCompanyUuid("baseworm"),
    );
  });

  it("rejects empty slugs", () => {
    expect(() => tenantToCompanyUuid("")).toThrow();
    expect(() => tenantToCompanyUuid("   ")).toThrow();
  });

  it("uuidv5 matches the published spec", () => {
    // RFC 4122 example: uuidv5("www.example.com", DNS namespace).
    const DNS_NS = "6ba7b810-9dad-11d1-80b4-00c04fd430c8";
    expect(uuidv5("www.example.com", DNS_NS)).toBe(
      "2ed6657d-e927-568b-95e1-2665a8aea6a2",
    );
  });

  it("uses the wormbase namespace constant", () => {
    expect(WORMBASE_TENANT_NAMESPACE).toBe(
      "6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f",
    );
  });
});

describe("listKnownTenantsSync", () => {
  it("includes baseworm and democorp", () => {
    const slugs = listKnownTenantsSync().map((t) => t.slug);
    expect(slugs).toContain("baseworm");
    expect(slugs).toContain("democorp");
  });

  it("each tenant carries a UUID company_id", () => {
    for (const t of listKnownTenantsSync()) {
      expect(t.companyId).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
      );
    }
  });
});

describe("findTenantBySlug + getDefaultTenant", () => {
  it("returns the default for a missing slug", () => {
    expect(findTenantBySlug(null)).toBeNull();
    expect(findTenantBySlug("")).toBeNull();
  });

  it("looks up known slugs case-insensitively", () => {
    expect(findTenantBySlug("BASEWORM")?.slug).toBe("baseworm");
    expect(findTenantBySlug("democorp")?.slug).toBe("democorp");
  });

  it("returns null for an unknown slug", () => {
    expect(findTenantBySlug("ghost-tenant")).toBeNull();
  });

  it("default tenant is baseworm", () => {
    expect(getDefaultTenant().slug).toBe(DEFAULT_TENANT_SLUG);
    expect(getDefaultTenant().slug).toBe("baseworm");
  });
});

// ─── tenant-cookies (server-side) ─────────────────────────────────────────
//
// We mock `next/headers` so the suite can run in vitest without a Next
// request scope. Each test sets the desired cookie value and reimports the
// module so the mock is picked up.

describe("getTenantFromCookies", () => {
  let cookieValue: string | null = null;

  beforeEach(() => {
    vi.resetModules();
    cookieValue = null;
    vi.doMock("next/headers", () => ({
      cookies: async () => ({
        get: (name: string) =>
          name === "wormbase-tenant-slug" && cookieValue
            ? { name, value: cookieValue }
            : undefined,
        set: vi.fn(),
      }),
    }));
  });

  afterEach(() => {
    vi.doUnmock("next/headers");
  });

  it("returns baseworm when no cookie is set", async () => {
    cookieValue = null;
    const { getTenantFromCookies } = await import("../../lib/tenant-cookies");
    const t = await getTenantFromCookies();
    expect(t.slug).toBe("baseworm");
    expect(t.companyId).toBe("a8989ece-b38a-5811-9625-327a79a65f90");
  });

  it("returns democorp when the cookie names it", async () => {
    cookieValue = "democorp";
    const { getTenantFromCookies } = await import("../../lib/tenant-cookies");
    const t = await getTenantFromCookies();
    expect(t.slug).toBe("democorp");
    expect(t.companyId).toBe("f9e1af07-371f-538b-bdde-cec81bcb6196");
  });

  it("falls back to baseworm for an unknown slug", async () => {
    cookieValue = "ghost-tenant";
    const { getTenantFromCookies } = await import("../../lib/tenant-cookies");
    const t = await getTenantFromCookies();
    expect(t.slug).toBe("baseworm");
  });

  it("getCurrentCompanyId returns the resolved UUID", async () => {
    cookieValue = "democorp";
    const { getCurrentCompanyId } = await import("../../lib/tenant-cookies");
    expect(await getCurrentCompanyId()).toBe(
      "f9e1af07-371f-538b-bdde-cec81bcb6196",
    );
  });
});

// ─── TenantSwitcher (client) ──────────────────────────────────────────────

describe("TenantSwitcher", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let refreshMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    vi.resetModules();
    refreshMock = vi.fn();
    fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true })));
    (globalThis as unknown as { fetch: typeof fetch }).fetch =
      fetchMock as unknown as typeof fetch;

    vi.doMock("next/navigation", () => ({
      useRouter: () => ({ refresh: refreshMock, push: vi.fn() }),
    }));
    // Reset the DOM between tests; happy-dom retains nodes otherwise.
    if (typeof document !== "undefined") {
      document.body.innerHTML = "";
    }
  });

  afterEach(async () => {
    const rtl = await import("@testing-library/react");
    rtl.cleanup();
    vi.doUnmock("next/navigation");
  });

  it("renders the current tenant + the full tenant list", async () => {
    const { render, screen } = await import("@testing-library/react");
    const React = await import("react");
    const { TenantProvider } = await import("../../lib/tenant-context");
    const { TenantSwitcher } = await import(
      "../../components/chrome/TenantSwitcher"
    );

    render(
      React.createElement(TenantProvider, {
        initialSlug: "baseworm",
        children: React.createElement(TenantSwitcher),
      }),
    );

    const select = screen.getByTestId("tenant-switcher-select") as HTMLSelectElement;
    expect(select.value).toBe("baseworm");
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toContain("baseworm");
    expect(optionValues).toContain("democorp");
  });

  it("posts to /api/tenant + refreshes the router on change", async () => {
    const { render, screen, fireEvent } = await import(
      "@testing-library/react"
    );
    const React = await import("react");
    const { TenantProvider } = await import("../../lib/tenant-context");
    const { TenantSwitcher } = await import(
      "../../components/chrome/TenantSwitcher"
    );

    render(
      React.createElement(TenantProvider, {
        initialSlug: "baseworm",
        children: React.createElement(TenantSwitcher),
      }),
    );

    const select = screen.getByTestId(
      "tenant-switcher-select",
    ) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "democorp" } });

    // Wait one microtask cycle for the async setCurrentTenant + fetch chain.
    await new Promise((r) => setTimeout(r, 0));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/tenant");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ slug: "democorp" });
    expect(refreshMock).toHaveBeenCalled();
  });
});
