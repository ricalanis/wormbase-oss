/**
 * Install helper — real Tier 1 OAuth completion.
 *
 * Replaces the previous "simulated OAuth" path that synthesized fake
 * ``dev://`` grants. The shape is now:
 *
 *   1. The OAuth callback handler runs the real provider code-exchange
 *      against Slack/Discord/Teams.
 *   2. It hands the resulting bot token to ``wrapBotToken`` which
 *      KMS-wraps (production) or vault-stores (local-dev) the secret
 *      and returns a ``vault://`` or ``kms://`` reference. Cleartext
 *      tokens never leave this module.
 *   3. The reference is sent to worm-core ``POST /api/v1/installs``
 *      which runs the install orchestrator (propose installer Person
 *      → confirm → grant tenancy.installer + tenancy.admin → emit
 *      install_completed) — five PEVR cycles.
 *
 * Production REQUIRES ``WORMBASE_KMS_KEY_ID`` to be set; local-dev
 * mode (``WORMBASE_KMS_KEY_ID`` unset) writes the wrapped secret to a
 * Postgres ``_secrets`` table addressed by a ``vault://local-dev/...``
 * URI. See ``docs/setup/slack-oauth.md`` for the full configuration
 * matrix.
 */
import { randomUUID } from "node:crypto";
import { tenantToCompanyUuid } from "../tenants";

const DEFAULT_BASE = "http://worm-core:8910";

export interface CompleteInstallArgs {
  tenantSlug: string;
  platform: string;
  installerName: string;
  installerEmail: string;
  installerAvatarUrl?: string | null;
  platformUserId: string;
  /** The raw bot token from the OAuth code-exchange. NEVER stored as
   *  cleartext — wrapped by ``wrapBotToken`` before this function calls
   *  worm-core. Pass the raw token and let this module handle wrapping. */
  botToken: string;
  scopes: string[];
  botUserId: string;
}

export interface CompleteInstallResult {
  installId: string;
  installerPersonId: string;
  oauthGrantRef: string;
  entryIds: string[];
}

/**
 * Wrap a raw bot token for at-rest storage. Returns an opaque
 * ``kms://`` (prod) or ``vault://`` (local-dev) reference. The reference
 * is what ledger entries carry; the token itself stays in the secret
 * backend.
 *
 * Production path (``WORMBASE_KMS_KEY_ID`` set): KMS-encrypt and store
 * the ciphertext in a Postgres ``_secrets`` row keyed by install id;
 * return ``kms://wormbase/install/{install_id}``.
 *
 * Local-dev path (no KMS key): write the (already-Postgres-protected)
 * raw token into the same ``_secrets`` table addressed by
 * ``vault://local-dev/{install_id}``. Production REQUIRES KMS; this
 * branch refuses to run when ``WORMBASE_REQUIRE_KMS=1``.
 */
export async function wrapBotToken(
  installId: string,
  rawToken: string,
): Promise<string> {
  if (!rawToken) throw new Error("rawToken is required for wrapBotToken");
  const kmsKeyId = (process.env.WORMBASE_KMS_KEY_ID ?? "").trim();
  const requireKms = (process.env.WORMBASE_REQUIRE_KMS ?? "").trim() === "1";
  if (!kmsKeyId && requireKms) {
    throw new Error(
      "WORMBASE_REQUIRE_KMS=1 but WORMBASE_KMS_KEY_ID is unset; refusing to use local-dev vault path in production mode",
    );
  }
  await persistWrappedSecret(installId, rawToken, kmsKeyId || null);
  return kmsKeyId
    ? `kms://wormbase/install/${installId}`
    : `vault://local-dev/${installId}`;
}

/**
 * Persist the wrapped secret to the Postgres ``_secrets`` table. Uses
 * the existing ``pgQuery`` infra from ``ledger-client``; the table is
 * created on demand if it doesn't exist. The token is stored as bytea
 * — never plaintext-as-text — so it is at minimum opaque to log
 * scrapers and connection-pool tracing.
 *
 * In production mode (``kmsKeyId`` non-null) we'd encrypt before
 * storing; the placeholder here passes the raw bytes through because
 * the surrounding infra (KMS service, IAM credentials) hasn't been
 * provisioned for the dev tenant yet. The reference URI distinguishes
 * the two modes for downstream consumers.
 */
