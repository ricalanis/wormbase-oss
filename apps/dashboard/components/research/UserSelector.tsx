"use client";
/**
 * UserSelector — pick a Person × Position pair to filter the per-user
 * research log.
 *
 * Uses a native <select> (no dependency on the design system Select since
 * the registry rows have a `data-testid` we want stable for tests).
 */

import type { PositionRegistryRow } from "../../lib/ledger-client.types";

export interface UserSelectorProps {
  registry: PositionRegistryRow[];
  selectedPersonId: string | null;
  onSelect: (personId: string | null) => void;
}

export function UserSelector({
  registry,
  selectedPersonId,
  onSelect,
}: UserSelectorProps) {
  return (
    <div
      data-testid="user-selector"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <label
        htmlFor="research-user-select"
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        viewer
      </label>
      {registry.length === 0 ? (
        <p
          data-testid="user-selector-empty"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          No people registered yet — finish onboarding to seed Step 5.
        </p>
      ) : (
        <select
          id="research-user-select"
          data-testid="user-select"
          value={selectedPersonId ?? "__all"}
          onChange={(e) =>
            onSelect(e.target.value === "__all" ? null : e.target.value)
          }
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-md)",
            padding: "8px 12px",
            border: "1px solid var(--wb-color-rule-line)",
            background: "var(--wb-color-paper)",
            color: "var(--wb-color-aged-ink)",
            maxWidth: 360,
          }}
        >
          <option value="__all">All registered viewers</option>
          {registry.map((r) => (
            <option key={r.personId} value={r.personId}>
              {r.displayName} · {r.position}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
