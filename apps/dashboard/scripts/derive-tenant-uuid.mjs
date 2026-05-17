#!/usr/bin/env node
// Derive UUIDv5 for a new tenant slug under WORMBASE_TENANT_NAMESPACE.
//
// Usage:
//   node apps/dashboard/scripts/derive-tenant-uuid.mjs <slug>
//
// Output: prints the company_id; use it to append a new entry to
// `apps/dashboard/lib/tenants.ts` `KNOWN_TENANTS`. The matching value is
// what `wormbase_channel_adapter.tenant.tenant_to_company_uuid(slug)` and
// `wormbase_core.service.tenant_to_uuid(slug)` produce for the same slug.

import { createHash } from "node:crypto";

const NS = "6f7c4b1d-3f0a-5b2c-9d8e-1a4b5c6d7e8f";

const slug = (process.argv[2] || "").trim().toLowerCase();
if (!slug) {
  console.error("usage: derive-tenant-uuid.mjs <slug>");
  process.exit(1);
}

const nsBytes = Buffer.from(NS.replace(/-/g, ""), "hex");
const h = createHash("sha1");
h.update(nsBytes);
h.update(slug);
const buf = h.digest();
buf[6] = (buf[6] & 0x0f) | 0x50;
buf[8] = (buf[8] & 0x3f) | 0x80;
const hex = buf.toString("hex").slice(0, 32);
const uuid = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20, 32)}`;
console.log(uuid);
