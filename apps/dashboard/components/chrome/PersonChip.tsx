/**
 * PersonChip — header chip showing the current Person's name + position +
 * tenancy-role badge. Lives top-right in every authenticated layout.
 *
 * Visual language: matches the /people surface — wb-mono caps on the role
 * badge, serif name, square corners, CSS variable tokens, no Tailwind.
 * Role-tone mapping reuses `tenancyRoleTone` from
 * `components/people/_styles.ts` so the chip and the People roster stay in
 * lockstep.
 *
 * The dashboard's `(app)/` layout guarantees a non-null Person before this
 * chip renders — no installer/admin grant means the layout redirects to
 * `/onboarding` first. The optional `personId` prop is for renderers that
 * pass a Person they've already loaded (e.g. People drawers); when absent,
 * the chip renders inert (no link).
 */
import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import { chipStyle, tenancyRoleTone } from "../people/_styles";

export type PersonChipRole = "installer" | "admin" | "member" | "observer";

export interface PersonChipProps {
  person: { name: string; position: string | null };
  role: PersonChipRole;
  personId?: string | null;
}

const FRAME_STYLE: CSSProperties = {
  display: "inline-flex",
  alignItems: "baseline",
  gap: 8,
  textDecoration: "none",
  color: "inherit",
};

const NAME_STYLE: CSSProperties = {
  fontFamily: "var(--wb-font-serif)",
  fontWeight: 500,
  fontSize: 13,
  color: "var(--wb-color-aged-ink)",
};

const POSITION_STYLE: CSSProperties = {
  fontSize: 10,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--wb-color-hash-gray)",
};

export function PersonChip({ person, role, personId }: PersonChipProps) {
  const inner: ReactNode = (
    <>
      <span style={NAME_STYLE} data-testid="person-chip-name">
        {person.name}
      </span>
      {person.position ? (
        <span
          className="wb-mono"
          style={POSITION_STYLE}
          data-testid="person-chip-position"
        >
          {person.position}
        </span>
      ) : null}
      <span
        className="wb-mono"
        data-testid="role-badge"
        style={chipStyle(tenancyRoleTone(role))}
      >
        {role}
      </span>
    </>
  );

  if (personId) {
    return (
      <Link
        href={`/people/${personId}`}
        data-testid="person-chip"
        style={FRAME_STYLE}
      >
        {inner}
      </Link>
    );
  }
  return (
    <span data-testid="person-chip" style={FRAME_STYLE}>
      {inner}
    </span>
  );
}
