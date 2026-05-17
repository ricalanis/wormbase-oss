"use client";
/**
 * ConnectPlatformButtons — one button per supported `ChannelAdapter`.
 *
 * D3 of docs/superpowers/plans/2026-04-26-production-dashboard.md.
 *
 * Reads from ``lib/platform-status.ts`` (canonical descriptor list).
 * Each platform descriptor's ``status`` drives the button's render:
 *
 *   - production: solid color, enabled. Click → /onboarding/oauth/<id>/start.
 *   - preview: outline color + "Preview" badge, enabled. Click →
 *     /onboarding/oauth/<id>/start (the worm will lurk; admins are
 *     warned via the banner that send isn't yet wired).
 *   - coming_soon: greyed out + "Coming soon" badge. Click → modal
 *     explaining what's not yet wired (no OAuth flow).
 *
 * Per the onboarding-production-only feedback: env-unset platforms must
 * NOT silently route to a synthesized OAuth grant. ``envState`` (server
 * resolved) controls whether a button shows "Configure: $envHint"
 * instead of "Connect" — preventing the synthesized-grant footgun.
 */
import { useState } from "react";
import {
  PLATFORMS,
  type PlatformDescriptor,
  type PlatformStatus,
} from "../../lib/platform-status";

interface ConnectPlatformButtonsProps {
  /**
   * Optional server-resolved env state. When provided, production /
   * preview buttons whose required env tokens are MISSING render as
   * disabled "Configure: $envHint" buttons — never as routes to a
   * synthesized-grant flow. When omitted (e.g. tests), buttons assume
   * env is configured.
   */
  envState?: { [envVarName: string]: boolean };
}

interface ButtonVisuals {
  background: string;
  border: string;
  badgeLabel: string | null;
  badgeBg: string;
  badgeColor: string;
}

function visualsFor(status: PlatformStatus): ButtonVisuals {
  switch (status) {
    case "production":
      return {
        background: "var(--wb-color-botanical-green-soft)",
        border: "1px solid var(--wb-color-aged-ink)",
        badgeLabel: null,
        badgeBg: "transparent",
        badgeColor: "var(--wb-color-botanical-green-deep)",
      };
    case "preview":
      return {
        background: "var(--wb-color-paper)",
        border: "1px solid var(--wb-color-sepia-warning-deep)",
        badgeLabel: "preview",
        badgeBg: "transparent",
        badgeColor: "var(--wb-color-sepia-warning-deep)",
      };
    case "coming_soon":
    default:
      return {
        background: "var(--wb-color-paper-deep)",
        border: "1px dashed var(--wb-color-paper-edge)",
        badgeLabel: "coming soon",
        badgeBg: "transparent",
        badgeColor: "var(--wb-color-hash-gray)",
      };
  }
}

function envIsConfigured(
  descriptor: PlatformDescriptor,
  envState: ConnectPlatformButtonsProps["envState"],
): boolean {
  if (descriptor.status === "coming_soon") return false;
  if (envState === undefined) return true; // assume configured (test default)
  if (!descriptor.envHint) return true;
  return descriptor.envHint
    .split("+")
    .map((s) => s.trim())
    .filter(Boolean)
    .every((key) => envState[key] === true);
}

export function ConnectPlatformButtons({
  envState,
}: ConnectPlatformButtonsProps = {}) {
  const [openModal, setOpenModal] = useState<PlatformDescriptor | null>(null);
  const close = () => setOpenModal(null);

  return (
    <section
      data-testid="connect-platform-buttons"
      style={{ display: "flex", flexDirection: "column", gap: 10 }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.18em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        connect another platform
      </span>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {PLATFORMS.map((p) => {
          const v = visualsFor(p.status);
          const configured = envIsConfigured(p, envState);
          const isComingSoon = p.status === "coming_soon";
          const needsConfig = !isComingSoon && !configured;

          return (
            <button
              key={p.platform}
              type="button"
              data-testid={`connect-${p.platform}`}
              data-ready={p.status === "production" ? "true" : "false"}
              data-status={p.status}
              data-configured={configured ? "true" : "false"}
              aria-disabled={isComingSoon || needsConfig}
              title={p.statusNote}
              onClick={() => {
                if (isComingSoon) {
                  setOpenModal(p);
                  return;
                }
                if (needsConfig) {
                  setOpenModal(p);
                  return;
                }
                window.location.href = `/onboarding/oauth/${p.platform}/start`;
              }}
              className="wb-mono"
              style={{
                fontSize: 11,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                padding: "6px 12px",
                border: v.border,
                background: v.background,
                color: "var(--wb-color-aged-ink)",
                cursor: isComingSoon ? "not-allowed" : "pointer",
                borderRadius: 0,
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                opacity: isComingSoon ? 0.55 : 1,
              }}
            >
              <span>
                {needsConfig ? `configure ${p.label}` : `connect ${p.label}`}
              </span>
              {v.badgeLabel ? (
                <span
                  data-testid={`connect-${p.platform}-badge`}
                  style={{
                    fontSize: 9,
                    letterSpacing: "0.08em",
                    color: v.badgeColor,
                    background: v.badgeBg,
                    border: `1px solid ${v.badgeColor}`,
                    padding: "0 4px",
                  }}
                >
                  {v.badgeLabel}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {openModal ? (
        <div
          data-testid={`connect-modal-${openModal.platform}`}
          role="dialog"
          aria-label={`Connect ${openModal.label}`}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(20, 20, 20, 0.45)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
          }}
          onClick={close}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "var(--wb-color-paper)",
              border: "1px solid var(--wb-color-aged-ink)",
              padding: 24,
              maxWidth: 460,
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span
                className="wb-mono"
                style={{
                  fontSize: 10,
                  letterSpacing: "0.18em",
                  textTransform: "uppercase",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                {openModal.status === "coming_soon" ? "coming soon" : "configuration required"}
              </span>
              <h3
                style={{
                  margin: 0,
                  fontFamily: "var(--wb-font-serif)",
                  fontSize: 22,
                }}
              >
                {openModal.label}
              </h3>
            </header>
            <p
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                color: "var(--wb-color-aged-ink)",
                lineHeight: 1.5,
              }}
            >
              {openModal.status === "coming_soon"
                ? openModal.statusNote
                : openModal.envHint
                  ? `Set ${openModal.envHint} on the server to enable the OAuth flow. Real grants only — no synthesized credentials.`
                  : openModal.statusNote}
            </p>
            <button
              type="button"
              onClick={close}
              data-testid="connect-modal-close"
              className="wb-mono"
              style={{
                alignSelf: "flex-end",
                fontSize: 11,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                padding: "6px 12px",
                border: "1px solid var(--wb-color-aged-ink)",
                background: "var(--wb-color-paper)",
                cursor: "pointer",
                borderRadius: 0,
              }}
            >
              close
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
