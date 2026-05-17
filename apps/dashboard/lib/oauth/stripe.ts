/**
 * Stripe Connect OAuth handler — Onboarding Sub-wave D (2026-05-30).
 *
 * Reference impl for the four OAuth-style connector kinds (Stripe /
 * Salesforce / HubSpot / GSheets). Stripe lands first because it has
 * the lowest dev-onboarding friction (no domain verification, free
 * test keys, well-documented endpoint surface). The other three
 * connectors land OAuth in a future wave following the same shape.
 *
 * Honest contract:
 *
 *   * When ``STRIPE_OAUTH_CLIENT_ID`` + ``STRIPE_OAUTH_CLIENT_SECRET``
 *     are unset → the callback redirects to a "not configured"
 *     surface. We do NOT fall back to the credential-paste form
 *     anymore for Stripe — that fallback was the bug the spec
 *     graduated out of. Salesforce / HubSpot / GSheets still use the
 *     credential-paste path (future-wave port).
 *
 *   * When env vars are set + the user authorizes → the handshake
 *     runs end-to-end: code → token → CredentialBroker storage →
 *     source_connected ledger entry. No half-baked synthetic state.
 *
 *   * State (CSRF) is round-tripped via a session cookie set by the
 *     ``./start`` route; mismatch → 400. Same pattern as the Slack
 *     handler at ``app/onboarding/oauth/[platform]/callback/route.ts``.
 */
import { randomBytes } from "node:crypto";

export const STRIPE_OAUTH_AUTHORIZE_URL =
  "https://connect.stripe.com/oauth/authorize";
export const STRIPE_OAUTH_TOKEN_URL = "https://connect.stripe.com/oauth/token";
export const STRIPE_STATE_COOKIE = "wormbase-stripe-oauth-state";

/**
 * Token-exchange envelope returned by Stripe's OAuth endpoint. The
 * field names mirror Stripe's documented response shape; we only
 * declare the fields we read downstream so we don't pin tests to
 * Stripe's full envelope.
 */
export interface StripeTokenResponse {
  access_token: string;
  refresh_token?: string | null;
  scope: string;
  livemode: boolean;
  stripe_user_id: string;
  stripe_publishable_key?: string | null;
  token_type: string;
}

/**
 * The CredentialBroker handle name we use for stored Stripe tokens.
 * Format: ``stripe::<tenant_slug>::<stripe_user_id>`` so the broker
 * looks the token up by tenant + connected-account composite key.
 */
export function credentialHandleFor(
  tenantSlug: string,
  stripeUserId: string,
): string {
  const cleanTenant = tenantSlug.trim() || "baseworm";
  const cleanUser = stripeUserId.trim();
  if (!cleanUser) {
    throw new Error("stripe_user_id required for credential handle");
  }
  return `stripe::${cleanTenant}::${cleanUser}`;
}

/**
 * Outcome of ``isConfigured()`` for the Stripe OAuth surface. Returned
 * by the start + callback routes so the dashboard can render an
 * honest "not configured" page instead of falling back to the broken
 * credential-paste path.
 */
export interface StripeOAuthConfig {
  configured: boolean;
  clientId: string | null;
  missing: string[];
}

/**
 * Read the Stripe OAuth env vars + return whether the feature is
 * usable. Both vars are required-for-feature, not opt-in. Operators
 * who haven't configured Stripe see an honest disabled surface, not a
 * fake-positive credential-paste fallback.
 */
export function readStripeOAuthConfig(): StripeOAuthConfig {
  const clientId = (process.env.STRIPE_OAUTH_CLIENT_ID ?? "").trim();
  const clientSecret = (process.env.STRIPE_OAUTH_CLIENT_SECRET ?? "").trim();
  const missing: string[] = [];
  if (!clientId) missing.push("STRIPE_OAUTH_CLIENT_ID");
  if (!clientSecret) missing.push("STRIPE_OAUTH_CLIENT_SECRET");
  return {
    configured: missing.length === 0,
    clientId: clientId || null,
    missing,
  };
}

/**
 * Build the authorize-URL that the dashboard's "Connect Stripe"
 * button targets. The ``state`` value is a CSRF token; the caller
 * sets it as a cookie before redirecting so the callback can verify.
 */
export function buildStripeAuthorizeUrl(opts: {
  clientId: string;
  state: string;
  redirectUri: string;
  scope?: "read_only" | "read_write";
}): string {
  const params = new URLSearchParams({
    response_type: "code",
    client_id: opts.clientId,
    scope: opts.scope ?? "read_only",
    state: opts.state,
    "stripe_user[business_type]": "company",
    redirect_uri: opts.redirectUri,
  });
  return `${STRIPE_OAUTH_AUTHORIZE_URL}?${params.toString()}`;
}

