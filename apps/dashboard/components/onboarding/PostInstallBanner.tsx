/**
 * Post-install banner CTA — Block I5.
 *
 * After Block I, the wizard-vs-bot fork is no longer a forced redirect.
 * Fresh tenants land on the dashboard immediately; this banner surfaces
 * the "Want a tour?" affordance (or, when partially set up, "Continue
 * setup" / "Setup in progress in your chat") without blocking the dashboard.
 *
 * Renders nothing when setup_completed is non-null (the install is fully
 * set up; no banner required).
 */
import Link from "next/link";

export interface PostInstallBannerProps {
  setupMode: "wizard" | "bot" | null;
  setupCompletedAt: string | null;
}

export function PostInstallBanner({
  setupMode,
  setupCompletedAt,
}: PostInstallBannerProps) {
  if (setupCompletedAt !== null) {
    // Setup complete — banner retires.
    return null;
  }

  if (setupMode === "wizard") {
    return (
      <aside
        data-testid="post-install-banner"
        data-banner-state="wizard-pending"
        className="wb-mono"
        style={bannerStyle}
      >
        <div style={bannerCopyStyle}>
          <span style={eyebrowStyle}>continue setup</span>
          <p style={bodyStyle}>
            You picked the dashboard wizard. Pick up where you left off — the
            worm has been lurking in the meantime.
          </p>
        </div>
        <Link
          href="/onboarding/tier2"
          data-testid="post-install-banner-cta-wizard"
          style={ctaStyle}
        >
          continue wizard →
        </Link>
      </aside>
    );
  }

  if (setupMode === "bot") {
    return (
      <aside
        data-testid="post-install-banner"
        data-banner-state="bot-pending"
        className="wb-mono"
        style={{
          ...bannerStyle,
          background: "var(--wb-color-botanical-green-soft)",
        }}
      >
        <div style={bannerCopyStyle}>
          <span style={eyebrowStyle}>setup in progress · chat</span>
          <p style={bodyStyle}>
            Reply to the worm's DM to continue setup. The dashboard stays
            consultable while the conversation runs.
          </p>
        </div>
      </aside>
    );
  }

  // setupMode === null + setupCompletedAt === null — fresh tenant, no fork
  // chosen. Offer both surfaces.
  return (
    <aside
      data-testid="post-install-banner"
      data-banner-state="want-a-tour"
      className="wb-mono"
      style={bannerStyle}
    >
      <div style={bannerCopyStyle}>
        <span style={eyebrowStyle}>want a tour?</span>
        <p style={bodyStyle}>
          The default lake is yours from minute zero. Want a guided tour, or
          would you rather chat with the worm?
        </p>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Link
          href="/onboarding/whats-next"
          data-testid="post-install-banner-cta-tour"
          style={ctaStyle}
        >
          take the tour →
        </Link>
        <Link
          href="/onboarding/setup-mode/choose"
          data-testid="post-install-banner-cta-chat"
          style={{
            ...ctaStyle,
            background: "var(--wb-color-paper-deep)",
            color: "var(--wb-color-aged-ink)",
          }}
        >
          chat with the worm →
        </Link>
      </div>
    </aside>
  );
}

const bannerStyle = {
  display: "flex",
  flexDirection: "column" as const,
  gap: 12,
  padding: 18,
  border: "1px solid var(--wb-color-paper-edge)",
  background: "var(--wb-color-paper-deep)",
};

const bannerCopyStyle = {
  display: "flex",
  flexDirection: "column" as const,
  gap: 4,
};

const eyebrowStyle = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase" as const,
  color: "var(--wb-color-hash-gray)",
};

const bodyStyle = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontStyle: "italic" as const,
  fontSize: 13,
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.55,
  maxWidth: 640,
};

const ctaStyle = {
  display: "inline-block",
  fontSize: 12,
  letterSpacing: "0.08em",
  textTransform: "uppercase" as const,
  padding: "8px 14px",
  border: "1px solid var(--wb-color-aged-ink)",
  background: "var(--wb-color-botanical-green-soft)",
  color: "var(--wb-color-aged-ink)",
  textDecoration: "none",
  alignSelf: "flex-start" as const,
};
