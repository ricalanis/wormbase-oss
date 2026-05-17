/**
 * D2 — role-aware nav.
 */
import { describe, it, expect } from "vitest";
import { navItemsForRole } from "../../lib/role-nav";

describe("navItemsForRole", () => {
  it("installer sees onboarding pinned first + /onboard (extends fresh tenant)", () => {
    const items = navItemsForRole("installer");
    expect(items[0]?.href).toBe("/onboarding");
    // followed by the admin nav (sans /mcp + /ops + /reactivities +
    // /governance/tenant-quota + /lake/lineage + /lake/quality +
    // /lake/schema-impact + /lake/semantic-types +
    // /lake/column-classification + /lake/entity-stitches +
    // /lake/source-candidates + /lake/catalog-drift +
    // /lake/surfaces — installer privacy / pre-provision
    // irrelevance). /onboard IS visible because the installer uses
    // it to extend the tenant they just installed (chat / source /
    // domain / person / policy / agent / subscription).
    const hrefs = items.map((i) => i.href);
    expect(hrefs).toContain("/people");
    expect(hrefs).toContain("/channels");
    expect(hrefs).toContain("/onboard");
    expect(hrefs).not.toContain("/mcp");
    expect(hrefs).not.toContain("/ops");
    expect(hrefs).not.toContain("/reactivities");
    expect(hrefs).not.toContain("/governance/tenant-quota");
    expect(hrefs).not.toContain("/lake/overview");
    expect(hrefs).not.toContain("/lake/lineage");
    expect(hrefs).not.toContain("/lake/quality");
    expect(hrefs).not.toContain("/lake/schema-impact");
    expect(hrefs).not.toContain("/lake/semantic-types");
    expect(hrefs).not.toContain("/lake/column-classification");
    expect(hrefs).not.toContain("/lake/entity-stitches");
    expect(hrefs).not.toContain("/lake/source-candidates");
    expect(hrefs).not.toContain("/lake/catalog-drift");
    expect(hrefs).not.toContain("/lake/surfaces");
  });

  it("admin sees full nav (all 31 tabs, no onboarding)", () => {
    // 30 tabs = 13 base + data-products + notebooks (Block F § 16.6) +
    // topics (WS5 S3) + mcp (Block J6) + ops (W2.A10) +
    // reactivities (W5.A5) + governance/tenant-quota (post-rest #3,
    // 2026-05-13) + /lake/lineage + /lake/surfaces (L3 Sub-wave D,
    // 2026-05-29) + /onboard (Onboarding Sub-wave B, 2026-05-30) +
    // /lake/quality (L7 Sub-wave D, 2026-05-30) +
    // /lake/schema-impact (L4 Sub-wave D, 2026-06-02) +
    // /lake/semantic-types (L5 Sub-wave D, 2026-06-05) +
    // /lake/column-classification (L6 Sub-wave D, 2026-06-06) +
    // /lake/entity-stitches (L8 Sub-wave D, 2026-06-07) +
    // /lake/source-candidates (L1 Sub-wave D, 2026-06-08) +
    // /lake/catalog-drift (L2 Sub-wave D, 2026-06-09 — 8th and FINAL
    // lake-side axis in this wave generation; L-axis family closes
    // here at 24 of 30 cap). Lake-Side Overview (2026-05-16) added
    // /lake/overview as natural landing surface across the 8-axis
    // stack — admin nav 30 → 31.
    const items = navItemsForRole("admin");
    expect(items).toHaveLength(31);
    const hrefs = items.map((i) => i.href);
    expect(hrefs).toContain("/people");
    expect(hrefs).toContain("/domains");
    expect(hrefs).toContain("/policies");
    expect(hrefs).toContain("/channels");
    expect(hrefs).toContain("/data-products");
    expect(hrefs).toContain("/notebooks");
    expect(hrefs).toContain("/topics");
    expect(hrefs).toContain("/mcp");
    expect(hrefs).toContain("/ops");
    expect(hrefs).toContain("/reactivities");
    expect(hrefs).toContain("/governance/tenant-quota");
    expect(hrefs).toContain("/lake/overview");
    expect(hrefs).toContain("/lake/lineage");
    expect(hrefs).toContain("/lake/quality");
    expect(hrefs).toContain("/lake/schema-impact");
    expect(hrefs).toContain("/lake/semantic-types");
    expect(hrefs).toContain("/lake/column-classification");
    expect(hrefs).toContain("/lake/entity-stitches");
    expect(hrefs).toContain("/lake/source-candidates");
    expect(hrefs).toContain("/lake/catalog-drift");
    expect(hrefs).toContain("/lake/surfaces");
    expect(hrefs).toContain("/onboard");
    expect(hrefs).not.toContain("/onboarding");
    // none flagged readOnly
    expect(items.every((i) => !i.readOnly)).toBe(true);
  });

  it("member nav is the 11-tab read-leaning subset (no /mcp + no /ops + no /reactivities + no /governance/tenant-quota + no /lake/* admin tabs + no /onboard)", () => {
    // 11 tabs = original 8 + data-products + notebooks (Block F § 16.6) +
    // topics (WS5 S3). /mcp + /ops + /reactivities +
    // /governance/tenant-quota + /lake/lineage + /lake/quality +
    // /lake/schema-impact + /lake/semantic-types +
    // /lake/column-classification + /lake/entity-stitches +
    // /lake/source-candidates + /lake/catalog-drift +
    // /lake/surfaces + /onboard stay admin/observer-only.
    const items = navItemsForRole("member");
    expect(items).toHaveLength(11);
    const hrefs = items.map((i) => i.href);
    expect(hrefs).toContain("/dashboard");
    expect(hrefs).toContain("/research");
    expect(hrefs).toContain("/data-products");
    expect(hrefs).toContain("/notebooks");
    expect(hrefs).toContain("/topics");
    expect(hrefs).not.toContain("/policies");
    expect(hrefs).not.toContain("/people");
    expect(hrefs).not.toContain("/channels");
    expect(hrefs).not.toContain("/trace");
    expect(hrefs).not.toContain("/mcp");
    expect(hrefs).not.toContain("/ops");
    expect(hrefs).not.toContain("/reactivities");
    expect(hrefs).not.toContain("/governance/tenant-quota");
    expect(hrefs).not.toContain("/lake/overview");
    expect(hrefs).not.toContain("/lake/lineage");
    expect(hrefs).not.toContain("/lake/quality");
    expect(hrefs).not.toContain("/lake/schema-impact");
    expect(hrefs).not.toContain("/lake/semantic-types");
    expect(hrefs).not.toContain("/lake/column-classification");
    expect(hrefs).not.toContain("/lake/entity-stitches");
    expect(hrefs).not.toContain("/lake/source-candidates");
    expect(hrefs).not.toContain("/lake/catalog-drift");
    expect(hrefs).not.toContain("/lake/surfaces");
    expect(hrefs).not.toContain("/onboard");
  });

  it("observer sees the full nav but every item is readOnly", () => {
    const items = navItemsForRole("observer");
    expect(items).toHaveLength(31);
    expect(items.every((i) => i.readOnly === true)).toBe(true);
    const hrefs = items.map((i) => i.href);
    expect(hrefs).toContain("/mcp");
    expect(hrefs).toContain("/ops");
    expect(hrefs).toContain("/reactivities");
    expect(hrefs).toContain("/governance/tenant-quota");
    expect(hrefs).toContain("/lake/overview");
    expect(hrefs).toContain("/lake/lineage");
    expect(hrefs).toContain("/lake/quality");
    expect(hrefs).toContain("/lake/schema-impact");
    expect(hrefs).toContain("/lake/semantic-types");
    expect(hrefs).toContain("/lake/column-classification");
    expect(hrefs).toContain("/lake/entity-stitches");
    expect(hrefs).toContain("/lake/source-candidates");
    expect(hrefs).toContain("/lake/catalog-drift");
    expect(hrefs).toContain("/lake/surfaces");
    expect(hrefs).toContain("/onboard");
  });

  it("returns fresh arrays so callers can mutate without cross-contamination", () => {
    const a = navItemsForRole("admin");
    const b = navItemsForRole("admin");
    a[0].label = "MUTATED";
    expect(b[0].label).not.toBe("MUTATED");
  });
});