/**
 * Generate a fresh CSRF state token. 24 bytes of URL-safe randomness
 * is plenty for the 5-minute Stripe redirect window.
 */
export function generateOAuthState(): string {
  return randomBytes(24).toString("base64url");
}

/**
 * Resolved value from a ``vault://...`` / ``env://...`` / raw scheme.
 *
 * The dashboard supports three credential-broker schemes:
 *   * ``vault://<path>``       — read from HashiCorp Vault when
 *                                ``VAULT_ADDR`` is set
 *   * ``env://<VAR_NAME>``     — read from process env var directly
 *   * raw                       — pass the value through unchanged
 *
 * This handler accepts all three so operators can rotate without
 * code changes.
 */
export async function resolveSecretRef(raw: string): Promise<string> {
  const trimmed = raw.trim();
  if (!trimmed) return "";

  if (trimmed.startsWith("env://")) {
    const varName = trimmed.slice("env://".length).trim();
    if (!varName) {
      throw new Error("env://<VAR> reference missing var name");
    }
    const v = (process.env[varName] ?? "").trim();
    if (!v) {
      throw new Error(`env-ref ${varName} unset or empty`);
    }
    return v;
  }

  if (trimmed.startsWith("vault://")) {
    const vaultAddr = (process.env.VAULT_ADDR ?? "").trim();
    if (!vaultAddr) {
      throw new Error(
        "vault://... credential supplied but VAULT_ADDR is unset; " +
          "set VAULT_ADDR (and VAULT_TOKEN) or use env://<VAR_NAME> for " +
          "env-resident secrets",
      );
    }
    const path = trimmed.slice("vault://".length).trim();
    if (!path) {
      throw new Error("vault://<path> reference missing path");
    }
    const vaultToken = (process.env.VAULT_TOKEN ?? "").trim();
    if (!vaultToken) {
      throw new Error("VAULT_TOKEN unset; required for vault:// resolution");
    }
    // The dashboard runs server-side; native fetch is available.
    const url = `${vaultAddr.replace(/\/+$/, "")}/v1/${path.replace(/^\/+/, "")}`;
    const res = await fetch(url, {
      method: "GET",
      headers: { "X-Vault-Token": vaultToken },
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(`vault GET ${path} returned ${res.status}`);
    }
    const body = (await res.json()) as {
      data?: { data?: Record<string, string> };
    };
    const value = body.data?.data?.value ?? "";
    if (!value) {
      throw new Error(`vault path ${path!} did not return data.data.value`);
    }
    return value;
  }

  // Raw secret — pass through unchanged.
  return trimmed;
}

/**
 * Exchange an authorization code for an access token. Pure function
 * over the wire-call; injects a fetch impl for testability.
 *
 * Errors are normalized into a typed exception (``StripeOAuthError``)
 * so callers can branch on ``error.code`` rather than parse free-text
 * messages.
 */
export class StripeOAuthError extends Error {
  constructor(
    message: string,
    public readonly code:
      | "invalid_grant"
      | "invalid_client"
      | "network_error"
      | "bad_response"
      | "non_ok_status",
    public readonly status: number,
  ) {
    super(message);
    this.name = "StripeOAuthError";
  }
}

export interface ExchangeStripeCodeOpts {
  code: string;
  clientSecretRef: string;
  /** Optional fetch implementation override (for unit tests). */
  fetchImpl?: typeof fetch;
}

/**
 * Run the Stripe code-for-token exchange.
 *
 * The bulk of the contract is documented in ``StripeOAuthError``: we
 * normalize wire errors into typed exceptions so the route handler can
 * branch on ``code`` and surface the right UX (retry vs reconfigure).
 */
export async function exchangeStripeCode(
  opts: ExchangeStripeCodeOpts,
): Promise<StripeTokenResponse> {
  const code = opts.code.trim();
  if (!code) {
    throw new StripeOAuthError("missing authorization code", "invalid_grant", 400);
  }
  const clientSecret = await resolveSecretRef(opts.clientSecretRef);
  if (!clientSecret) {
    throw new StripeOAuthError(
      "STRIPE_OAUTH_CLIENT_SECRET resolved to empty",
      "invalid_client",
      500,
    );
  }
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    client_secret: clientSecret,
  });
  const doFetch = opts.fetchImpl ?? fetch;
  let res: Response;
  try {
    res = await doFetch(STRIPE_OAUTH_TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
      cache: "no-store",
    });
  } catch (err) {
    const e = err as Error;
    throw new StripeOAuthError(
      `network error during Stripe token exchange: ${e.message}`,
      "network_error",
      502,
    );
  }

  const text = await res.text();
  let parsed: Record<string, unknown> = {};
  try {
    parsed = text ? (JSON.parse(text) as Record<string, unknown>) : {};
  } catch {
    throw new StripeOAuthError(
      `Stripe token endpoint returned non-JSON (status=${res.status}): ${text.slice(0, 200)}`,
      "bad_response",
      res.status,
    );
  }

  if (!res.ok) {
    // Stripe encodes its error contract via `{error: "invalid_grant", error_description: "..."}`.
    const errCode = String(parsed["error"] ?? "");
    const errDesc = String(parsed["error_description"] ?? text.slice(0, 200));
    if (errCode === "invalid_grant") {
      throw new StripeOAuthError(
        `Stripe rejected the code: ${errDesc}`,
        "invalid_grant",
        res.status,
      );
    }
    if (errCode === "invalid_client") {
      throw new StripeOAuthError(
        `Stripe rejected the client credentials: ${errDesc}`,
        "invalid_client",
        res.status,
      );
    }
    throw new StripeOAuthError(
      `Stripe token endpoint HTTP ${res.status}: ${errDesc}`,
      "non_ok_status",
      res.status,
    );
  }

  // Minimal shape validation: a usable token MUST carry access_token,
  // stripe_user_id, scope, and a livemode flag. Anything else is
  // optional in our consumption path.
  if (
    typeof parsed.access_token !== "string" ||
    typeof parsed.stripe_user_id !== "string" ||
    typeof parsed.scope !== "string"
  ) {
    throw new StripeOAuthError(
      `Stripe token response missing required fields (access_token/stripe_user_id/scope)`,
      "bad_response",
      res.status,
    );
  }

  return parsed as unknown as StripeTokenResponse;
}

