/**
 * MemberAccessBanner — D8 of the production-dashboard plan.
 *
 * Server-rendered notice shown on tabs where role-aware filtering is
 * applied. For members with no domain grants the page surface is empty;
 * this banner explains why and tells them who to ask.
 *
 * Editorial language: sepia warning chrome, square corners, wb-mono.
 */
export interface MemberAccessBannerProps {
  /** True when the current Person is a member with no domain grants. */
  show: boolean;
  /** What surface they're looking at (kpis, sources, etc.). */
  surface?: string;
}

export function MemberAccessBanner({ show, surface }: MemberAccessBannerProps) {
  if (!show) return null;
  return (
    <aside
      data-testid="member-access-banner"
      style={{
        border: "1px solid var(--wb-color-sepia-warning)",
        background: "var(--wb-color-sepia-warning-soft)",
        padding: "10px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-sepia-warning-deep)",
        }}
      >
        no access · member view
      </span>
      <span
        style={{
          fontFamily: "var(--wb-font-serif)",
          fontSize: 13,
          color: "var(--wb-color-aged-ink)",
        }}
      >
        You don't have a domain grant for {surface ?? "this surface"}. Ask
        your tenant admin to grant{" "}
        <span className="wb-mono">domain.contributor</span> on the relevant
        domain.
      </span>
    </aside>
  );
}
