// WormBase silent-mode plugin for OpenClaw.
//
// Closes the 6th egress surface from the silent-mode design
// (docs/superpowers/specs/2026-05-18-silent-mode-design.md §"The egress
// gates"). When WORMBASE_SILENT_MODE is truthy the plugin claims every
// available outbound hook so openclaw's built-in default agent (and
// any other path that would emit a chat send) cannot reach the
// channel adapter's send call. Inbound flow is unchanged: Baileys /
// socket → openclaw runtime log → channel-adapter → ledger; worm-core
// reactivities still fire on `chat_received` entries.
//
// Why a shotgun set of hooks: `before_agent_reply` registers cleanly
// (verified live) but the handler doesn't appear to fire from our
// plugin's sandbox — likely because the hook runner is conversation-
// scoped and the plugin instance lifecycle resets per message
// (we see "loading wormbase-silent-mode" once per inbound). The
// outbound-side hooks (`message_sending`, `before_message_write`,
// `before_dispatch`, `reply_dispatch`) live in a different category
// (`PluginHookName` enum, hook-types.d.ts) and are run by the global
// hook runner from the channel adapter's send boundary — registering
// at every plausible chokepoint maximizes the chance one of them
// runs and claims before Baileys actually sends.

import { definePluginEntry } from "openclaw/plugin-sdk/core";

const TRUTHY = new Set(["1", "true", "yes", "on"]);

function silentModeEnabled() {
  const raw = String(process.env.WORMBASE_SILENT_MODE ?? "").trim().toLowerCase();
  return TRUTHY.has(raw);
}

// Outbound-only chokepoints. Crucial: do NOT claim `before_dispatch`
// or `before_agent_run`/`before_agent_start`. Those fire on the
// INBOUND path and a claim there short-circuits the agent session
// lifecycle, which kills `chat_received` emission via the channel-
// adapter's session-JSONL tailer (regression caught live 2026-05-21:
// a DM produced HANDLER_FIRING for before_dispatch + zero outbound +
// zero chat_received). The hooks below all fire AFTER the agent has
// processed the inbound and is about to emit a reply, so claiming
// them silences outbound while preserving the inbound audit trail.
const CLAIMING_HOOKS = [
  "before_agent_reply",
  "reply_dispatch",
  "message_sending",
  "before_message_write",
];

export default definePluginEntry({
  id: "wormbase-silent-mode",
  name: "WormBase Silent Mode",
  description:
    "Claims every outbound hook when WORMBASE_SILENT_MODE is truthy so openclaw's default agent never sends.",
  register: (api) => {
    const enabled = silentModeEnabled();
    api.logger.info(
      `wormbase-silent-mode: register fired, silent_mode=${enabled}`,
    );
    if (!enabled) return;

    // Direct stdout write so we can see hook fires even if the
    // plugin's api.logger context is stale by the time the handler
    // runs (suspected cause of the prior silent-fire bug — handler
    // appeared registered but logs from inside it never surfaced).
    const stamp = () => new Date().toISOString();
    const directLog = (msg) => {
      try {
        process.stdout.write(`[wormbase-silent-mode] ${stamp()} ${msg}\n`);
      } catch (_) {
        // never let logging block the gate
      }
    };

    // CRITICAL: use `api.on(name, handler, opts)`, NOT
    // `api.registerHook(name, handler, opts)`. The legacy
    // `registerHook` path lands in `registry.hooks` + an internal
    // fire-and-forget bus that does NOT honor `{ handled: true }`
    // returns. Only `api.on` populates `registry.typedHooks`, which
    // is the list `runClaimingHook` (hook-runner-global-…js) reads.
    // Discovered by reading loader-CZB9kQVT.js lines 3616-3686 +
    // hook-runner-global-D1vhzHUy.js lines 149/385 — see the
    // gate-6 known-issue note.
    for (const hookName of CLAIMING_HOOKS) {
      const handler = (event, ctx) => {
        directLog(
          `HANDLER_FIRING hook=${hookName} sessionKey=${ctx?.sessionKey ?? "?"} channelId=${ctx?.channelId ?? "?"}`,
        );
        return {
          handled: true,
          reason: "wormbase_silent_mode",
          reply: { text: "" },
        };
      };
      try {
        // `priority: 1000` so we beat any built-in default handler
        // that might also register for these hooks.
        api.on(hookName, handler, { priority: 1000 });
        api.logger.info(`wormbase-silent-mode: registered ${hookName} via api.on`);
      } catch (err) {
        api.logger.warn(
          `wormbase-silent-mode: api.on(${hookName}) failed: ${err?.message ?? err}`,
        );
      }
    }
  },
});
