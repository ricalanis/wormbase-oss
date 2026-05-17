"use client";

/**
 * ChannelPlatforms — landing-page channel-platform tiles.
 *
 * Data-driven from `lib/platform-status.ts` PLATFORMS so capability honesty
 * stays consistent across the dashboard. Each tile renders a platform's
 * label, status badge (production / preview / coming_soon), capability
 * chips, and surfaces the canonical `statusNote` via tooltip + a click-to-
 * open modal for the longer prose.
 *
 * Wave H · W2-A surfacing — added to give the post-C-wave WhatsApp
 * descriptor a public-facing landing surface alongside Slack / Discord /
 * Teams / Signal. The tile rendering is generic so any future cascade
 * (Signal preview, new platforms) lands automatically without touching
 * this file.
 *
 * Field Notebook treatment matches the rest of the landing: rectangular
 * tiles, serif labels, mono kickers, sepia-toned preview chip, muted
 * coming_soon. No color outside the canonical token surface.
 */
import { useId, useState, type CSSProperties } from "react";

import {
  PLATFORMS,
  type PlatformDescriptor,
  type PlatformStatus,
} from "../../lib/platform-status";

interface ChannelPlatformsProps {
  /**
   * Override the platform list — primarily a test affordance. Defaults
   * to the canonical PLATFORMS constant so production usage stays
   * data-driven.
   */
  platforms?: PlatformDescriptor[];
}

export function ChannelPlatforms({
  platforms = PLATFORMS,
}: ChannelPlatformsProps) {
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const titleId = useId();
  const active = activeSlug
    ? platforms.find((p) => p.platform === activeSlug) ?? null
    : null;

  return (
    <section
      data-testid="channel-platforms-section"
      aria-labelledby={titleId}
      style={sectionStyle}
    >
      <div style={sectionInnerStyle}>
        <p className="wb-mono" style={eyebrowStyle}>
          plate v · the channels
        </p>
        <h2
          id={titleId}
          data-testid="channel-platforms-headline"
          style={headlineStyle}
        >
          One worm, every channel.
          <span style={headlineDashStyle}> — </span>
          <span style={headlineSubStyle}>
            Capability-honest. Click any tile for the install posture.
          </span>
        </h2>
        <p style={subheadStyle}>
          The worm joins where your team already talks. Production
          platforms ship with full ingest + send + DM today; preview
          platforms lurk now, speak when their wire reaches parity. The
          tile reads the canonical descriptor — what you see here is what
          the install path enforces.
        </p>

        <ul
          data-testid="channel-platforms-grid"
          role="list"
          style={gridStyle}
        >
          {platforms.map((p) => (
            <li key={p.platform} style={gridItemStyle}>
              <PlatformTile
                descriptor={p}
                onActivate={() => setActiveSlug(p.platform)}
                isActive={active?.platform === p.platform}
              />
            </li>
          ))}
        </ul>
      </div>

      {active ? (
        <PlatformModal
          descriptor={active}
          onClose={() => setActiveSlug(null)}
        />
      ) : null}
    </section>
  );
}

interface PlatformTileProps {
  descriptor: PlatformDescriptor;
  isActive: boolean;
  onActivate: () => void;
}

function PlatformTile({ descriptor, isActive, onActivate }: PlatformTileProps) {
  const tone = statusToneStyle(descriptor.status);
  return (
    <button
      data-testid={`channel-platform-tile-${descriptor.platform}`}
      data-platform-status={descriptor.status}
      type="button"
      onClick={onActivate}
      title={descriptor.statusNote}
      aria-label={`${descriptor.label} — ${descriptor.status}. ${descriptor.statusNote}`}
      style={{
        ...tileStyle,
        borderColor: isActive
          ? "var(--wb-color-botanical-green)"
          : tone.border,
        boxShadow: isActive
          ? "inset 0 0 0 1px var(--wb-color-botanical-green)"
          : "none",
      }}
    >
      <div style={tileHeaderStyle}>
        <span style={tileTitleStyle}>{descriptor.label}</span>
        <span
          data-testid={`channel-platform-badge-${descriptor.platform}`}
          className="wb-mono"
          style={{
            ...statusBadgeStyle,
            color: tone.fg,
            background: tone.bg,
            borderColor: tone.border,
          }}
        >
          {descriptor.status === "coming_soon" ? "coming soon" : descriptor.status}
        </span>
      </div>
      {descriptor.capabilities && descriptor.capabilities.length > 0 ? (
        <ul
          data-testid={`channel-platform-capabilities-${descriptor.platform}`}
          style={capabilityListStyle}
          aria-label={`${descriptor.label} capabilities`}
        >
          {descriptor.capabilities.map((cap) => (
            <li key={cap} className="wb-mono" style={capabilityChipStyle}>
              {cap}
            </li>
          ))}
        </ul>
      ) : null}
      <p style={tileNoteStyle}>{descriptor.statusNote}</p>
    </button>
  );
}

