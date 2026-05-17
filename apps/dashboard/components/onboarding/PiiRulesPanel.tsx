"use client";

import { useState } from "react";
import type { PiiPattern } from "../../lib/ledger-client.types";

export function PiiRulesPanel({ patterns }: { patterns: PiiPattern[] }) {
  const [enabled, setEnabled] = useState<Record<string, boolean>>(
    Object.fromEntries(patterns.map((p) => [p.patternId, p.enabled]))
  );

  return (
    <table
      data-testid="pii-rules-panel"
      style={{
        width: "100%",
        borderCollapse: "collapse",
        borderTop: "1px solid var(--wb-color-aged-ink)",
      }}
    >
      <thead>
        <tr style={{ borderBottom: "1px solid var(--wb-color-aged-ink)" }}>
          {["pattern", "regex", "enabled"].map((h) => (
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
        {patterns.map((p, i) => (
          <tr
            key={p.patternId}
            data-testid={`pii-${p.patternId}`}
            style={{
              background:
                i % 2 ? "var(--wb-color-paper-deep)" : "var(--wb-color-paper)",
            }}
          >
            <td style={{ padding: "8px 10px", fontFamily: "var(--wb-font-serif)" }}>
              {p.label}
            </td>
            <td
              style={{
                padding: "8px 10px",
                fontFamily: "var(--wb-font-mono)",
                fontSize: 11,
                color: "var(--wb-color-aged-ink)",
                wordBreak: "break-all",
              }}
            >
              {p.regex}
            </td>
            <td style={{ padding: "8px 10px" }}>
              <label
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <input
                  type="checkbox"
                  data-testid={`pii-toggle-${p.patternId}`}
                  checked={!!enabled[p.patternId]}
                  onChange={(e) =>
                    setEnabled((s) => ({
                      ...s,
                      [p.patternId]: e.currentTarget.checked,
                    }))
                  }
                />
                <span
                  className="wb-mono"
                  style={{
                    fontSize: 10,
                    letterSpacing: "0.12em",
                    textTransform: "uppercase",
                    color: enabled[p.patternId]
                      ? "var(--wb-color-botanical-green-deep)"
                      : "var(--wb-color-hash-gray)",
                  }}
                >
                  {enabled[p.patternId] ? "enabled" : "disabled"}
                </span>
              </label>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
