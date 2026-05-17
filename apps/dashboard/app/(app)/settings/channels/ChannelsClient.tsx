"use client";

import { ChannelDial } from "../../../../components/settings/ChannelDial";
import type {
  ChannelRow,
  Talkativeness,
} from "../../../../lib/ledger-client.types";

export function ChannelsClient({ channels }: { channels: ChannelRow[] }) {
  async function handleChange(channelId: string, value: Talkativeness) {
    await fetch("/api/channels/talkativeness", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ channelId, talkativeness: value }),
    });
  }

  return (
    <section
      data-testid="channels-list"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
        gap: 12,
      }}
    >
      {channels.map((c) => (
        <ChannelDial key={c.channelId} row={c} onChange={handleChange} />
      ))}
    </section>
  );
}
