/**
 * Rule — explicit horizontal rule conventions.
 *
 * Phase 1B locks down four rule semantics. By componentizing them we make
 * the design grammar legible at the JSX level (no "what does this border do"
 * archaeology when reading code six months from now).
 *
 * Variants:
 *  - thin    — paperEdge, section separation
 *  - strong  — 1px ink, primary boundary
 *  - double  — 3px double ink, heading divider, Royal-Society reference
 *  - dashed  — provisional / pending ledger entries
 */

import type { CSSProperties } from "react";

export type RuleVariant = "thin" | "strong" | "double" | "dashed";

export interface RuleProps {
  variant?: RuleVariant;
  /** Optional inline style overrides (margin etc.). */
  style?: CSSProperties;
  /** Optional aria-label. By default the rule is decorative (aria-hidden). */
  label?: string;
}

const RULE_BORDER: Record<RuleVariant, string> = {
  thin: "1px solid var(--wb-color-paper-edge)",
  strong: "1px solid var(--wb-color-aged-ink)",
  double: "3px double var(--wb-color-aged-ink)",
  dashed: "1px dashed var(--wb-color-hash-gray)",
};

export function Rule({ variant = "thin", style, label }: RuleProps) {
  const heightHint = variant === "double" ? 3 : 1;
  return (
    <div
      role={label ? "separator" : undefined}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      data-rule={variant}
      style={{
        height: 0,
        borderTop: RULE_BORDER[variant],
        marginTop: heightHint > 1 ? -heightHint : 0,
        ...style,
      }}
    />
  );
}

Rule.displayName = "Rule";
