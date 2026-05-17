/**
 * Server-only UUIDv5 derivation for new tenant slugs.
 *
 * Mirrors `apps/channel-adapter/src/wormbase_channel_adapter/tenant.py`
 * and `apps/worm-core/src/wormbase_core/service.py` — every consumer
 * derives the same UUID by computing UUIDv5 of the slug under the same
 * namespace.
 *
 * **Do not import this from a Client Component** (it pulls `node:crypto`).
 * The dashboard's runtime tenant list is precomputed in `./tenants.ts`;
 * this module exists for admin tooling, tests, and the
 * `apps/dashboard/scripts/derive-tenant-uuid.mjs` helper.
 */
import { createHash } from "node:crypto";

import { WORMBASE_TENANT_NAMESPACE } from "./tenants";

/** Compute UUIDv5 (SHA-1, RFC 4122 §4.3) for a name under a namespace. */
export function uuidv5(name: string, namespace: string): string {
  const nsBytes = Buffer.from(namespace.replace(/-/g, ""), "hex");
  if (nsBytes.length !== 16) {
    throw new Error(`invalid namespace UUID: ${namespace}`);
  }
  const h = createHash("sha1");
  h.update(nsBytes);
  h.update(name);
  const buf = h.digest();
  // Set version (5) and variant bits per RFC 4122.
  buf[6] = (buf[6] & 0x0f) | 0x50;
  buf[8] = (buf[8] & 0x3f) | 0x80;
  const hex = buf.toString("hex").slice(0, 32);
  return (
    hex.slice(0, 8) +
    "-" +
    hex.slice(8, 12) +
    "-" +
    hex.slice(12, 16) +
    "-" +
    hex.slice(16, 20) +
    "-" +
    hex.slice(20, 32)
  );
}

/** Derive a company id from a tenant slug. Server-only. */
export function deriveTenantCompanyId(slug: string): string {
  const normalized = slug.trim().toLowerCase();
  if (!normalized) throw new Error("tenant slug must be non-empty");
  return uuidv5(normalized, WORMBASE_TENANT_NAMESPACE);
}
