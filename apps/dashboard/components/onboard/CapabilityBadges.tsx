/**
 * CapabilityBadges — shared status + capability badge component
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * Generalizes the badge pattern from L3's ``StrategyStatusBanner``
 * (`apps/dashboard/components/lake/StrategyStatusBanner.tsx`) and from
 * the channel/connector capability surfaces (``platform-status.ts``,
 * ``lake-surfaces-catalog.ts``). One component used across the unified
 * `/onboard/*` tabs + the universal `/status` and `/logs` views.
 *
 * The badge pattern: a small uppercase wb-mono label with a colored
 * cue. Status colors mirror the wb-color tokens already used by
 * ``StrategyStatusBanner`` and ``ConnectorCatalogRow``:
 *
 *   * production / works     → botanical-green-deep
 *   * preview / degraded     → sepia-warning-deep
 *   * configured · stubbed   → sepia-warning-deep
 *   * coming_soon / unknown  → hash-gray
 *   * disabled               → hash-gray (muted)
 *   * failed                 → sepia-warning-deep (with louder copy)
 *
 * Capability badges sit alongside the status badge. Each capability is
 * a small wb-mono uppercase token (e.g. `discover · profile · sample`)
 * rendered in hash-gray so capability declarations read as honest
 * metadata, not advertising.
 *
 * The component is presentational only — callers pass status +
 * capabilities; no data fetching, no projections, no side effects.
 */

import type { JSX } from "react";

/**
 * Status enum covers every honest state across the institutional
 * ontology:
 *
 *   * "production"           — every method wired against the real platform
 *   * "preview"              — wired end-to-end, awaiting graduation
 *   * "coming_soon"          — skeleton only
 *   * "configured-stubbed"   — env knob set but implementation is a no-op
 *                              (mirrors L3 `configured · stubbed`)
 *   * "disabled"             — env knob off
 *   * "works"                — probe succeeded
 *   * "degraded"             — probe partial / warning
 *   * "failed"               — probe failed
 *   * "unknown"              — probe not yet implemented for this kind
 */
export type CapabilityStatus =
  | "production"
  | "preview"
  | "coming_soon"
  | "configured-stubbed"
  | "disabled"
  | "works"
  | "degraded"
  | "failed"
  | "unknown";

/**
 * Object kinds the badge component knows how to render. Capability
 * labels and accents may differ subtly per kind (a connector's
 * capabilities include `discover/profile/sample/watch`, a channel
 * adapter's include `ingest/send/dm/file_upload`, a domain has no
 * capabilities in the connector sense, etc.). The component itself
 * stays presentational — it renders whatever capability strings the
 * caller passes; the `kind` prop participates only in the data-testid
 * suffix so per-tab tests can target unambiguously.
 */
export type CapabilityKind =
  | "connector"
  | "channel"
  | "domain"
  | "person"
  | "policy"
  | "agent"
  | "subscription";

export interface CapabilityBadgesProps {
  /** Object kind — feeds the data-testid suffix; not visually rendered. */
  kind: CapabilityKind;
  /** Optional identifier to disambiguate the testid when multiple
   *  badges of the same kind render on the same page (e.g. a list of
   *  connectors). */
  id?: string;
  /** Capabilities declared by the object (e.g. `["discover", "profile"]`). */
  capabilities?: string[];
  /** Honest status. */
  status: CapabilityStatus;
  /** Optional status-note line shown below the badges. Italic, hash-gray. */
  statusNote?: string;
}

interface BadgeAccent {
  label: string;
  color: string;
  testIdSuffix: string;
}

function accentFor(status: CapabilityStatus): BadgeAccent {
  switch (status) {
    case "production":
      return {
        label: "production",
        color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
        testIdSuffix: "production",
      };
    case "works":
      return {
        label: "works",
        color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
        testIdSuffix: "works",
      };
    case "preview":
      return {
        label: "preview",
        color: "var(--wb-color-sepia-warning-deep, #b6741c)",
        testIdSuffix: "preview",
      };
    case "degraded":
      return {
        label: "degraded",
        color: "var(--wb-color-sepia-warning-deep, #b6741c)",
        testIdSuffix: "degraded",
      };
    case "configured-stubbed":
      return {
        label: "configured · stubbed",
        color: "var(--wb-color-sepia-warning-deep, #b6741c)",
        testIdSuffix: "stubbed",
      };
    case "failed":
      return {
        label: "failed",
        color: "var(--wb-color-sepia-warning-deep, #b6741c)",
        testIdSuffix: "failed",
      };
    case "coming_soon":
      return {
        label: "coming soon",
        color: "var(--wb-color-hash-gray, #7c7569)",
        testIdSuffix: "coming-soon",
      };
    case "disabled":
      return {
        label: "disabled",
        color: "var(--wb-color-hash-gray, #7c7569)",
        testIdSuffix: "disabled",
      };
    case "unknown":
      return {
        label: "unknown",
        color: "var(--wb-color-hash-gray, #7c7569)",
        testIdSuffix: "unknown",
      };
  }
}

export function CapabilityBadges({
  kind,
  id,
  capabilities,
  status,
  statusNote,
}: CapabilityBadgesProps): JSX.Element {
  const accent = accentFor(status);
  const suffix = id ? `-${id}` : "";
  return (
    <div
      data-testid={`capability-badges-${kind}${suffix}`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <span
          className="wb-mono"
          data-testid={`capability-status-${kind}${suffix}-${accent.testIdSuffix}`}
          style={{
            fontSize: 10,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: accent.color,
          }}
        >
          {accent.label}
        </span>
        {capabilities && capabilities.length > 0 ? (
          <span
            className="wb-mono"
            data-testid={`capability-list-${kind}${suffix}`}
            style={{
              fontSize: 10,
              letterSpacing: "0.1em",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            {capabilities.join(" · ")}
          </span>
        ) : null}
      </div>
      {statusNote ? (
        <span
          data-testid={`capability-note-${kind}${suffix}`}
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            fontSize: 12,
            color: "var(--wb-color-hash-gray, #7c7569)",
            maxWidth: 720,
          }}
        >
          {statusNote}
        </span>
      ) : null}
    </div>
  );
}
