"use client";

import { useState } from "react";
import type { PersonRow } from "../../lib/ledger-client.types";

export function DmRoutingPanel({ people }: { people: PersonRow[] }) {
  const [allow, setAllow] = useState<Set<string>>(
    new Set(people.slice(0, 1).map((p) => p.personId))
  );

  function toggle(id: string) {
    setAllow((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  }

  return (
    <section
      data-testid="dm-routing-panel"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 16,
      }}
    >
      <Column label="Allowlist" people={people.filter((p) => allow.has(p.personId))} onClick={toggle} accent="green" />
      <Column label="Denylist" people={people.filter((p) => !allow.has(p.personId))} onClick={toggle} accent="ink" />
    </section>
  );
}

function Column({
  label,
  people,
  onClick,
  accent,
}: {
  label: string;
  people: PersonRow[];
  onClick: (id: string) => void;
  accent: "green" | "ink";
}) {
  const color =
    accent === "green"
      ? "var(--wb-color-botanical-green)"
      : "var(--wb-color-aged-ink)";
  return (
    <div
      style={{
        border: `1px solid ${color}`,
        padding: 12,
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.16em",
          textTransform: "uppercase",
          color,
        }}
      >
        {label}
      </span>
      {people.map((p) => (
        <button
          key={p.personId}
          type="button"
          data-testid={`dm-${p.personId}`}
          onClick={() => onClick(p.personId)}
          style={{
            border: "1px solid var(--wb-color-paper-edge)",
            background: "var(--wb-color-paper)",
            borderRadius: 0,
            padding: "6px 8px",
            cursor: "pointer",
            fontFamily: "var(--wb-font-mono)",
            fontSize: 12,
            textAlign: "left",
          }}
        >
          @{p.displayName}
        </button>
      ))}
    </div>
  );
}
