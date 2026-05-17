/**
 * Field Notebook typography.
 *
 * Serif for narrative UI — editorial weight, evokes scientific publishing.
 * Mono is SEMANTIC — it marks "this is ledger." Used for hashes, entry IDs,
 * SQL, schema names, attribution metadata. Never decorative.
 *
 * Font choices:
 * - Tiempos is commercial-only — use Source Serif 4 (Google Fonts) as
 *   the production-safe fallback closest to Tiempos' editorial feel.
 * - Berkeley Mono / Tuesday Mono are commercial — use JetBrains Mono
 *   (Google Fonts) as the production-safe fallback.
 *
 * Type scale: 12, 14, 16, 20, 25, 32, 40, 51, 64 — ratio 1.25, base 16.
 * (Computed 16 * 1.25^n, rounded.)
 */
export const typography = {
  fontFamily: {
    serif:
      '"Tiempos Text", "Source Serif 4", "Source Serif Pro", "GT Super", "Lora", Georgia, serif',
    mono: '"Berkeley Mono", "Tuesday Mono", "JetBrains Mono", "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
  },
  scale: {
    xs: "12px",
    sm: "14px",
    base: "16px",
    md: "20px",
    lg: "25px",
    xl: "32px",
    "2xl": "40px",
    "3xl": "51px",
    "4xl": "64px",
  },
  ratio: 1.25,
  weight: {
    regular: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },
  leading: {
    tight: 1.15,
    snug: 1.3,
    normal: 1.5,
    relaxed: 1.65,
  },
  tracking: {
    tight: "-0.01em",
    normal: "0",
    wide: "0.04em",
    wider: "0.08em",
  },
} as const;

export type FontFamilyToken = keyof typeof typography.fontFamily;
export type ScaleToken = keyof typeof typography.scale;
