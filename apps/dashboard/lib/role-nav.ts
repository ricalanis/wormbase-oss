/**
 * Role-aware navigation chrome.
 *
 * D2 of docs/superpowers/plans/2026-04-26-production-dashboard.md, mapping
 * to PRD §7.10 + §7.1 (role × tab utility matrix).
 *
 * Surface contract:
 *   - installer  → /onboarding pinned first, then full nav
 *   - admin      → full nav, every item actionable
 *   - member     → narrow read-leaning nav (8 tabs)
 *   - observer   → full nav, every item flagged readOnly
 *
 * Pure function; no side effects. Both the server-rendered Sidebar and the
 * unit test consume `navItemsForRole` directly.
 */

export type NavRole = "installer" | "admin" | "member" | "observer";

export interface NavItem {
  href: string;
  label: string;
  /** When true the rendering chrome should mute the item and suppress
   *  any inline action chip — observer mode renders every tab read-only. */
  readOnly?: boolean;
}

/** Canonical full nav (admin lens). PRD §7.1 + §16.6 — 23 daily/weekly tabs.
 *  WS5 S3 added /topics (silver-conversations cluster view); Block J6
 *  added /mcp (server catalog + per-call audit); W2.A10 added /ops
 *  (observability — Postgres health, throughput, rate limits, agent loops);
 *  W5.A5 added /reactivities (the worm's registered reactivity rules +
 *  fire history + budget telemetry — admin-only operational surface);
 *  post-rest #3 (2026-05-13) added /governance/tenant-quota (admin-only
 *  audit of ``tenant_quota_consumed`` ledger entries — SOC-2 surface);
 *  L3 Sub-wave D (2026-05-29) added /lake/lineage (admin-only L3
 *  inference-axis audit — confirm/reject proposed edges) +
 *  /lake/connectors (read-only marketplace shell with per-tenant
 *  connection state); Onboarding Sub-wave B (2026-05-30) added
 *  /onboard (unified onboarding surface covering every institutional
 *  object kind — chat / source / domain / person / policy / agent /
 *  subscription — with @status + @logs deep-links per row);
 *  L7 Sub-wave D (2026-05-30) added /lake/quality (admin-only L7
 *  quality-checks audit — confirm/reject proposed checks with the 5-
 *  value enum + group-by toggle); L4 Sub-wave D (2026-06-02) added
 *  /lake/schema-impact (admin-only L4 schema-evolution-impact audit —
 *  first lake-side axis to consume another axis's output, first
 *  cross-axis trace navigation in the dashboard via "view L3 edge"
 *  links from impact rows); L5 Sub-wave D (2026-06-05) added
 *  /lake/semantic-types (admin-only L5 sample-data fingerprinting
 *  audit — strict 19-value semantic_type enum + L5-specific 5-value
 *  reject reason enum with ``wrong_type``); L6 Sub-wave D (2026-06-06)
 *  added /lake/column-classification (admin-only L6 column-level
 *  governance classification audit — 5-value ClassificationLevel enum
 *  with regulated visual distinction (red + lock glyph) +
 *  L6-specific 5-value reject reason enum with ``wrong_level`` +
 *  SECOND cross-axis trace navigation in the lake stack via
 *  "view L5 semantic type →" links); L8 Sub-wave D (2026-06-07)
 *  added /lake/entity-stitches (admin-only L8 cross-source entity-
 *  stitch audit — 8-value EntityKind enum with muted "other" tier +
 *  L8-specific 5-value reject reason enum with ``wrong_pairing`` +
 *  THIRD cross-axis trace navigation in the lake stack via
 *  "view L5 semantic type →" links, reusing L6's
 *  ConfirmedSemanticTypeReader Protocol); L1 Sub-wave D (2026-06-08)
 *  added /lake/source-candidates (admin-only L1 source-candidate
 *  triage audit — 12-value connector-registry kind chip with muted
 *  "unknown" + ``mcp:*`` tier + L1-specific 5-value reject reason
 *  enum with ``duplicate`` + sui-generis "→ source pipeline"
 *  downstream link on promoted rows; does NOT add a peer-L-axis
 *  cross-axis chain — strategies read lightweight platform
 *  projections, not other axes' confirmed outputs; cross-axis chain
 *  count stays at 3); L2 Sub-wave D (2026-06-09) added
 *  /lake/catalog-drift (admin-only L2 catalog-drift triage audit —
 *  strict 5-value DriftKind enum with multi-color chip palette
 *  (table_added green / table_removed red / column_added emerald /
 *  column_removed rose / column_type_changed amber) + L2-specific
 *  5-value reject reason enum with ``expected_change`` +
 *  before→after delta rendering; L2 uses ``acknowledged`` for the
 *  affirmative state (sui generis — distinct from L1's ``promoted``
 *  and L3-L8's ``confirmed``) reflecting read-only-disposition
 *  semantics; does NOT add a peer-L-axis cross-axis chain — its
 *  CatalogSnapshotReader Protocol reads catalog-mirror substrate,
 *  NOT another L-axis's confirmed projection; cross-axis chain
 *  count stays at 3. L2 is the 8th and FINAL planned lake-side
 *  axis in this wave generation; L-axis family closes at 24 of 30
 *  cap). Lake-Side Overview (2026-05-16) added /lake/overview as
 *  the natural landing surface across the 8-axis stack — admin-only
 *  landing page with axis state grid + 7-chain panel + recent-
 *  activity stream; placed FIRST in the lake section above
 *  /lake/lineage so the overview is the canonical entry point.
 *  Admin nav 30 → 31. */
