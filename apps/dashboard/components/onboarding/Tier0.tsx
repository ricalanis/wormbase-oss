"use client";
/**
 * Tier 0 — production landing page (Block I3).
 *
 * One-tap chat-platform connect. After Block I, this is the entire
 * Tier 0 surface — no connector grid. The default local lake is
 * provisioned automatically when the tenant completes install (I2;
 * see provision_local_lake in worm-core/write_actions.py). External
 * data sources move to post-install progressive enhancement,
 * reachable from /sources/new or via worm conversation.
 *
 * Buttons render from the canonical PLATFORMS descriptor list in
 * lib/platform-status.ts so capability honesty stays consistent
 * across the dashboard. Production platforms (Slack today) are
 * primary; preview platforms (Discord, Teams) render dimmer with a
 * preview badge; coming_soon platforms are filtered out at this
 * surface (the connector picker at /sources/new is the right
 * place for the long tail).
 *
 * No installer-name/email form here — those come from the provider's
 * profile API after OAuth completes (Slack ``users.info``, Discord
 * ``/users/@me``, etc.). Capturing them client-side before OAuth
 * would be a chance for them to disagree with the platform, and
 * there's no production reason to ask twice.
 *
 * The "Already installed? Sign in" link routes the operator to the
 * existing-tenant flow (the redirect guard handles the tenant
 * lookup) for users returning to a previously-installed workspace.
 */
import { useSearchParams } from "next/navigation";

import { PLATFORMS, type PlatformDescriptor } from "../../lib/platform-status";

type RenderablePlatform = {
  id: string;
  label: string;
  status: "production" | "preview";
  statusNote: string;
};

type RenderablePlatformDescriptor = PlatformDescriptor & {
  status: "production" | "preview";
};

const RENDERED_PLATFORMS: RenderablePlatform[] = PLATFORMS.filter(
  (p): p is RenderablePlatformDescriptor =>
    p.status === "production" || p.status === "preview",
).map((p) => ({
  id: p.platform,
  label: p.label,
  status: p.status,
  statusNote: p.statusNote,
}));

export function Tier0() {
  const searchParams = useSearchParams();
  const error = searchParams.get("error");
  const hint = searchParams.get("hint");

  return (
    <section
      data-testid="onboarding-tier0"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        border: "1px solid var(--wb-color-paper-edge)",
        padding: 20,
        background: "var(--wb-color-paper)",
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
          tier 0 · landing
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 22,
            fontWeight: 500,
          }}
        >
          Connect a channel
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Pick a platform. The worm joins your workspace, provisions a
          default lake, and starts lurking for ingest within 30 seconds.
          External data sources connect later — from chat or from /sources.
        </p>
      </header>

      <div
        data-testid="tier0-platform-buttons"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        {RENDERED_PLATFORMS.map((p) => (
          <a
            key={p.id}
            href={`/onboarding/oauth/${p.id}/start`}
            data-testid={`tier0-connect-${p.id}`}
            data-platform-status={p.status}
            title={p.statusNote}
            className="wb-mono"
            style={{
              fontSize: 12,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              padding: "10px 16px",
              border: "1px solid var(--wb-color-aged-ink)",
              background:
                p.status === "production"
                  ? "var(--wb-color-botanical-green-soft)"
                  : "var(--wb-color-paper-deep)",
              color: "var(--wb-color-aged-ink)",
              cursor: "pointer",
              borderRadius: 0,
              textDecoration: "none",
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              opacity: p.status === "production" ? 1 : 0.85,
            }}
          >
            <span>connect {p.label}</span>
            {p.status === "preview" ? (
              <span
                data-testid={`tier0-${p.id}-preview-badge`}
                style={{
                  fontSize: 9,
                  letterSpacing: "0.08em",
                  padding: "1px 5px",
                  border: "1px solid var(--wb-color-hash-gray)",
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                preview
              </span>
            ) : null}
          </a>
        ))}
      </div>

      <a
        href="/login"
        data-testid="tier0-sign-in"
        className="wb-mono"
        style={{
          fontSize: 11,
          letterSpacing: "0.04em",
          color: "var(--wb-color-hash-gray)",
          textDecoration: "underline",
          textUnderlineOffset: 3,
          alignSelf: "flex-start",
        }}
      >
        already installed? sign in
      </a>

      {error ? (
        <div
          data-testid="tier0-error"
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-sepia-warning-deep)",
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            background: "var(--wb-color-sepia-warning-soft)",
            padding: "8px 12px",
          }}
        >
          <strong style={{ display: "block", marginBottom: 4 }}>
            {error}
          </strong>
          {hint ? <span>{hint}</span> : null}
        </div>
      ) : null}
    </section>
  );
}
