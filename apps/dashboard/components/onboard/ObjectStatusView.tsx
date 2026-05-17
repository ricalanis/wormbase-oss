/**
 * ObjectStatusView — universal status surface for ``@status <object>``
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * Renders an ``ObjectStatus`` (works / degraded / failed / unknown) with
 * the underlying state explanation + recovery hint. Real probes for
 * connectors land in Sub-wave D; until then, state is derived from
 * ledger projections.
 *
 * Honest empty-state UX rule (`Don't render nothing on empty data`): if
 * the kind has no real probe wired, the panel says so loudly so an
 * operator never reads a placeholder as a working signal.
 */

import Link from "next/link";
import type { JSX } from "react";

import { CapabilityBadges } from "./CapabilityBadges";
import type {
  CapabilityKind,
  CapabilityStatus,
} from "./CapabilityBadges";
import type { ObjectStatus, StatusKind } from "../../lib/onboard";

export interface ObjectStatusViewProps {
  status: ObjectStatus;
}

function toCapabilityStatus(state: ObjectStatus["state"]): CapabilityStatus {
  switch (state) {
    case "works":
      return "works";
    case "degraded":
      return "degraded";
    case "failed":
      return "failed";
    case "unknown":
      return "unknown";
  }
}

function toCapabilityKind(kind: StatusKind): CapabilityKind {
  return kind;
}

export function ObjectStatusView({
  status,
}: ObjectStatusViewProps): JSX.Element {
  return (
    <section
      data-testid={`object-status-${status.kind}`}
      style={{
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
          {status.kind} · status
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 28,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          {status.label}
        </h1>
        <code
          className="wb-mono"
          data-testid={`object-status-id-${status.kind}`}
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {status.objectId}
        </code>
      </header>

      <CapabilityBadges
        kind={toCapabilityKind(status.kind)}
        id={status.objectId}
        capabilities={status.capabilities}
        status={toCapabilityStatus(status.state)}
        statusNote={status.summary}
      />

      {!status.probeImplemented ? (
        <div
          data-testid={`object-status-probe-pending-${status.kind}`}
          role="note"
          style={{
            border: "1px dashed var(--wb-color-hash-gray)",
            background: "var(--wb-color-paper)",
            padding: 12,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            probe not yet implemented
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              fontSize: 13,
              color: "var(--wb-color-aged-ink)",
              maxWidth: 720,
            }}
          >
            Status is derived from existing ledger projections for this
            sub-wave. Real probes (network reach, auth handle validity,
            sample fetch) land in Sub-wave D for connectors; other kinds
            stay projection-derived.
          </p>
        </div>
      ) : null}

      {status.recoveryHint ? (
        <div
          data-testid={`object-status-recovery-${status.kind}`}
          style={{
            border: "1px solid var(--wb-color-paper-edge)",
            background: "var(--wb-color-paper-deep)",
            padding: 12,
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            recovery hint
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 13,
              color: "var(--wb-color-aged-ink)",
            }}
          >
            {status.recoveryHint}
          </p>
        </div>
      ) : null}

      <nav
        style={{
          display: "flex",
          gap: 12,
          marginTop: 6,
          flexWrap: "wrap",
        }}
      >
        <Link
          href={`/logs/${status.kind}/${encodeURIComponent(status.objectId)}`}
          data-testid={`object-status-logs-link-${status.kind}`}
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            padding: "6px 12px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-paper)",
            color: "var(--wb-color-aged-ink)",
            textDecoration: "none",
          }}
        >
          See logs
        </Link>
        <Link
          href="/onboard"
          data-testid={`object-status-onboard-link-${status.kind}`}
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            padding: "6px 12px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "transparent",
            color: "var(--wb-color-aged-ink)",
            textDecoration: "none",
          }}
        >
          Back to /onboard
        </Link>
      </nav>
    </section>
  );
}
