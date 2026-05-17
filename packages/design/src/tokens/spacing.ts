/**
 * Field Notebook spacing — 4px base grid.
 *
 * Scale: 2 / 4 / 6 / 8 / 12 / 16 / 24 / 32 / 48 / 64 (px).
 * Dense brutalist horizontal grids + generous vertical breathing room.
 */
export const spacing = {
  "0": "0px",
  "0.5": "2px",
  "1": "4px",
  "1.5": "6px",
  "2": "8px",
  "3": "12px",
  "4": "16px",
  "6": "24px",
  "8": "32px",
  "12": "48px",
  "16": "64px",
} as const;

export const spacingBase = 4;

export type SpacingToken = keyof typeof spacing;
