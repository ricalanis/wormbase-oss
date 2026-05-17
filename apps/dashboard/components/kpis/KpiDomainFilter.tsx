"use client";
/**
 * KpiDomainFilter — populated-state filter for /kpis (W2.A7).
 *
 * KpiNodeRow carries ``classification`` (the lens governance uses to
 * partition the KPI tree). The filter scopes the visible tree by
 * classification, which is the read-side of "by domain" given that
 * domain assignment is currently expressed through classification on
 * the KPI tree projection. The filter is purely presentational — the
 * underlying KPI tree is unchanged.
 *
 * Filter state is held in URL query (`?lens=...`) so a deep-linked
 * filtered tree round-trips through reload.
 */
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useMemo } from "react";

const LENS_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "all", label: "All classifications" },
  { value: "public", label: "public" },
  { value: "internal", label: "internal" },
  { value: "confidential", label: "confidential" },
  { value: "pii", label: "pii" },
  { value: "regulated", label: "regulated" },
];

export function KpiDomainFilter() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const current = params.get("lens") ?? "all";

  const target = useMemo(() => {
    return (next: string) => {
      const usp = new URLSearchParams(params.toString());
      if (next === "all") {
        usp.delete("lens");
      } else {
        usp.set("lens", next);
      }
      const qs = usp.toString();
      return qs ? `${pathname}?${qs}` : pathname;
    };
  }, [params, pathname]);

  return (
    <label
      data-testid="kpi-domain-filter"
      className="wb-mono"
      style={{
        fontSize: 11,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: "var(--wb-color-hash-gray)",
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      Filter by domain:&nbsp;
      <select
        data-testid="kpi-domain-filter-select"
        value={current}
        onChange={(e) => router.push(target(e.currentTarget.value))}
        style={{
          fontFamily: "var(--wb-font-mono)",
          fontSize: 12,
          padding: "4px 8px",
          borderRadius: 0,
          border: "1px solid var(--wb-color-aged-ink)",
          background: "var(--wb-color-paper)",
        }}
      >
        {LENS_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
