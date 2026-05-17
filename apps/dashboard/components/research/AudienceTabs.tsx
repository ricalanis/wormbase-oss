"use client";
/**
 * AudienceTabs — Mine / Team / Company tab strip for /research (W5.A5).
 *
 * Reads `?audience=` from the URL; defaults to "mine". Clicking a tab
 * replaces the URL with the new audience while preserving any other
 * query params (e.g. ?personId=). The /research server page reads the
 * resolved audience and passes it down to the experiments query so the
 * filtered slice renders.
 *
 * Three tabs map 1:1 to the W5.A4 audience scopes:
 *   - "Mine"     → person:<currentPersonId>  (default; per-Person)
 *   - "Team"     → team:<*>                  (any team-scoped experiment)
 *   - "Company"  → company                   (org-wide arbitration winners)
 *
 * Editorial chrome: small uppercase wb-mono labels, sepia rule under
 * the active tab. No icons, no animations.
 */

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import type { ResearchAudience } from "../../lib/ledger-client.types";

const TABS: ReadonlyArray<{ key: ResearchAudience; label: string }> = [
  { key: "mine", label: "Mine" },
  { key: "team", label: "Team" },
  { key: "company", label: "Company" },
];

export interface AudienceTabsProps {
  /** Override the resolved audience (defaults to ?audience= → "mine"). */
  current?: ResearchAudience;
}

export function AudienceTabs({ current }: AudienceTabsProps) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const raw = params.get("audience") ?? "mine";
  const resolved: ResearchAudience =
    current ?? ((["mine", "team", "company"] as const).includes(
      raw as ResearchAudience,
    )
      ? (raw as ResearchAudience)
      : "mine");

  const select = useCallback(
    (audience: ResearchAudience) => {
      const next = new URLSearchParams(params.toString());
      if (audience === "mine") next.delete("audience");
      else next.set("audience", audience);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname);
    },
    [params, pathname, router],
  );

  return (
    <nav
      data-testid="research-audience-tabs"
      aria-label="Research audience scope"
      style={{
        display: "flex",
        gap: 0,
        borderBottom: "1px solid var(--wb-color-rule-line)",
      }}
    >
      {TABS.map((tab) => {
        const isActive = resolved === tab.key;
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            data-testid={`audience-tab-${tab.key}`}
            data-active={isActive ? "true" : "false"}
            onClick={() => select(tab.key)}
            style={{
              padding: "10px 18px",
              border: "none",
              borderBottom: isActive
                ? "2px solid var(--wb-color-botanical-green-deep)"
                : "2px solid transparent",
              background: "transparent",
              fontFamily: "var(--wb-font-mono)",
              fontSize: 11,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: isActive
                ? "var(--wb-color-aged-ink)"
                : "var(--wb-color-hash-gray)",
              cursor: "pointer",
              marginBottom: -1,
            }}
          >
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
}
