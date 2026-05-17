/**
 * Signed session cookie (Phase 1B.E — multi-tenancy v2 plan).
 *
 * Replaces the unsigned ``wormbase-tenant-slug`` cookie as the
 * source-of-truth for the active session. Carries:
 *
 *   * tenant_slug — the tenant the session is bound to.
 *   * person_id — the bound Person, or null when the session is bound
 *     to an observer-only role (e.g. magic-link evaluators).
 *   * exp — unix-seconds expiry.
 *
 * Signed with ``WORMBASE_LEDGER_API_TOKEN`` so the rotation surface is
 * the same one the MCP Person-tokens already use.
 *
 * Forwards-compat: the legacy unsigned slug cookie keeps working for one
 * release window via ``getTenantFromCookies()`` in ``tenant-cookies.ts``.
 * Once Phase 4C lands the sign-in UI, every new session will be a
 * ``wormbase-session`` cookie; the legacy slug cookie is then deleted.
 */
import { createHmac } from "node:crypto";

export interface SessionClaims {
  tenantSlug: string;
  personId: string | null;
  exp: number;
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

/** Constant-time buffer comparison; rejects unequal-length buffers. */
function timingSafeEqual(a: Buffer, b: Buffer): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

/**
 * Encode a signed session cookie. Format mirrors
 * ``encodeMagicLinkToken``: ``base64url(JSON(claims)).base64url(hmac)``.
 */
export function encodeSessionCookie(args: {
  tenantSlug: string;
  personId: string | null;
  secret: string;
  expiresInSeconds: number;
  issuedAtSeconds?: number;
}): string {
  const issuedAt = args.issuedAtSeconds ?? Math.floor(Date.now() / 1000);
  const claims: SessionClaims = {
    tenantSlug: args.tenantSlug,
    personId: args.personId,
    exp: issuedAt + args.expiresInSeconds,
  };
  const body = Buffer.from(JSON.stringify(claims), "utf8");
  const sig = createHmac("sha256", args.secret).update(body).digest();
  return `${b64urlEncode(body)}.${b64urlEncode(sig)}`;
}

/**
 * Verify + decode a session cookie. Returns claims on success; null on
 * malformed / expired / signature failure.
 */
export function decodeSessionCookie(
  cookie: string,
  args: { secret: string; nowSeconds?: number },
): SessionClaims | null {
  const idx = cookie.lastIndexOf(".");
  if (idx <= 0) return null;
  let body: Buffer;
  let sig: Buffer;
  try {
    body = b64urlDecode(cookie.slice(0, idx));
    sig = b64urlDecode(cookie.slice(idx + 1));
  } catch {
    return null;
  }
  const expected = createHmac("sha256", args.secret).update(body).digest();
  if (!timingSafeEqual(expected, sig)) return null;
  let claims: SessionClaims;
  try {
    claims = JSON.parse(body.toString("utf8")) as SessionClaims;
  } catch {
    return null;
  }
  const now = args.nowSeconds ?? Math.floor(Date.now() / 1000);
  if (typeof claims.exp !== "number" || claims.exp < now) return null;
  if (typeof claims.tenantSlug !== "string" || !claims.tenantSlug) return null;
  if (
    claims.personId !== null &&
    (typeof claims.personId !== "string" || !claims.personId)
  ) {
    return null;
  }
  return claims;
}

export const SESSION_COOKIE_NAME = "wormbase-session";

/** Default session lifetime: 30 days. Mirrors the legacy slug cookie's TTL. */
export const DEFAULT_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30;
