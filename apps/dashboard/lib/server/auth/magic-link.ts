/**
 * Email magic-link backend (Phase 1B.D — multi-tenancy v2 plan).
 *
 * Two surfaces:
 *
 *   * encodeMagicLinkToken / decodeMagicLinkToken — signed (HMAC-SHA256)
 *     token format carrying ``email`` + ``exp``. Mirrors the compact
 *     token format used by MCP Person-tokens, with a different claim
 *     shape; signs with ``WORMBASE_LEDGER_API_TOKEN`` (one rotation
 *     surface for the deployment).
 *
 *   * pickDemoTenantForEmail — pure round-robin policy: pick the demo
 *     tenant the requesting email has not previously visited; if all
 *     visited, pick the one with the oldest visit by this email.
 *
 *   * MagicLinkSender + LogOnlySender — pluggable Protocol so Phase 4
 *     polish can swap in SES / SendGrid without changing the API
 *     surface. Default 1B implementation logs to stderr.
 *
 * The actual route handlers (POST /api/auth/email/request and
 * GET /api/auth/email/confirm) live in
 * ``app/api/auth/email/{request,confirm}/route.ts``.
 */
import { createHash, createHmac } from "node:crypto";

export interface MagicLinkSender {
  send(args: { to: string; link: string; expiresInS: number }): Promise<void>;
}

/** Default sender — logs to stderr. Sufficient for 1B without SMTP wired. */
export class LogOnlySender implements MagicLinkSender {
  async send(args: { to: string; link: string; expiresInS: number }): Promise<void> {
     
    console.error(
      `MAGIC_LINK to=${args.to} link=${args.link} exp=${args.expiresInS}s`,
    );
  }
}

export interface MagicLinkClaims {
  email: string;
  exp: number; // unix seconds
}

function b64urlEncode(buf: Buffer): string {
  return buf
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function b64urlDecode(s: string): Buffer {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  return Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/") + pad, "base64");
}

/**
 * Encode a signed magic-link token.
 *
 * Format: ``base64url(JSON({email, exp})).base64url(hmac-sha256(secret, body))``
 */
export function encodeMagicLinkToken(args: {
  email: string;
  secret: string;
  expiresInSeconds: number;
  issuedAtSeconds?: number;
}): string {
  const issuedAt = args.issuedAtSeconds ?? Math.floor(Date.now() / 1000);
  const claims: MagicLinkClaims = {
    email: args.email,
    exp: issuedAt + args.expiresInSeconds,
  };
  const body = Buffer.from(JSON.stringify(claims), "utf8");
  const sig = createHmac("sha256", args.secret).update(body).digest();
  return `${b64urlEncode(body)}.${b64urlEncode(sig)}`;
}

/**
 * Verify + decode a magic-link token.
 *
 * Returns the claims dict on success. Returns null if the token is
 * malformed, the signature does not verify, or it has expired.
 */
export function decodeMagicLinkToken(
  token: string,
  args: { secret: string; nowSeconds?: number },
): MagicLinkClaims | null {
  const idx = token.lastIndexOf(".");
  if (idx <= 0) return null;
  let body: Buffer;
  let sig: Buffer;
  try {
    body = b64urlDecode(token.slice(0, idx));
    sig = b64urlDecode(token.slice(idx + 1));
  } catch {
    return null;
  }
  const expected = createHmac("sha256", args.secret).update(body).digest();
  if (sig.length !== expected.length) return null;
  let diff = 0;
  for (let i = 0; i < sig.length; i++) diff |= sig[i] ^ expected[i];
  if (diff !== 0) return null;
  let claims: MagicLinkClaims;
  try {
    claims = JSON.parse(body.toString("utf8")) as MagicLinkClaims;
  } catch {
    return null;
  }
  const now = args.nowSeconds ?? Math.floor(Date.now() / 1000);
  if (typeof claims.exp !== "number" || claims.exp < now) return null;
  if (typeof claims.email !== "string" || !claims.email) return null;
  return claims;
}

/**
 * Compute the canonical sha256 hex of a magic-link token. The matching
 * ``tenant_signup_initiated`` ledger entry's ``pending_token_hash``
 * field stores this value so the confirm endpoint can verify the
 * presented token corresponds to a previously-emitted initiation.
 */
export function hashTokenForLedger(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}

export interface DemoTenantState {
  /** Canonical demo tenant slug (e.g. ``wormbase-saas-demo``). */
  slug: string;
  /** Visit log; one entry per (email, visited_at) pair. */
  visitors: Array<{ email: string; visited_at: string }>;
}

/**
 * Pure round-robin: prefer unvisited; if all visited by this email,
 * pick the one with the oldest last-visit by this email.
 *
 * Stable tiebreak: alphabetical by slug for unvisited.
 */
export function pickDemoTenantForEmail(args: {
  email: string;
  demoTenants: DemoTenantState[];
}): string {
  if (args.demoTenants.length === 0) {
    throw new Error("no demo tenants configured");
  }
  const unvisited = args.demoTenants.filter(
    (t) => !t.visitors.some((v) => v.email === args.email),
  );
  if (unvisited.length > 0) {
    const sorted = [...unvisited].sort(
      (a, b) =>
        a.visitors.length - b.visitors.length || a.slug.localeCompare(b.slug),
    );
    return sorted[0].slug;
  }
  const withLastVisit = args.demoTenants.map((t) => {
    const v = t.visitors.find((x) => x.email === args.email);
    return { slug: t.slug, lastVisitAt: v ? v.visited_at : "" };
  });
  withLastVisit.sort((a, b) => a.lastVisitAt.localeCompare(b.lastVisitAt));
  return withLastVisit[0].slug;
}

export const DEFAULT_DEMO_TENANT_SLUGS = [
  "wormbase-saas-demo",
  "wormbase-fintech-demo",
  "wormbase-marketplace-demo",
  "wormbase-ecommerce-demo",
  "wormbase-agency-demo",
];

export function getDemoTenantSlugs(): string[] {
  const env = (process.env.WORMBASE_DEMO_TENANT_SLUGS ?? "").trim();
  if (!env) return [...DEFAULT_DEMO_TENANT_SLUGS];
  return env
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/** RFC-5321-shape email validator; strict enough for a magic-link gate. */
export function isValidEmailShape(s: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s);
}
