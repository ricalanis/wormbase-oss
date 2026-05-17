"use client";

import { useState } from "react";
import { Receipt } from "../../lib/receipts";
import type {
  Talkativeness,
  ChannelRow as ChannelRowModel,
} from "../../lib/ledger-client.types";
import { formatChannelDisplay } from "../../lib/whatsapp-display";

const SEGMENTS: Talkativeness[] = ["lurker", "responsive", "proactive"];

export function ChannelDial({
  row,
  onChange,
}: {
  row: ChannelRowModel;
  onChange?: (channelId: string, value: Talkativeness) => Promise<void>;
}) {
  const [value, setValue] = useState<Talkativeness>(row.talkativeness);
  const [pendingHash, setPendingHash] = useState<string | null>(null);

  async function pick(v: Talkativeness) {
    if (v === value) return;
    setValue(v);
    if (onChange) {
      try {
        await onChange(row.channelId, v);
        setPendingHash("just-saved");
      } catch {
        // swallow — toast comes from parent
      }
    }
  }

  // Phase D1 — WhatsApp jids aren't human-friendly. Project the raw
  // channel_id into a display label (DM → +E.164, group → truncated id
  // or registered name when present). Slack channel names pass through
  // unchanged when registeredName is set; otherwise the channel_id
  // surfaces as the label, exactly as before.
  const display = formatChannelDisplay(
    row.channelId,
    row.platform,
    row.name && row.name !== row.channelId ? row.name : null,
  );

  return (
    <article
      data-testid={`channel-dial-${row.channelId}`}
      data-platform={row.platform ?? "unknown"}
      style={{
        border: "1px solid var(--wb-color-paper-edge)",
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        background: "var(--wb-color-paper)",
      }}
    >
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 13,
            color: "var(--wb-color-aged-ink)",
          }}
        >
          {display.label}
        </span>
        <div style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
          {row.platform === "whatsapp" ? (
            <span
              className="wb-mono"
              data-testid={`channel-platform-${row.channelId}`}
              style={{
                fontSize: 9,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--wb-color-sepia-warning-deep)",
                border: "1px solid var(--wb-color-sepia-warning-deep)",
                padding: "1px 5px",
              }}
              title={`WhatsApp · ${display.hint}`}
            >
              {display.hint}
            </span>
          ) : null}
          {pendingHash ? (
            <span
              className="wb-mono"
              style={{
                fontSize: 10,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "var(--wb-color-botanical-green-deep)",
              }}
            >
              saved · ledger
            </span>
          ) : null}
        </div>
      </header>
      {row.lastSeenAt ? (
        <span
          className="wb-mono"
          data-testid={`channel-last-seen-${row.channelId}`}
          style={{
            fontSize: 10,
            color: "var(--wb-color-hash-gray)",
            letterSpacing: "0.04em",
          }}
        >
          last seen · {row.lastSeenAt}
        </span>
      ) : null}
      <div
        role="group"
        aria-label={`Talkativeness for ${row.name}`}
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          border: "1px solid var(--wb-color-aged-ink)",
        }}
      >
        {SEGMENTS.map((s) => {
          const active = s === value;
          return (
            <button
              key={s}
              type="button"
              data-testid={`channel-${row.channelId}-${s}`}
              data-active={active ? "true" : "false"}
              aria-pressed={active}
              onClick={() => pick(s)}
              style={{
                padding: "8px 6px",
                border: "none",
                borderRadius: 0,
                cursor: "pointer",
                background: active
                  ? "var(--wb-color-botanical-green-soft)"
                  : "transparent",
                fontFamily: "var(--wb-font-mono)",
                fontSize: 11,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: active
                  ? "var(--wb-color-botanical-green-deep)"
                  : "var(--wb-color-aged-ink-soft)",
                outline: active ? "1px solid var(--wb-color-sepia-warning)" : "none",
                outlineOffset: -1,
              }}
            >
              {s}
            </button>
          );
        })}
      </div>
      <Receipt
        hash={row.receipt.hash}
        source={row.receipt.source}
        owner={row.receipt.owner}
        classification={row.receipt.classification}
        compact
      />
    </article>
  );
}
