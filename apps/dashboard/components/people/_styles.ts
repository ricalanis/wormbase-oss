/**
 * Shared style helpers for the /people surface (A5).
 *
 * Field-Notebook tokens only — square corners, serif headings, mono ids /
 * timestamps / status badges. No Tailwind, no SaaS pastels. Re-used across
 * PeopleRoster / PendingProposals / PersonDetailDrawer / InviteModal /
 * RoleGrantPanel.
 */
import type { CSSProperties } from "react";

/**
 * Rectangular chip — same visual language as the owned-domain chip on
 * the legacy PersonRow. Color pair switches by `tone`.
 */
export type ChipTone =
  | "neutral"
  | "green"
  | "sepia"
  | "ink"
  | "muted";

const TONE: Record<
  ChipTone,
  { fg: string; bg: string; border: string }
> = {
  neutral: {
    fg: "var(--wb-color-aged-ink)",
    bg: "var(--wb-color-paper)",
    border: "var(--wb-color-aged-ink)",
  },
  green: {
    fg: "var(--wb-color-botanical-green-deep)",
    bg: "var(--wb-color-botanical-green-soft)",
    border: "var(--wb-color-botanical-green)",
  },
  sepia: {
    fg: "var(--wb-color-sepia-warning-deep)",
    bg: "var(--wb-color-sepia-warning-soft)",
    border: "var(--wb-color-sepia-warning)",
  },
  ink: {
    fg: "var(--wb-color-paper)",
    bg: "var(--wb-color-aged-ink)",
    border: "var(--wb-color-aged-ink)",
  },
  muted: {
    fg: "var(--wb-color-hash-gray)",
    bg: "var(--wb-color-paper-deep)",
    border: "var(--wb-color-paper-edge)",
  },
};

export function chipStyle(tone: ChipTone = "neutral"): CSSProperties {
  const t = TONE[tone];
  return {
    display: "inline-flex",
    alignItems: "center",
    fontSize: 10,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    padding: "3px 8px",
    border: `1px solid ${t.border}`,
    color: t.fg,
    background: t.bg,
    borderRadius: 0,
  };
}

/** Tone for a tenancy role badge — installer/admin in green; member ink; observer muted. */
export function tenancyRoleTone(role: string | null): ChipTone {
  if (!role) return "muted";
  if (role === "installer" || role === "admin") return "green";
  if (role === "observer") return "muted";
  return "ink";
}

/** Tone for a Person status badge. */
export function statusTone(
  status: "proposed" | "active" | "archived" | string,
): ChipTone {
  if (status === "active") return "green";
  if (status === "proposed") return "sepia";
  if (status === "archived") return "muted";
  return "neutral";
}

/** "Plate" framing — table border + light card surround used throughout the surface. */
export const PLATE_RULE: CSSProperties = {
  borderTop: "1px solid var(--wb-color-aged-ink)",
};
