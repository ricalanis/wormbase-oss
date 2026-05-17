# Channel adapters — capability honesty and promotion bar

Every `ChannelAdapter` declares two capability-honesty fields alongside
its `platform` and `capability`:

- `status: AdapterStatus` — one of `"production"`, `"preview"`,
  `"coming_soon"`.
- `status_note: str` — a short user-facing explanation (≤ 120 chars
  preferred, ≤ 200 enforced) shown verbatim in the dashboard's
  channels tab.

The dashboard's TypeScript counterpart is
`apps/dashboard/lib/platform-status.ts`, which carries the same fields
plus an `envHint` describing the OAuth env vars an admin needs to set
to enable the platform.

## The three statuses

| Status | Definition | Channels-tab UX |
|---|---|---|
| `production` | Every method (`authenticate`, `install`, `listen`, `send`, `file_upload`, `list_workspace_members`) is wired against the real platform. | Solid-color "Connect <platform>" button. Click → real OAuth flow at `/onboarding/oauth/<platform>/start`. |
| `preview` | `install` + `listen` are real (admins can connect; the worm will lurk and ingest); `send` and `file_upload` may be skeletal. | Outline "Connect <platform>" button + "Preview" badge. Click still routes to the OAuth flow — but installed cards show a banner explaining the worm lurks but won't yet post. |
| `coming_soon` | Skeleton only. Not yet usable end-to-end. | Greyed-out button + "Coming soon" badge. Click → explanatory modal; **no OAuth flow.** |

## Why "preview" is a real category

Discord and Teams adapters in this repo are stub-but-real: their
`authenticate` validates a real bot token, `install` returns a
shaped `InstallRecord`, and `listen` is a survivable async iterator.
What's missing is the platform-specific bot wiring for sending. That
distinction matters: an admin who connects Discord today gets a
worm that lurks the channels (real ingest into the conversation lake)
even though it can't yet reply. That is a **real, if limited,
product step** — not a fake.

Without the `preview` tier, we would either lie about Discord
(claiming it works) or hide it (denying its real value). Capability
honesty needs three tiers, not two.

## Promotion bar

| Promotion | Bar |
|---|---|
| Skeleton → Preview | `install` + `listen` are wired against the real platform; one integration test against a recorded fixture; bot tokens validated end-to-end. |
| Preview → Production | All methods wired; `send` + `file_upload` posting against the real platform; integration tests gated behind CI secrets; the `status_note` no longer mentions skeletal pieces. |

## Day-one inventory (2026-04-26)

| Platform | Status | Notes |
|---|---|---|
| `slack` | production | Full ingest, send, file_upload, DM, install. |
| `discord` | preview | Install + listen real; send + file_upload skeletal. |
| `teams` | preview | Install + listen real; send + file_upload skeletal. |
| `signal` | coming_soon | signal-cli bridge design in v1.5. |
| `whatsapp` | coming_soon | WhatsApp Business adapter in v1.5. |

## Production-only OAuth

Per the onboarding-production-only feedback principle: a button must
NEVER silently route to a synthesized OAuth grant when env vars
aren't configured. `ConnectPlatformButtons` reads server-resolved
`envState` and renders a "Configure: $envHint" disabled state for
production / preview platforms whose OAuth env tokens are missing.
Only platforms with real env config will start an OAuth flow. Real
grants only.

## Cross-language sync

When promoting an adapter's status, update **both** sides in the same
change:

- Python: `packages/channel-adapters/src/wormbase_channel_adapters/<platform>.py`
- TypeScript: `apps/dashboard/lib/platform-status.ts`

Parametrized tests at
`packages/channel-adapters/tests/test_adapter_status.py` and
`apps/dashboard/tests/lib/platform-status.test.ts` pin the expected
status per platform; the tests fail loudly on drift.
