# OpenClaw image — upgrade log

Durable record of OpenClaw image-level dependency bumps. Each entry pairs
a date, the change, and the rationale. Bump deliberately — `npm install -g
openclaw@latest` is pinned only by build cache, so an unrelated rebuild can
silently drag in upstream changes.

When in doubt, follow the existing pattern: bump in a single commit, capture
the upstream version range exercised, and note any operator-visible behavior
deltas.

---

## 2026-05-06: WhatsApp plugin + Baileys deps

**Dockerfile additions:**

- `apk add --no-cache git ffmpeg` — alpine package install before any
  npm install lines that depend on these tools. Required by the WhatsApp
  transport:
  - `git` — Baileys (transitively pulled in by `@openclaw/whatsapp`)
    declares its libsignal dependency as a git URL. `node:24-alpine` ships
    without git, so `npm install -g @openclaw/whatsapp` fails at
    git-clone time without this.
  - `ffmpeg` — Baileys' media-message path shells out to ffmpeg for
    audio/video transcoding. Without it, runtime media handling
    silently drops transcodes.
- `npm install -g --no-audit --no-fund @openclaw/whatsapp@latest` — separate
  npm package; OpenClaw core does not bundle the WhatsApp transport. Reuses
  the retry/timeout npm config set immediately before the existing
  `openclaw@latest` install line; no new config required.

**Slack-only impact:** none. The `channels.whatsapp` config block is only
rendered at runtime when `WHATSAPP_ENABLED_<TENANT>=true` (see
`entrypoint.sh::render_whatsapp_block`). Slack-only deploys are byte-identical
in their config; only the image is heavier by ~git + ffmpeg + npm package.

**Bump pattern:** mirror the existing OpenClaw bump procedure when raising
either pin. `apk add` packages float with the alpine base (`node:24-alpine`);
bumping the base image upgrades both git and ffmpeg in lockstep. The
`@openclaw/whatsapp@latest` pin behavior matches `openclaw@latest` —
deliberately bump together when chasing upstream feature parity.

**Operator runbook:** `infra/openclaw/WHATSAPP_PAIRING.md` covers QR
pairing, credential persistence, and ToS posture for the Baileys-based
preview transport.
