"use client";
/**
 * Tenant switcher dropdown — lives in the TopRule.
 *
 * Lists every known tenant; selecting one POSTs to `/api/tenant`, which sets
 * the `wormbase-tenant-slug` cookie, then triggers a router refresh so the
 * RSC tree re-reads with the new company_id.
 */

import { useCurrentTenant } from "../../lib/tenant-context";

export function TenantSwitcher() {
  const { currentTenant, knownTenants, setCurrentTenant, isPending } =
    useCurrentTenant();

  return (
    <label
      data-testid="tenant-switcher"
      style={{
        display: "inline-flex",
        alignItems: "baseline",
        gap: 6,
        fontFamily: "var(--wb-font-mono, monospace)",
        fontSize: 10,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        color: "var(--wb-color-hash-gray)",
      }}
    >
      <span aria-hidden>tenant /</span>
      <select
        data-testid="tenant-switcher-select"
        aria-label="Switch tenant"
        value={currentTenant.slug}
        onChange={(e) => {
          const slug = e.target.value;
          if (slug !== currentTenant.slug) {
            void setCurrentTenant(slug);
          }
        }}
        disabled={isPending}
        style={{
          fontFamily: "inherit",
          fontSize: "inherit",
          letterSpacing: "inherit",
          textTransform: "inherit",
          color: "var(--wb-color-aged-ink)",
          background: "transparent",
          border: "1px solid var(--wb-color-paper-edge, #d6cfbf)",
          padding: "2px 4px",
          cursor: isPending ? "wait" : "pointer",
        }}
      >
        {knownTenants.map((t) => (
          <option key={t.slug} value={t.slug}>
            {t.displayName.toLowerCase()}
          </option>
        ))}
      </select>
      <span style={{ color: "var(--wb-color-hash-gray)" }}>
        · {currentTenant.companyId.slice(0, 8)}…
      </span>
    </label>
  );
}
