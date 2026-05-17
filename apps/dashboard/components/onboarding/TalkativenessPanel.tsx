"use client";

import { ChannelDial } from "../settings/ChannelDial";
import type { ChannelRow } from "../../lib/ledger-client.types";

export function TalkativenessPanel({ channels }: { channels: ChannelRow[] }) {
  return (
    <section
      data-testid="talkativeness-panel"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
        gap: 12,
      }}
    >
      {channels.slice(0, 6).map((c) => (
        <ChannelDial key={c.channelId} row={c} />
      ))}
    </section>
  );
}
