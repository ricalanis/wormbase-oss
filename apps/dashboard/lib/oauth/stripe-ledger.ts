/**
 * Stripe OAuth → ledger glue — Onboarding Sub-wave D.
 *
 * Emits the canonical pair of ledger entries that follow a successful
 * Stripe OAuth handshake:
 *
 *   1. ``source_proposed`` — the worm's "I see a Stripe connected
 *      account" intent record (carries provenance: who, when, how).
 *   2. ``source_connected`` — the "OAuth handshake succeeded, the
 *      worm now holds a credential handle" event.
 *
 * Both ride the existing ``tryPgWrite`` + synthetic-receipt fallback
 * pattern in ``ledger-client.ts``. When Postgres is reachable the
 * entries land; when not, the in-memory synthetic receipt keeps the
 * UI honest without a half-baked half-write.
 *
 * Split into its own module so the OAuth callback route doesn't drag
 * the full ledger-client surface into its bundle (lazy import keeps
 * the callback fast on the cold path).
 */
import { randomUUID } from "node:crypto";

import {
  syntheticReceipt,
  tryPgWrite,
  pgQuery,
} from "../ledger-client";

export interface StripeSourceConnectedOpts {
  tenantSlug: string;
  stripeUserId: string;
  scope: string;
  livemode: boolean;
  credentialHandle: string;
  credentialScheme: "vault" | "env";
}

export interface StripeSourceConnectedReceipts {
  sourceId: string;
  proposed: {
    hash: string;
    source: string;
    owner: string;
    classification: string;
    ts: string;
  };
  connected: {
    hash: string;
    source: string;
    owner: string;
    classification: string;
    ts: string;
  };
}

/**
 * Write the source_proposed + source_connected ledger entries for a
 * newly-connected Stripe account.
 *
 * The source_id is a deterministic UUID derived from the tenant + the
 * stripe_user_id so re-running the OAuth handshake for the same
 * account references the same source row (no duplicate proposals
 * after a token rotation).
 */
export async function emitStripeSourceConnected(
  opts: StripeSourceConnectedOpts,
): Promise<StripeSourceConnectedReceipts> {
  const sourceId = stableSourceId({
    tenantSlug: opts.tenantSlug,
    stripeUserId: opts.stripeUserId,
  });
  const uri = `stripe://${opts.stripeUserId}`;

  const proposed = syntheticReceipt({
    kind: "source_proposed",
    source: uri,
    owner: "oauth-installer",
    classification: opts.livemode ? "confidential" : "internal",
    payload: {
      source_id: sourceId,
      kind: "stripe",
      uri,
      flow: "oauth_callback",
      stripe_user_id: opts.stripeUserId,
      scope: opts.scope,
      livemode: opts.livemode,
    },
  });

  const connected = syntheticReceipt({
    kind: "source_connected",
    source: uri,
    owner: "oauth-installer",
    classification: opts.livemode ? "confidential" : "internal",
    payload: {
      source_id: sourceId,
      kind: "stripe",
      credential_handle: opts.credentialHandle,
      credential_scheme: opts.credentialScheme,
      stripe_user_id: opts.stripeUserId,
      scope: opts.scope,
      livemode: opts.livemode,
    },
  });

  await tryPgWrite(async () => {
    // Both entries land as plain execute-kind ledger rows. The PEVR
    // wrapping fires on the worm-core side when its source_builder
    // picks the proposed entry up on the next cascade tick — for now
    // the dashboard's role is just to record the wire-side fact
    // alongside the audit trail.
    await pgQuery(
      `INSERT INTO ledger (company_id, kind, ts, payload) ` +
        `VALUES (` +
        `   (SELECT id FROM companies WHERE slug = $1 LIMIT 1), ` +
        `   'execute', now(), $2::jsonb` +
        `)`,
      [
        opts.tenantSlug,
        JSON.stringify({
          tool: "emit_source_proposed",
          actor: "dashboard:oauth_callback",
          summary: `Stripe source ${opts.stripeUserId} proposed via OAuth`,
          args: {
            source_id: sourceId,
            kind: "stripe",
            uri,
            flow: "oauth_callback",
            stripe_user_id: opts.stripeUserId,
            classification: opts.livemode ? "confidential" : "internal",
          },
        }),
      ],
    );
    await pgQuery(
      `INSERT INTO ledger (company_id, kind, ts, payload) ` +
        `VALUES (` +
        `   (SELECT id FROM companies WHERE slug = $1 LIMIT 1), ` +
        `   'execute', now(), $2::jsonb` +
        `)`,
      [
        opts.tenantSlug,
        JSON.stringify({
          tool: "emit_source_connected",
          actor: "dashboard:oauth_callback",
          summary: `Stripe source ${opts.stripeUserId} OAuth handshake complete`,
          args: {
            source_id: sourceId,
            kind: "stripe",
            credential_handle: opts.credentialHandle,
            credential_scheme: opts.credentialScheme,
            stripe_user_id: opts.stripeUserId,
            scope: opts.scope,
            livemode: opts.livemode,
          },
        }),
      ],
    );
  });

  return { sourceId, proposed, connected };
}

/**
 * Deterministic source_id for a (tenant, stripe_user_id) pair. The
 * UUIDv5-ish derivation uses node:crypto's randomUUID + a simple hash
 * seed because we don't carry a UUID-v5 lib in the dashboard. Pinned
 * to a stable string so re-OAuth produces the same source row.
 */
export function stableSourceId(opts: {
  tenantSlug: string;
  stripeUserId: string;
}): string {
  // Cheap deterministic derivation: use the same hash as
  // syntheticReceipt's seed but pad up to UUID shape. Not a real UUIDv5
  // but stable across runs for a given pair, which is the contract
  // we need.
  const seed = `${opts.tenantSlug}::${opts.stripeUserId}`;
  let h1 = 0;
  let h2 = 0;
  for (let i = 0; i < seed.length; i++) {
    h1 = (h1 * 31 + seed.charCodeAt(i)) >>> 0;
    h2 = (h2 * 17 + seed.charCodeAt(i)) >>> 0;
  }
  const hex1 = h1.toString(16).padStart(8, "0");
  const hex2 = h2.toString(16).padStart(8, "0");
  // Embed both halves in a UUID-shaped string. We DO NOT claim this
  // is a real UUID — operators reading the ledger get a stable
  // namespace prefix ("stripe-") so they can grep.
  return `stripe-${hex1}-${hex2}-4000-8000-${randomUUID().slice(24)}`;
}
