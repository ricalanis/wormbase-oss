# ADR-0001: Listener-shaped channel adapter (OpenClaw over responder-shaped Hermes)

**Status:** Accepted
**Date:** 2026-04-27

## Context

WormBase's first architectural commitment is that the worm is a lurker by
default: every message in every connected channel is captured, regardless of
whether the worm intends to respond. The capture path feeds the conversation
lake (bronze tier), the relevance gate, governance audits, and downstream
process / identity / research worms. Speech is a separate, gated act.

The channel-adapter layer needed a wire-protocol provider that could deliver
this listener semantics across Slack (day one) and additional platforms over
time. Two production-grade open-source options were available: OpenClaw — a
multi-platform gateway with a global event log that captures every wire event
regardless of bot engagement — and Hermes, an agent-framework gateway with a
hook system for `agent:start` / `session:start` lifecycle events.

The initial intuition favored Hermes for its Python-native runtime, modern
hook surface, and the ability to drop the bonjour-mDNS workaround that
OpenClaw required.

## Decision

WormBase routes inbound channel traffic through a **listener-shaped channel
adapter built on OpenClaw**. The channel-adapter is the only path that writes
`channel_adapter.emit_chat_received` entries to the ledger; every other
subsystem reads from that ledger stream.

Hermes was empirically evaluated and rejected. The Hermes hook system is
**responder-shaped**: its `agent:start` and `session:start` events only fire
after the gateway decides to engage the agent loop with a message (auth,
allowlist, target-channel routing, mention/DM gating). There is no
`gateway:inbound_message` event, no documented Python plugin extension point
for `BaseChannelPlatform._run_processing_hook`, and no "lurker mode" flag
that emits every received event into a configurable sink. Silent chat in a
non-target channel never reaches the agent loop at all — the architecturally
opposite shape from what WormBase requires.

Alternative paths considered and rejected:

- **Custom Hermes plugin** that monkey-patches `_run_processing_hook` to
  emit file-based `inbound_message` events. Feasible at ~2-3 days of effort
  but creates a fork-tracking maintenance burden — each Hermes release
  potentially breaks the patch.
- **Mixed-mode (Hermes outbound, OpenClaw inbound)**. Sidesteps the listener
  problem but defeats every stated payoff of the migration (still maintains
  the bonjour workaround, still maintains the dual-app pattern). Strictly
  worse than keeping OpenClaw end-to-end.

## Consequences

**Positive:**

- Capture-by-default is upheld at the wire layer. Every chat-received entry
  lands in the ledger regardless of whether the worm engages.
- The channel-adapter is a thin (~200 LOC) shim that subscribes to OpenClaw
  events, normalizes them into ledger entries tagged with `domain_id` /
  `classification` / `channel_id`, and writes outbound messages back through
  OpenClaw.
- Multi-platform coverage (Slack, WhatsApp, Discord, Teams, Matrix, IRC,
  Google Chat, ...) is inherited from OpenClaw without custom adapter code.
- The principle "listen-for-ingest is always on; speak is always gated" is
  enforceable at an architectural layer, not just at a policy layer.

**Negative:**

- OpenClaw's bonjour-mDNS quirk remains a known wart, mitigated by an
  environment variable workaround documented in deployment notes.
- WormBase tracks the OpenClaw release cycle for its own platform expansions
  and bug fixes, rather than the Hermes ecosystem.
- The decision is platform-specific: any future channel framework adoption
  must be re-evaluated against the listener-shaped requirement, not assumed
  to fit.

**Neutral:**

- A small `Channel Ledger Adapter` (~200 LOC) is the only wire-protocol code
  WormBase maintains; everything platform-specific lives in OpenClaw.
- Hermes can be revisited if it ships an `inbound_message` hook, a documented
  plugin extension point, or a "lurker mode" config flag — none of which
  exist in v0.11.0.

## Cross-references

- Related ADRs: ADR-0004 (chat worm decomposition consumes the listener
  contract), ADR-0007 (identity discovery fires on captured wire events).
- Architecture: `ARCHITECTURE.md` §4 ("The ChannelAdapter contract — chat
  platforms are pluggable").