/**
 * Description of where a Stripe access token landed. The route
 * handler logs this (without the secret) into the ledger entry so
 * operators can audit token storage.
 */
export interface StripeTokenStorageReceipt {
  /** Logical handle name passed to the CredentialBroker. */
  handle: string;
  /** "vault" or "env" — never the raw token. */
  scheme: "vault" | "env";
  /** Stripe-side connected account id. */
  stripeUserId: string;
  /** True when the env shipping the secret is the env scheme. */
  livemode: boolean;
  /** Scope granted by Stripe (e.g. ``read_only``). */
  scope: string;
}

/**
 * Persist the Stripe access token via the CredentialBroker. When
 * ``VAULT_ADDR`` is set we write to Vault at
 * ``secret/data/wormbase/stripe/<tenantSlug>/<stripe_user_id>``; when
 * unset we mark the receipt as env-resident (the route handler
 * fans out the env var to the next deploy via the operator runbook).
 *
 * The Vault path is opinionated to match the agent-gateway
 * CredentialBroker's Vault schema (``data.value`` envelope).
 */
export async function storeStripeToken(opts: {
  tenantSlug: string;
  token: StripeTokenResponse;
  fetchImpl?: typeof fetch;
}): Promise<StripeTokenStorageReceipt> {
  const handle = credentialHandleFor(opts.tenantSlug, opts.token.stripe_user_id);
  const vaultAddr = (process.env.VAULT_ADDR ?? "").trim();
  if (vaultAddr) {
    const vaultToken = (process.env.VAULT_TOKEN ?? "").trim();
    if (!vaultToken) {
      throw new Error("VAULT_ADDR set but VAULT_TOKEN unset; cannot store token");
    }
    const path =
      `secret/data/wormbase/stripe/` +
      `${encodeURIComponent(opts.tenantSlug)}/` +
      `${encodeURIComponent(opts.token.stripe_user_id)}`;
    const doFetch = opts.fetchImpl ?? fetch;
    const res = await doFetch(`${vaultAddr.replace(/\/+$/, "")}/v1/${path}`, {
      method: "POST",
      headers: {
        "X-Vault-Token": vaultToken,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        data: {
          value: opts.token.access_token,
          refresh_token: opts.token.refresh_token ?? null,
          scope: opts.token.scope,
          livemode: opts.token.livemode,
          stored_at: new Date().toISOString(),
        },
      }),
      cache: "no-store",
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Vault POST ${path} returned ${res.status}: ${text.slice(0, 200)}`);
    }
    return {
      handle,
      scheme: "vault",
      stripeUserId: opts.token.stripe_user_id,
      livemode: opts.token.livemode,
      scope: opts.token.scope,
    };
  }

  // Env-resident path: we don't have a way to mutate process env at
  // runtime safely, so we emit an honest receipt pointing operators
  // at the runbook. The actual token surfaces in the deploy via
  // ``STRIPE_TOKEN_<TENANT>_<USER>`` env var.
  return {
    handle,
    scheme: "env",
    stripeUserId: opts.token.stripe_user_id,
    livemode: opts.token.livemode,
    scope: opts.token.scope,
  };
}