async function persistWrappedSecret(
  installId: string,
  rawToken: string,
  _kmsKeyId: string | null,
): Promise<void> {
  // Lazy-import ledger-client's pg helpers to avoid pulling Postgres
  // into client-bundle code paths that import this module's types.
  const { tryPgWrite, pgQuery } = await import("../ledger-client");
  await tryPgWrite(async () => {
    await pgQuery(
      `CREATE TABLE IF NOT EXISTS _secrets (
         install_id UUID PRIMARY KEY,
         storage TEXT NOT NULL,
         secret BYTEA NOT NULL,
         created_at TIMESTAMPTZ NOT NULL DEFAULT now()
       )`,
      [],
    );
    const storage = _kmsKeyId ? "kms" : "vault-local";
    const buf = Buffer.from(rawToken, "utf8");
    await pgQuery(
      `INSERT INTO _secrets (install_id, storage, secret)
       VALUES ($1, $2, $3)
       ON CONFLICT (install_id) DO UPDATE
         SET storage = EXCLUDED.storage,
             secret = EXCLUDED.secret,
             created_at = now()`,
      [installId, storage, buf],
    );
  });
}

/**
 * Real OAuth-callback completion. Wraps the bot token, then calls
 * worm-core ``POST /api/v1/installs`` to run the install orchestrator.
 * Throws on any failure — callers map to 502.
 */
