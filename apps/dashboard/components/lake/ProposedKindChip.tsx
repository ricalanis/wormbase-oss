/**
 * ProposedKindChip — colored chip for the free-form
 * ``proposed_kind`` connector-registry string surfaced on
 * /lake/source-candidates rows (L1 Sub-wave D, 2026-06-08).
 *
 * Unlike L8's ``EntityKindChip`` (8 strict Literal values), L1's
 * ``proposed_kind`` is a free-form connector-registry string — the
 * ledger payload validates it at write time against
 * ``wormbase_lake_surfaces.registry.default_registry()`` but the type is
 * NOT a Literal (per spec §4.2 — connector kinds are configuration,
 * not KIND_REGISTRY entries). New connectors can ship without dashboard
 * churn.
 *
 * The chip palette covers the 12 day-one connector kinds (csv_local /
 * postgres / snowflake / stripe / salesforce / hubspot / gsheets /
 * bigquery / s3_csv / http_csv / rest_api / other). Any unknown kind
 * (including ``mcp:*`` namespaced kinds) falls back to a muted slate
 * style — same "unclassified" discipline as L8's ``other`` tier — so
 * fresh connectors still render readably until a palette slot is
 * picked. ``mcp:*`` shares one muted color per Sub-wave D plan.
 *
 * Per Sub-wave C handoff concern #4 (``_proposed_kind_to_source_kind``
 * heuristic — connector resolution is downstream's job), the chip
 * renders the raw projection ``proposed_kind`` verbatim. No
 * normalisation.
 */

"use client";

interface ChipColors {
  bg: string;
  fg: string;
  border: string;
}

/**
 * Per-kind visual signature. The 12 day-one connectors get distinct
 * palette slots (paired with L6 ColumnClassificationRow / L8
 * EntityKindChip discipline). ``mcp:*`` and unknown kinds share the
 * muted slate tier so the chip stays legible without a palette
 * conflict.
 */
function kindChipStyle(kind: string): ChipColors {
  // mcp:* — shared muted purple-slate (any namespaced MCP server)
  if (kind.startsWith("mcp:")) {
    return {
      bg: "var(--wb-color-paper-deep, #f4eedb)",
      fg: "#5b4f6a",
      border: "#5b4f6a",
    };
  }
  switch (kind) {
    case "csv_local":
      // Paper / aged-ink — the canonical "file" baseline.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-aged-ink, #2a2620)",
        border: "var(--wb-color-aged-ink, #2a2620)",
      };
    case "postgres":
      // Archive-blue — the canonical "database" hue.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-archive-blue-deep, #2c5f7c)",
        border: "var(--wb-color-archive-blue-deep, #2c5f7c)",
      };
    case "snowflake":
      // Deeper indigo — distinguishes warehouse from OLTP.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#2a3d7a",
        border: "#2a3d7a",
      };
    case "bigquery":
      // Teal — warehouse hue distinct from snowflake indigo.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#1e6f72",
        border: "#1e6f72",
      };
    case "stripe":
      // Botanical-green — the canonical "money / payments" hue
      // (paired with L8's transaction entity_kind).
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-botanical-green-deep, #2d5d3a)",
        border: "var(--wb-color-botanical-green-deep, #2d5d3a)",
      };
    case "salesforce":
      // Sepia-warning — the canonical CRM / sales hue.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-sepia-warning-deep, #b6741c)",
        border: "var(--wb-color-sepia-warning-deep, #b6741c)",
      };
    case "hubspot":
      // Distinct rust — sales/marketing CRM but visually distinct
      // from salesforce sepia.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#a8503a",
        border: "#a8503a",
      };
    case "gsheets":
      // Botanical-green-light variant — spreadsheet hue.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#3d7350",
        border: "#3d7350",
      };
    case "s3_csv":
      // Deep purple — object-storage hue.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#5b3a8a",
        border: "#5b3a8a",
      };
    case "http_csv":
      // Pink-rose — http file hue, distinct from s3.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#a8366a",
        border: "#a8366a",
      };
    case "rest_api":
      // Deeper indigo — generic API hue.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#3b3f8c",
        border: "#3b3f8c",
      };
    case "other":
      // Muted slate — the "unclassified" tier mirroring L8's `other`.
      return {
        bg: "var(--wb-color-paper-deep, #f4eedb)",
        fg: "var(--wb-color-hash-gray, #7c7569)",
        border: "var(--wb-color-paper-edge, #d8d2c2)",
      };
    default:
      // Unknown connector kind — fall back to the muted-slate
      // "unknown" tier. New connectors render readably without a
      // dashboard release, per spec §4.2.
      return {
        bg: "var(--wb-color-paper-deep, #f4eedb)",
        fg: "var(--wb-color-hash-gray, #7c7569)",
        border: "var(--wb-color-paper-edge, #d8d2c2)",
      };
  }
}

const KNOWN_KINDS: ReadonlySet<string> = new Set([
  "csv_local",
  "postgres",
  "snowflake",
  "bigquery",
  "stripe",
  "salesforce",
  "hubspot",
  "gsheets",
  "s3_csv",
  "http_csv",
  "rest_api",
  "other",
]);

function isKnown(kind: string): boolean {
  return KNOWN_KINDS.has(kind) || kind.startsWith("mcp:");
}

export interface ProposedKindChipProps {
  kind: string;
  /** Test-id suffix so multiple chips on a page each get a unique
   *  ``data-testid``. */
  testIdSuffix: string;
}

export function ProposedKindChip({
  kind,
  testIdSuffix,
}: ProposedKindChipProps): JSX.Element {
  const c = kindChipStyle(kind);
  const known = isKnown(kind);
  return (
    <span
      data-testid={`source-candidate-kind-chip-${testIdSuffix}`}
      data-kind={kind}
      data-known={known ? "true" : "false"}
      aria-label={
        known ? `proposed_kind=${kind}` : `proposed_kind=${kind} (unknown)`
      }
      className="wb-mono"
      style={{
        display: "inline-block",
        padding: "2px 8px",
        border: `1px solid ${c.border}`,
        background: c.bg,
        color: c.fg,
        fontSize: 10,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        fontWeight: 600,
        // Slightly de-emphasised typography for unknown kinds — same
        // discipline as L8's ``other`` tier.
        opacity: known ? 1.0 : 0.85,
      }}
    >
      {kind}
    </span>
  );
}
