"use client";

import { useState } from "react";
import type { OntologySeed } from "../../lib/ledger-client.types";

export function OntologySeedsPanel({ seeds }: { seeds: OntologySeed[] }) {
  const [enabled, setEnabled] = useState<Record<string, boolean>>(
    Object.fromEntries(seeds.map((s) => [s.concept, s.enabled]))
  );

  return (
    <table
      data-testid="ontology-seeds-panel"
      style={{
        width: "100%",
        borderCollapse: "collapse",
        borderTop: "1px solid var(--wb-color-aged-ink)",
      }}
    >
      <thead>
        <tr style={{ borderBottom: "1px solid var(--wb-color-aged-ink)" }}>
          {["concept", "aliases", "default class", "keep?"].map((h) => (
            <th
              key={h}
              scope="col"
              style={{
                textAlign: "left",
                padding: "8px 10px",
                fontFamily: "var(--wb-font-serif)",
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: "0.16em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray)",
              }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {seeds.map((s, i) => (
          <tr
            key={s.concept}
            style={{
              background:
                i % 2 ? "var(--wb-color-paper-deep)" : "var(--wb-color-paper)",
            }}
          >
            <td style={{ padding: "8px 10px", fontFamily: "var(--wb-font-serif)" }}>
              {s.concept}
            </td>
            <td
              className="wb-mono"
              style={{
                padding: "8px 10px",
                fontSize: 11,
                color: "var(--wb-color-aged-ink-soft)",
              }}
            >
              {s.aliases.join(" · ")}
            </td>
            <td
              className="wb-mono"
              style={{ padding: "8px 10px", fontSize: 11 }}
            >
              {s.classificationDefault}
            </td>
            <td style={{ padding: "8px 10px" }}>
              <input
                type="checkbox"
                data-testid={`seed-${s.concept.toLowerCase()}`}
                checked={!!enabled[s.concept]}
                onChange={(e) =>
                  setEnabled((st) => ({
                    ...st,
                    [s.concept]: e.currentTarget.checked,
                  }))
                }
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