const ALL_NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/onboard", label: "Onboard" },
  { href: "/sources", label: "Sources" },
  { href: "/kpis", label: "KPIs" },
  { href: "/data-products", label: "Data products" },
  { href: "/notebooks", label: "Notebooks" },
  { href: "/topics", label: "Topics" },
  { href: "/decisions", label: "Decisions" },
  { href: "/processes", label: "Processes" },
  { href: "/system-map", label: "System map" },
  { href: "/research", label: "Research" },
  { href: "/activity", label: "Activity" },
  { href: "/trace", label: "Trace" },
  { href: "/people", label: "People" },
  { href: "/domains", label: "Domains" },
  { href: "/policies", label: "Policies" },
  { href: "/channels", label: "Channels" },
  { href: "/lake/connectors", label: "Connectors" },
  { href: "/lake/overview", label: "Lake overview" },
  { href: "/lake/lineage", label: "Lineage" },
  { href: "/lake/quality", label: "Quality" },
  { href: "/lake/schema-impact", label: "Schema impact" },
  { href: "/lake/semantic-types", label: "Semantic types" },
  { href: "/lake/column-classification", label: "Column classification" },
  { href: "/lake/entity-stitches", label: "Entity stitches" },
  { href: "/lake/source-candidates", label: "Source candidates" },
  { href: "/lake/catalog-drift", label: "Catalog drift" },
  { href: "/mcp", label: "MCP" },
  { href: "/ops", label: "Ops" },
  { href: "/reactivities", label: "Reactivities" },
  { href: "/governance/tenant-quota", label: "Tenant quota" },
];

/** Tabs that are admin-or-observer only. /mcp shows other tenants'
 *  inbound calls, /ops shows cross-tenant rate-limit headroom,
 *  /reactivities lets admins propose / confirm / disable the worm's
 *  reactivity rules, /governance/tenant-quota surfaces per-tenant
 *  MCP-request quota consumption, /lake/lineage is the L3 inference-
 *  axis audit (confirm/reject proposed edges — admin write actions),
 *  /lake/quality is the L7 quality-checks audit (confirm/reject
 *  proposed checks — admin write actions), /lake/schema-impact is the
 *  L4 schema-evolution-impact audit (confirm/reject proposed impacts
 *  — admin write actions; first cross-axis trace navigation in the
 *  lake stack), /lake/semantic-types is the L5 sample-data
 *  fingerprinting audit (confirm/reject proposed semantic types from
 *  the strict 19-value enum — admin write actions), /lake/connectors
 *  is the marketplace shell with per-tenant connection state, and
 *  /onboard is the unified onboarding surface (chat / source / domain
 *  / person / policy / agent / subscription) — admins extend the
 *  tenant, observers audit, members don't see it. All privacy-bounded
 *  to admins + observers. Members must not see any of these. The
 *  installer onboarding lens shows /onboard (it's how they extend the
 *  tenant they just installed) but hides the rest — they're
 *  irrelevant before a tenant is fully provisioned. */
const ADMIN_OR_OBSERVER_ONLY_HREFS = new Set([
  "/mcp",
  "/ops",
  "/reactivities",
  "/governance/tenant-quota",
  "/lake/overview",
  "/lake/lineage",
  "/lake/quality",
  "/lake/schema-impact",
  "/lake/semantic-types",
  "/lake/column-classification",
  "/lake/entity-stitches",
  "/lake/source-candidates",
  "/lake/catalog-drift",
  "/lake/connectors",
  "/onboard",
]);

/** Member-visible subset — 11 read-leaning tabs (no people/domains/policies/
 *  channels/trace). Mirrors PRD §7.10 "member" lens; data-products + notebooks
 *  added per §16.6; topics added per WS5 S3. */
const MEMBER_HREFS = new Set([
  "/dashboard",
  "/sources",
  "/kpis",
  "/data-products",
  "/notebooks",
  "/topics",
  "/decisions",
  "/processes",
  "/system-map",
  "/research",
  "/activity",
]);

/**
 * Resolve the nav items for a tenancy role. Returns a fresh array so the
 * caller can sort/filter without mutating module-level state.
 */
export function navItemsForRole(role: NavRole): NavItem[] {
  switch (role) {
    case "installer": {
      // Installer onboards into a fresh tenant. /mcp + /ops + /reactivities
      // + /governance/tenant-quota + /lake/lineage + /lake/connectors are
      // hidden until the installer is promoted (or self-promotes) to admin —
      // privacy: the audit log surfaces other tenants' calls in /mcp, and
      // the installer's role is defined by the tenant they just created,
      // not by general admin scope.
      //
      // /onboard IS surfaced — it's the unified surface the installer uses
      // to extend their fresh tenant (chat / source / domain / person /
      // policy / agent / subscription). Without it, the installer can't
      // reach the agentic-source-building flows their tenant needs.
      const onboarding: NavItem = { href: "/onboarding", label: "Onboarding" };
      const tail = ALL_NAV.filter(
        (i) => i.href === "/onboard" || !ADMIN_OR_OBSERVER_ONLY_HREFS.has(i.href),
      ).map((i) => ({ ...i }));
      return [onboarding, ...tail];
    }
    case "admin":
      return ALL_NAV.map((i) => ({ ...i }));
    case "member":
      return ALL_NAV.filter((i) => MEMBER_HREFS.has(i.href)).map((i) => ({ ...i }));
    case "observer":
      return ALL_NAV.map((i) => ({ ...i, readOnly: true }));
  }
}