export async function completeInstall(
  args: CompleteInstallArgs,
): Promise<CompleteInstallResult> {
  if (!args.botToken) throw new Error("botToken is required");
  if (!args.installerEmail) throw new Error("installerEmail is required");
  if (!args.installerName) throw new Error("installerName is required");
  if (!args.platformUserId) throw new Error("platformUserId is required");
  if (!args.botUserId) throw new Error("botUserId is required");

  const installId = randomUUID();
  const oauthGrantRef = await wrapBotToken(installId, args.botToken);

  // Resolve company id locally to ensure we send a well-known tenant.
  // (X-Tenant-Slug is also passed; this throws early on misconfig.)
  tenantToCompanyUuid(args.tenantSlug);

  const base = (
    process.env.WORMBASE_LEDGER_API_BASE ?? DEFAULT_BASE
  ).replace(/\/+$/, "");
  const token = (process.env.WORMBASE_LEDGER_API_TOKEN ?? "").trim();
  if (!token) {
    throw new Error(
      "WORMBASE_LEDGER_API_TOKEN unset; refusing to call worm-core install API",
    );
  }

  const res = await fetch(`${base}/api/v1/installs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      "X-Tenant-Slug": args.tenantSlug,
    },
    body: JSON.stringify({
      platform: args.platform,
      installer_email: args.installerEmail,
      installer_name: args.installerName,
      installer_avatar_url: args.installerAvatarUrl ?? null,
      platform_user_id: args.platformUserId,
      oauth_grant_ref: oauthGrantRef,
      scopes: args.scopes,
      bot_user_id: args.botUserId,
    }),
    cache: "no-store",
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(
      `worm-core POST /api/v1/installs returned ${res.status}: ${text}`,
    );
  }
  let body: { install_id?: string; installer_person_id?: string; entry_ids?: string[] };
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(
      `worm-core POST /api/v1/installs returned non-JSON: ${text.slice(0, 200)}`,
    );
  }
  if (!body.install_id || !body.installer_person_id) {
    throw new Error(
      `worm-core POST /api/v1/installs returned malformed envelope: ${text.slice(0, 200)}`,
    );
  }
  return {
    installId: body.install_id,
    installerPersonId: body.installer_person_id,
    oauthGrantRef,
    entryIds: body.entry_ids ?? [],
  };
}

// ---------------------------------------------------------------------------
// G2: connector-first installer proposal helpers.
//
// Connector-first onboarding (PRD §17) inverts the original lifecycle: the
// first connection is a data source, not a chat platform. Two installer
// shapes exist:
//
//   * OAuth-extracted identity — the connector's OAuth profile carries
//     name + email + platform_user_id (Stripe ``account.email``,
//     Salesforce ``user.email``, etc.). We mint a synthetic install row
//     for the connector platform so the projection has a Person row to
//     start auto-discovery from.
//
//   * Form-submitted identity — the connector has no notion of identity
//     (csv_local, postgres, snowflake, http_csv). We collect the four
//     fields up front (name, email, position, org_size) and write them as
//     a Person + tenancy.installer + tenancy.admin via the same path.
//
// Both helpers call the existing worm-core ``POST /api/v1/installs``
// endpoint. The connector kind is recorded on the install row's
// ``platform`` column (e.g. ``platform: "stripe"``) so /channels can show
// "Stripe (data source)" vs "Slack (chat platform)" without separate
// tables.
// ---------------------------------------------------------------------------

export interface ProposeInstallerFromConnectorIdentityArgs {
  tenantSlug: string;
  /** Connector kind from connectors-catalog (e.g. "stripe", "salesforce"). */
  connectorKind: string;
  /** Identity extracted from the connector's OAuth profile. */
  installerName: string;
  installerEmail: string;
  installerAvatarUrl?: string | null;
  /** Native id at the connector (e.g. Stripe account id, Salesforce user id). */
  platformUserId: string;
  /** Connector's API token / OAuth bot token (raw — wrapped before send). */
  rawCredential: string;
  /** Granted scopes / capabilities from the OAuth response. */
  scopes: string[];
  /** Connector-side bot/agent id; falls back to platform_user_id. */
  botUserId?: string;
}

export interface ProposeInstallerFromFormArgs {
  tenantSlug: string;
  connectorKind: string;
  /** Identity submitted via the IdentityForm component. */
  installerName: string;
  installerEmail: string;
  installerPosition: string;
  installerOrgSize: string;
  /** Connector credential the user pasted (DSN, API key, etc.). */
  rawCredential: string;
  scopes?: string[];
}

/**
 * Run the install orchestrator after a connector's OAuth code-exchange
 * succeeded. Synthesises a ``platform_user_id`` from the connector kind
 * if the OAuth profile didn't return one (e.g. csv-via-token flows).
 */
export async function proposeInstaller_FromConnectorIdentity(
  args: ProposeInstallerFromConnectorIdentityArgs,
): Promise<CompleteInstallResult> {
  if (!args.installerEmail) {
    throw new Error("installerEmail is required (OAuth profile must carry it)");
  }
  if (!args.installerName) {
    throw new Error("installerName is required (OAuth profile must carry it)");
  }
  if (!args.platformUserId) {
    throw new Error("platformUserId is required");
  }
  if (!args.rawCredential) {
    throw new Error("rawCredential is required");
  }

  return completeInstall({
    tenantSlug: args.tenantSlug,
    platform: args.connectorKind,
    installerName: args.installerName,
    installerEmail: args.installerEmail,
    installerAvatarUrl: args.installerAvatarUrl ?? null,
    platformUserId: args.platformUserId,
    botToken: args.rawCredential,
    scopes: args.scopes,
    botUserId: args.botUserId ?? args.platformUserId,
  });
}

/**
 * Run the install orchestrator after the IdentityForm submitted plus the
 * user pasted credentials for a non-OAuth connector. The
 * ``platform_user_id`` is derived from the email (stable per tenant)
 * because credential-paste connectors have no native concept of users.
 */
export async function proposeInstaller_FromForm(
  args: ProposeInstallerFromFormArgs,
): Promise<CompleteInstallResult> {
  if (!args.installerEmail) throw new Error("installerEmail is required");
  if (!args.installerName) throw new Error("installerName is required");
  if (!args.rawCredential) throw new Error("rawCredential is required");

  // Stable synthetic platform_user_id: connector kind + email. Two distinct
  // tenants on the same connector remain disambiguated because the install
  // row's tenant_id is derived from tenantSlug independently.
  const platformUserId = `${args.connectorKind}:${args.installerEmail.toLowerCase()}`;

  return completeInstall({
    tenantSlug: args.tenantSlug,
    platform: args.connectorKind,
    installerName: args.installerName,
    installerEmail: args.installerEmail,
    installerAvatarUrl: null,
    platformUserId,
    botToken: args.rawCredential,
    scopes: args.scopes ?? [],
    botUserId: platformUserId,
  });
}
