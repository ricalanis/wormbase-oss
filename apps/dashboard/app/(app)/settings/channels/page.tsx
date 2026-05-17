/**
 * Legacy /settings/channels — redirects to /channels (D3 promoted the
 * surface to a top-level tab). The ChannelsClient component this page
 * used to wrap is still imported by the new /channels page via
 * components/channels/ChannelRoster.tsx, so the per-channel
 * talkativeness write path is unchanged.
 */
import { redirect } from "next/navigation";

export const metadata = { title: "WormBase · Channels" };

export default function ChannelsRedirect(): never {
  redirect("/channels");
}
