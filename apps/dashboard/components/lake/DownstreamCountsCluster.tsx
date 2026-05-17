/**
 * DownstreamCountsCluster — compact horizontal chip cluster surfacing
 * reverse-arc counts on the L5 semantic-types row (2026-05-16).
 *
 * The L5 producer page is consumed by 4 downstream axes (L6
 * classifications, L8 entity stitches, L7 quality checks, L4 schema
 * impacts). Rather than stack 4 separate badges (vertical bloat), this
 * component renders up to 4 link-chips in a single inline row labelled
 * "Downstream:". Each chip is omitted when its count is 0; if all 4
 * are 0, the whole cluster renders nothing (honest empty state).
 *
 * Per Recipe Addendum #3 (L4↦L2 close-out): reverse arcs are
 * dashboard-only enrichment — no new ledger writes, no new Protocols,
 * no env knob. The cluster reads pre-fetched count maps from the page
 * accessor and renders inline filter-deeplinks to each consumer's
 * audit surface.
 *
 * Honest empty: when ``classificationCount``, ``entityStitchCount``,
 * ``qualityCount``, and ``impactCount`` are all undefined-or-zero,
 * the component returns ``null``. When some are populated, only the
 * populated chips render — never a "0" chip.
 */

"use client";

export interface DownstreamCountsClusterProps {
  /** L5 type_id — used to build the filter-deeplink query param. */
  semanticTypeId: string;
  /** R2 L6↦L5 — count of L6 column-classification rows derived from this type. */
  classificationCount?: number;
  /** R3 L8↦L5 — count of L8 entity-stitch rows derived from this type. */
  entityStitchCount?: number;
  /** R4 L7↦L5 — count of L7 quality-check rows derived from this type. */
  qualityCount?: number;
  /** R6 L4↦L5 — count of L4 schema-impact rows derived from this type. */
  impactCount?: number;
}

interface ChipSpec {
  /** Stable testid suffix (chain label). */
  testId: string;
  /** Consumer-axis label shown on the chip. */
  label: string;
  /** Count surfaced on the chip. */
  count: number;
  /** Consumer audit-page deeplink. */
  href: string;
  /** Tooltip when hovered. */
  title: string;
}

export function DownstreamCountsCluster({
  semanticTypeId,
  classificationCount,
  entityStitchCount,
  qualityCount,
  impactCount,
}: DownstreamCountsClusterProps): JSX.Element | null {
  const encoded = encodeURIComponent(semanticTypeId);
  const chips: ChipSpec[] = [];

  if (typeof classificationCount === "number" && classificationCount > 0) {
    chips.push({
      testId: "classification",
      label: `↪ ${classificationCount} classification${
        classificationCount === 1 ? "" : "s"
      } via L6`,
      count: classificationCount,
      href: `/lake/column-classification?upstream_semantic_type_id=${encoded}`,
      title:
        "View L6 column-classification rows derived from this semantic type",
    });
  }
  if (typeof entityStitchCount === "number" && entityStitchCount > 0) {
    chips.push({
      testId: "entity-stitch",
      label: `↪ ${entityStitchCount} entity stitch${
        entityStitchCount === 1 ? "" : "es"
      } via L8`,
      count: entityStitchCount,
      href: `/lake/entity-stitches?upstream_semantic_type_id=${encoded}`,
      title:
        "View L8 entity-stitch rows anchored on this semantic type",
    });
  }
  if (typeof qualityCount === "number" && qualityCount > 0) {
    chips.push({
      testId: "quality",
      label: `↪ ${qualityCount} quality check${
        qualityCount === 1 ? "" : "s"
      } via L7`,
      count: qualityCount,
      href: `/lake/quality?upstream_semantic_type_id=${encoded}`,
      title:
        "View L7 quality-check rows derived from this semantic type",
    });
  }
  if (typeof impactCount === "number" && impactCount > 0) {
    chips.push({
      testId: "impact",
      label: `↪ ${impactCount} impact proposal${
        impactCount === 1 ? "" : "s"
      } via L4`,
      count: impactCount,
      href: `/lake/schema-impact?upstream_semantic_type_id=${encoded}`,
      title:
        "View L4 schema-evolution-impact rows derived from this semantic type",
    });
  }

  if (chips.length === 0) return null;

  return (
    <div
      data-testid={`semantic-type-downstream-cluster-${semanticTypeId}`}
      style={{
        display: "flex",
        flexDirection: "row",
        flexWrap: "wrap",
        gap: 6,
        alignItems: "center",
        marginTop: 2,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 9,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray, #7c7569)",
        }}
      >
        Downstream:
      </span>
      {chips.map((chip) => (
        <a
          key={chip.testId}
          href={chip.href}
          data-testid={`semantic-type-downstream-${chip.testId}-${semanticTypeId}`}
          className="wb-mono"
          title={chip.title}
          style={{
            fontSize: 10,
            letterSpacing: "0.06em",
            color: "var(--wb-color-sepia-warning-deep, #b6741c)",
            textDecoration: "none",
            cursor: "pointer",
            padding: "1px 6px",
            border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
            background: "var(--wb-color-paper, #f8f3e1)",
          }}
        >
          {chip.label}
        </a>
      ))}
    </div>
  );
}
