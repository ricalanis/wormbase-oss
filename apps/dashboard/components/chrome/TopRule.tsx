/**
 * TopRule — the tenant + projection-snapshot strip across the top of every
 * dashboard surface. 1px ink rule beneath, mono content, no decoration.
 *
 * The tenant control on the left is a real switcher — selecting another
 * tenant rewrites the `wormbase-tenant-slug` cookie and refreshes the route
 * so RSCs re-read with the new company_id. The PersonChip on the right
 * shows the resolved current Person for the active tenant (D1).
 */

import { PersonChip, type PersonChipProps } from "./PersonChip";
import { ShareViewButton } from "./ShareViewButton";
import { TenantSwitcher } from "./TenantSwitcher";

export interface TopRuleProps {
  snapshotHash?: string;
  /** Current Person for the active tenant. Optional — when omitted the
   *  right slot collapses to just the snapshot label (back-compat for tests
   *  that render TopRule directly). */
  person?: PersonChipProps;
  /** Show the share-view button (D8). Defaults to true for the production
   *  layout; tests can opt out by passing false. */
  showShareView?: boolean;
}

export function TopRule({
  snapshotHash,
  person,
  showShareView = true,
}: TopRuleProps) {
  return (
    <div
      data-testid="top-rule"
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        gap: 16,
        padding: "10px 32px",
        borderBottom: "1px solid var(--wb-color-aged-ink)",
        background: "var(--wb-color-paper)",
      }}
    >
      <TenantSwitcher />
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 16,
        }}
      >
        {showShareView ? <ShareViewButton /> : null}
        {person ? <PersonChip {...person} /> : null}
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.06em",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          snapshot · {snapshotHash ?? "live"}
        </span>
      </div>
    </div>
  );
}
