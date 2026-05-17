/**
 * PolicySideBySide — two-column side-by-side view for /lake/governance.
 *
 * Left column: upstream catalog-mirror policies (masking + row-access
 * pulled from ``projection_external_policy``). Right column: WormBase-
 * applied policies (warmup pack, PII redact, interjection budget,
 * channel talkativeness, …) folded from ``emit_policy_applied``.
 *
 * The component is pure presentational — the page handles the
 * combined empty state. When ONE column is non-empty, that column
 * renders normally and the other column shows its own "nothing yet"
 * affordance (so the operator still sees the surface and the empty
 * column isn't a silent panel — see CLAUDE.md §9).
 *
 * S2 spike contract surfacing:
 *
 *   * ``body == null`` on an upstream policy renders the
 *     "Body unavailable (insufficient APPLY privilege)" placeholder
 *     copy with a hash-gray italic treatment. This is the load-
 *     bearing UI affordance for the S2 finding — a read-only
 *     Snowflake catalog credential cannot fetch policy SQL, and
 *     the dashboard is honest about it rather than hiding the policy.
 */

import type {
  ExternalPolicyRow,
  WormbasePolicyRow,
} from "../../lib/lake-governance";

export interface PolicySideBySideProps {
  externalPolicies: ExternalPolicyRow[];
  wormbasePolicies: WormbasePolicyRow[];
}

const COLUMN_STYLE: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  display: "flex",
  flexDirection: "column",
  gap: 12,
};

const COLUMN_HEADER_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 11,
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray, #6b6256)",
  marginBottom: 4,
};

const COLUMN_TITLE_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 22,
  fontWeight: 500,
  letterSpacing: "-0.01em",
  margin: 0,
};

const CARD_STYLE: React.CSSProperties = {
  padding: "14px 16px",
  border: "1px solid var(--wb-color-edge, rgba(0,0,0,0.12))",
  borderRadius: 6,
  background: "var(--wb-color-paper, #fbfaf6)",
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const POLICY_NAME_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-serif, Georgia, serif)",
  fontSize: 15,
  fontWeight: 500,
  margin: 0,
};

const KIND_PILL_STYLE: React.CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 4,
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 10,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
  background: "var(--wb-color-edge, rgba(0,0,0,0.06))",
  color: "var(--wb-color-hash-gray, #6b6256)",
};

const BODY_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 12,
  background: "var(--wb-color-paper-deep, rgba(0,0,0,0.04))",
  padding: "8px 10px",
  borderRadius: 4,
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  margin: 0,
};

const META_STYLE: React.CSSProperties = {
  fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
  fontSize: 11,
  color: "var(--wb-color-hash-gray, #6b6256)",
};

const PLACEHOLDER_STYLE: React.CSSProperties = {
  ...BODY_STYLE,
  fontStyle: "italic",
  color: "var(--wb-color-hash-gray, #6b6256)",
};

const EMPTY_COLUMN_STYLE: React.CSSProperties = {
  ...CARD_STYLE,
  alignItems: "flex-start",
  background: "var(--wb-color-paper, #fbfaf6)",
  borderStyle: "dashed",
};

function fmtTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toISOString().replace("T", " ").slice(0, 16);
  } catch {
    return iso;
  }
}

function ExternalPolicyCard({
  row,
}: {
  row: ExternalPolicyRow;
}): JSX.Element {
  const bodyMissing = row.body === null;
  return (
    <div
      style={CARD_STYLE}
      data-testid={`external-policy-${row.id}`}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <h3 style={POLICY_NAME_STYLE}>{row.policyFqn}</h3>
        <span style={KIND_PILL_STYLE}>{row.policyKind}</span>
      </div>
      <div style={META_STYLE}>
        <span>{row.sourceName}</span>
        {row.appliedTo.length > 0 ? (
          <>
            {" · "}
            <span data-testid="external-policy-applied-to">
              {row.appliedTo.join(", ")}
            </span>
          </>
        ) : null}
      </div>
      {bodyMissing ? (
        <p
          style={PLACEHOLDER_STYLE}
          data-testid="external-policy-body-unavailable"
        >
          Body unavailable (insufficient APPLY privilege)
        </p>
      ) : (
        <pre
          style={BODY_STYLE}
          data-testid="external-policy-body"
        >
          {row.body}
        </pre>
      )}
      <div style={META_STYLE}>
        imported {fmtTimestamp(row.importedAt)}
      </div>
    </div>
  );
}

function WormbasePolicyCard({
  row,
}: {
  row: WormbasePolicyRow;
}): JSX.Element {
  return (
    <div
      style={CARD_STYLE}
      data-testid={`wormbase-policy-${row.id}`}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <h3 style={POLICY_NAME_STYLE}>{row.policyName}</h3>
        <span style={KIND_PILL_STYLE}>{row.scope}</span>
      </div>
      <div style={META_STYLE}>{row.plainLanguage}</div>
      {row.body ? (
        <pre
          style={BODY_STYLE}
          data-testid="wormbase-policy-body"
        >
          {row.body}
        </pre>
      ) : (
        <p
          style={PLACEHOLDER_STYLE}
          data-testid="wormbase-policy-body-unavailable"
        >
          No gate implementation registered yet
        </p>
      )}
    </div>
  );
}

function EmptyColumn({
  message,
  testId,
}: {
  message: string;
  testId: string;
}): JSX.Element {
  return (
    <div
      style={EMPTY_COLUMN_STYLE}
      data-testid={testId}
    >
      <span style={META_STYLE}>{message}</span>
    </div>
  );
}

export function PolicySideBySide({
  externalPolicies,
  wormbasePolicies,
}: PolicySideBySideProps): JSX.Element {
  return (
    <div
      data-testid="policy-side-by-side"
      style={{
        display: "flex",
        gap: 24,
        flexWrap: "wrap",
        alignItems: "flex-start",
      }}
    >
      <section
        style={COLUMN_STYLE}
        aria-label="Upstream policies"
        data-testid="upstream-column"
      >
        <header>
          <div style={COLUMN_HEADER_STYLE}>
            upstream · catalog mirror
          </div>
          <h2 style={COLUMN_TITLE_STYLE}>
            Upstream policies · {externalPolicies.length}
          </h2>
        </header>
        {externalPolicies.length === 0 ? (
          <EmptyColumn
            testId="upstream-empty"
            message={
              "No upstream policies mirrored yet. Connect a Snowflake / dbt " +
              "catalog source to start mirroring masking + row-access policies."
            }
          />
        ) : (
          externalPolicies.map((row) => (
            <ExternalPolicyCard key={row.id} row={row} />
          ))
        )}
      </section>
      <section
        style={COLUMN_STYLE}
        aria-label="WormBase policies"
        data-testid="wormbase-column"
      >
        <header>
          <div style={COLUMN_HEADER_STYLE}>
            wormbase · applied
          </div>
          <h2 style={COLUMN_TITLE_STYLE}>
            WormBase policies · {wormbasePolicies.length}
          </h2>
        </header>
        {wormbasePolicies.length === 0 ? (
          <EmptyColumn
            testId="wormbase-empty"
            message={
              "No WormBase policies applied yet. Warmup applies the canonical " +
              "pack on first run; visit /policies for the full register."
            }
          />
        ) : (
          wormbasePolicies.map((row) => (
            <WormbasePolicyCard key={row.id} row={row} />
          ))
        )}
      </section>
    </div>
  );
}