interface PlatformModalProps {
  descriptor: PlatformDescriptor;
  onClose: () => void;
}

function PlatformModal({ descriptor, onClose }: PlatformModalProps) {
  return (
    <div
      data-testid="channel-platform-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby={`channel-platform-modal-title-${descriptor.platform}`}
      style={modalScrimStyle}
      onClick={onClose}
    >
      <div
        style={modalCardStyle}
        onClick={(e) => e.stopPropagation()}
      >
        <header style={modalHeaderStyle}>
          <div style={modalHeadlineStyle}>
            <span className="wb-mono" style={modalKickerStyle}>
              channel · {descriptor.platform} · {descriptor.status}
            </span>
            <h3
              id={`channel-platform-modal-title-${descriptor.platform}`}
              style={modalTitleStyle}
            >
              {descriptor.label}
            </h3>
          </div>
          <button
            data-testid="channel-platform-modal-close"
            type="button"
            onClick={onClose}
            aria-label={`Close ${descriptor.label} details`}
            style={modalCloseStyle}
          >
            ×
          </button>
        </header>

        <p
          data-testid="channel-platform-modal-status-note"
          style={modalBodyStyle}
        >
          {descriptor.statusNote}
        </p>

        {descriptor.capabilities && descriptor.capabilities.length > 0 ? (
          <section style={modalSectionStyle}>
            <h4 className="wb-mono" style={modalSectionTitleStyle}>
              Capabilities shipped
            </h4>
            <ul
              data-testid="channel-platform-modal-capabilities"
              style={modalCapabilityListStyle}
            >
              {descriptor.capabilities.map((cap) => (
                <li key={cap} className="wb-mono" style={modalCapabilityItemStyle}>
                  {cap}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {descriptor.envHint ? (
          <section style={modalSectionStyle}>
            <h4 className="wb-mono" style={modalSectionTitleStyle}>
              Configure
            </h4>
            <code
              data-testid="channel-platform-modal-env-hint"
              className="wb-mono"
              style={envHintStyle}
            >
              {descriptor.envHint}
            </code>
          </section>
        ) : null}

        <footer style={modalFooterStyle} className="wb-mono">
          {descriptor.status === "production"
            ? "production · install path is the production path · no demo seams"
            : descriptor.status === "preview"
              ? "preview · install + listen real · capability honesty enforced by ledger"
              : "coming soon · skeleton adapter present · no production wire yet"}
        </footer>
      </div>
    </div>
  );
}

interface StatusTone {
  fg: string;
  bg: string;
  border: string;
}

function statusToneStyle(status: PlatformStatus): StatusTone {
  switch (status) {
    case "production":
      return {
        fg: "var(--wb-color-botanical-green-deep)",
        bg: "var(--wb-color-botanical-green-soft)",
        border: "var(--wb-color-botanical-green)",
      };
    case "preview":
      return {
        fg: "var(--wb-color-sepia-warning-deep)",
        bg: "var(--wb-color-sepia-warning-soft)",
        border: "var(--wb-color-sepia-warning)",
      };
    case "coming_soon":
    default:
      return {
        fg: "var(--wb-color-hash-gray)",
        bg: "var(--wb-color-paper-deep)",
        border: "var(--wb-color-paper-edge)",
      };
  }
}

const sectionStyle: CSSProperties = {
  width: "100%",
  borderTop: "1px solid var(--wb-color-rule-line)",
  borderBottom: "1px solid var(--wb-color-rule-line)",
  background: "var(--wb-color-paper)",
  padding: "72px 24px",
};

const sectionInnerStyle: CSSProperties = {
  maxWidth: 1080,
  margin: "0 auto",
  display: "flex",
  flexDirection: "column",
  gap: 24,
};

const eyebrowStyle: CSSProperties = {
  fontSize: 11,
  letterSpacing: "0.24em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
  margin: 0,
};

const headlineStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "clamp(28px, 3.4vw, 40px)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
  letterSpacing: "-0.012em",
  lineHeight: 1.15,
  maxWidth: 820,
};

const headlineDashStyle: CSSProperties = {
  color: "var(--wb-color-hash-gray)",
  fontWeight: 400,
};

const headlineSubStyle: CSSProperties = {
  fontStyle: "italic",
  color: "var(--wb-color-aged-ink-soft)",
};

const subheadStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-md)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.55,
  maxWidth: 720,
};

const gridStyle: CSSProperties = {
  listStyle: "none",
  margin: "16px 0 0",
  padding: 0,
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
  gap: 16,
};

const gridItemStyle: CSSProperties = {
  display: "flex",
};

const tileStyle: CSSProperties = {
  flex: 1,
  textAlign: "left",
  background: "var(--wb-color-paper)",
  border: "1px solid var(--wb-color-rule-line)",
  borderRadius: 2,
  padding: "16px 18px",
  display: "flex",
  flexDirection: "column",
  gap: 10,
  cursor: "pointer",
  fontFamily: "inherit",
  color: "inherit",
  transition:
    "border-color var(--wb-duration-standard) var(--wb-ease-standard), box-shadow var(--wb-duration-standard) var(--wb-ease-standard)",
};

const tileHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
};

const tileTitleStyle: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-md)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
};

const statusBadgeStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  fontSize: 9,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  padding: "2px 6px",
  border: "1px solid",
  borderRadius: 0,
};

const capabilityListStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
};

const capabilityChipStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "lowercase",
  padding: "2px 6px",
  border: "1px solid var(--wb-color-rule-line)",
  background: "var(--wb-color-paper-deep)",
  color: "var(--wb-color-aged-ink-soft)",
};

const tileNoteStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-sm)",
  color: "var(--wb-color-aged-ink-soft)",
  lineHeight: 1.45,
  display: "-webkit-box",
  WebkitBoxOrient: "vertical",
  WebkitLineClamp: 3,
  overflow: "hidden",
};

const modalScrimStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(42, 42, 42, 0.45)",
  zIndex: 1000,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  padding: "32px 16px",
};

const modalCardStyle: CSSProperties = {
  width: "min(560px, 100%)",
  maxHeight: "min(82vh, 720px)",
  overflowY: "auto",
  background: "var(--wb-color-paper)",
  border: "1px solid var(--wb-color-aged-ink)",
  borderRadius: 2,
  padding: "24px 28px",
  display: "flex",
  flexDirection: "column",
  gap: 16,
};

const modalHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 16,
};

const modalHeadlineStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const modalKickerStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const modalTitleStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "clamp(22px, 2.4vw, 28px)",
  fontWeight: 600,
  color: "var(--wb-color-aged-ink)",
  letterSpacing: "-0.01em",
};

const modalCloseStyle: CSSProperties = {
  background: "transparent",
  border: "1px solid var(--wb-color-rule-line)",
  fontSize: 18,
  width: 32,
  height: 32,
  borderRadius: 2,
  cursor: "pointer",
  color: "var(--wb-color-aged-ink)",
};

const modalBodyStyle: CSSProperties = {
  margin: 0,
  fontFamily: "var(--wb-font-serif)",
  fontSize: "var(--wb-text-base)",
  color: "var(--wb-color-aged-ink)",
  lineHeight: 1.6,
};

const modalSectionStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 8,
  borderTop: "1px solid var(--wb-color-rule-line)",
  paddingTop: 14,
};

const modalSectionTitleStyle: CSSProperties = {
  margin: 0,
  fontSize: 11,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

const modalCapabilityListStyle: CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
};

const modalCapabilityItemStyle: CSSProperties = {
  fontSize: 11,
  letterSpacing: "0.04em",
  padding: "4px 8px",
  border: "1px solid var(--wb-color-rule-line)",
  background: "var(--wb-color-paper-deep)",
  color: "var(--wb-color-aged-ink)",
};

const envHintStyle: CSSProperties = {
  fontSize: 11,
  padding: "6px 8px",
  background: "var(--wb-color-paper-deep)",
  border: "1px solid var(--wb-color-rule-line)",
  color: "var(--wb-color-aged-ink)",
  borderRadius: 0,
  alignSelf: "flex-start",
};

const modalFooterStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.16em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
  borderTop: "1px solid var(--wb-color-rule-line)",
  paddingTop: 12,
};
