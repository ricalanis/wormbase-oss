/**
 * EntityKindChip — colored chip for the 8-value ``EntityKind`` enum
 * surfaced on /lake/entity-stitches rows (L8 Sub-wave D, 2026-06-07).
 *
 * The 8 entity_kind values get distinct, accessible chip colors drawn
 * from the existing classification-chip / lineage-chip palette
 * vocabulary (paper / archive-blue / botanical-green / sepia-warning /
 * alarm-red / hash-gray families). The ``other`` chip is intentionally
 * muted/slate so it reads as "unclassified" — per Sub-wave C handoff
 * concern #4, NameMatch's fuzzy-name path always emits ``other`` (the
 * bare name has no entity-class signal), so the muted tone keeps the
 * "I'm just a name match" rows visually de-emphasised relative to the
 * semantic-type-anchored kinds.
 *
 * Color discipline (paired with the L6 ColumnClassificationRow palette):
 *   * person        → archive-blue (people are the canonical entity)
 *   * organization  → botanical-green-deep variant (org/group hue)
 *   * transaction   → botanical-green (money/financial events)
 *   * product       → sepia-warning (product/inventory hue)
 *   * event         → indigo-ish (time-bound events, distinct from
 *                     transaction's money-green)
 *   * location      → teal (geographic/spatial hue)
 *   * session       → pink-rose (ephemeral session/connection hue)
 *   * other         → slate (muted "unclassified" tier)
 */

"use client";

import type { EntityKind } from "../../lib/entity-stitches";

export interface EntityKindChipProps {
  kind: EntityKind;
  /** Test-id suffix so multiple chips on a page each get a unique
   *  ``data-testid``. */
  testIdSuffix: string;
}

interface ChipColors {
  bg: string;
  fg: string;
  border: string;
}

/**
 * Per-kind visual signature for the 8-value enum. Per the surface
 * spec, ``other`` is the "unclassified" tier — slate / muted gray so
 * fuzzy-name proposals visually read as lower-signal than the
 * semantic-type-anchored kinds.
 */
function kindChipStyle(kind: EntityKind): ChipColors {
  switch (kind) {
    case "person":
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-archive-blue-deep, #2c5f7c)",
        border: "var(--wb-color-archive-blue-deep, #2c5f7c)",
      };
    case "organization":
      // Distinct purple-ish — orgs are people-collectives.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#5b3a8a",
        border: "#5b3a8a",
      };
    case "transaction":
      // Money/financial green.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-botanical-green-deep, #2d5d3a)",
        border: "var(--wb-color-botanical-green-deep, #2d5d3a)",
      };
    case "product":
      // Sepia/amber for product/inventory.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "var(--wb-color-sepia-warning-deep, #b6741c)",
        border: "var(--wb-color-sepia-warning-deep, #b6741c)",
      };
    case "event":
      // Indigo — temporal events, distinct from transaction green.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#3b3f8c",
        border: "#3b3f8c",
      };
    case "location":
      // Teal — geographic/spatial hue.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#1e6f72",
        border: "#1e6f72",
      };
    case "session":
      // Pink-rose — ephemeral session/connection hue.
      return {
        bg: "var(--wb-color-paper, #f8f3e1)",
        fg: "#a8366a",
        border: "#a8366a",
      };
    case "other":
      // Muted slate — the "unclassified" tier (per handoff concern #4,
      // NameMatch fuzzy-name always lands here). Intentionally low-
      // contrast so fuzzy-name rows visually read as lower-signal than
      // the semantic-type-anchored kinds.
      return {
        bg: "var(--wb-color-paper-deep, #f4eedb)",
        fg: "var(--wb-color-hash-gray, #7c7569)",
        border: "var(--wb-color-paper-edge, #d8d2c2)",
      };
  }
}

export function EntityKindChip({
  kind,
  testIdSuffix,
}: EntityKindChipProps): JSX.Element {
  const c = kindChipStyle(kind);
  const isUnclassified = kind === "other";
  return (
    <span
      data-testid={`entity-stitch-kind-chip-${testIdSuffix}`}
      data-kind={kind}
      data-unclassified={isUnclassified ? "true" : "false"}
      aria-label={
        isUnclassified ? `entity_kind=${kind} (unclassified)` : `entity_kind=${kind}`
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
        // Slightly de-emphasised typography for the "other" tier — per
        // Sub-wave C handoff concern #4.
        opacity: isUnclassified ? 0.85 : 1.0,
      }}
    >
      {kind}
    </span>
  );
}
