/**
 * Field Notebook palette — WormBase.
 *
 * Institutional-organic hybrid, not SaaS-pastel. See PRD §4.4.
 *
 * Phase 1A established paper / aged-ink / botanical-green / sepia / hash-gray /
 * rule-line / highlight. Phase 1B adds tonal layers (paperDeep, paperEdge,
 * inkSoft, inkFaint, greenDeep, greenSoft, sepiaSoft) so cards, hover states,
 * receipts, and classification washes have explicit token-level support.
 *
 * - paper: warm off-white base (the journal page)
 * - paperDeep: section fills, hover (darker than paper but still warm)
 * - paperEdge: thin rule lines / borders / faint dividers
 * - agedInk: aged charcoal — primary ink for narrative text
 * - agedInkSoft: secondary text
 * - inkFaint: tertiary text — timestamps, ghost meta
 * - botanicalGreen: institutional accent, used for primary actions
 * - botanicalGreenDeep: pressed / confirmed
 * - botanicalGreenSoft: classification wash for "internal" / verified
 * - sepiaWarning: warning-only (gate fires, PII blocks, policy violations)
 * - sepiaWarningSoft: warning wash (PII / restricted classification)
 * - hashGray: metadata / lower-hierarchy text
 * - ruleLine: legacy alias for paperEdge — kept for back-compat
 * - highlight: subtle highlight wash (paperEdge tone)
 */
export const colors = {
  // base canvas + tonal layers
  paper: "#FAF7F0",
  paperDeep: "#F2ECDE",
  paperEdge: "#E8E0CC",

  // ink ladder
  agedInk: "#2A2A2A",
  agedInkSoft: "#4A4842",
  inkFaint: "#A8A49A",

  // botanical
  botanicalGreen: "#2C5F3E",
  botanicalGreenDeep: "#1F4A2E",
  botanicalGreenSoft: "#E6EDE4",

  // sepia (warnings)
  sepiaWarning: "#B8603C",
  sepiaWarningDeep: "#8E4525",
  sepiaWarningSoft: "#F3E4DA",

  // metadata
  hashGray: "#7A7A7A",
  hashGraySoft: "#9B9B9B",

  // back-compat aliases (Phase 1A names that downstream code already uses)
  ruleLine: "#E8E0CC",
  highlight: "#E8E2CC",
} as const;

export type ColorToken = keyof typeof colors;

/**
 * Exposes tokens as CSS custom properties. Import in a global stylesheet:
 * `:root { ...colorsCssVariables }`.
 */
export const colorsCssVariables: Record<string, string> = Object.fromEntries(
  Object.entries(colors).map(([name, value]) => [
    `--wb-color-${kebab(name)}`,
    value,
  ])
);

function kebab(s: string): string {
  return s.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);
}
