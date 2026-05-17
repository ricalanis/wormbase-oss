/**
 * Phase 4 Task 4C — tests for the magic-link request route.
 *
 * The route was added in 1B.D; 4C wires it to the visitor-facing forms
 * on the landing page and `/login`. These tests pin the contract the
 * forms rely on:
 *   - Returns 200 + ``{sent: true, expires_in_s}`` for valid emails.
 *   - Returns 400 ``invalid_email`` for malformed inputs.
 *   - Returns 400 ``bad_json`` for non-JSON bodies.
 *   - Returns 503 ``auth_secret_unset`` when the signing secret is
 *     absent (so the form surfaces an honest "magic-link disabled"
 *     state instead of pretending to send).
 *   - In dev mode (``WORMBASE_AUTH_DEV_MODE=1``), the response body
 *     carries the rendered ``magic_link`` so the form can offer a
 *     copy-link affordance instead of relying on stdout.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";

import { POST as requestRoute } from "../../app/api/auth/email/request/route";

const SECRET = "test-request-secret";

function makeRequest(body: unknown, opts?: { rawBody?: string }): Request {
  return new Request("https://dashboard.example/api/auth/email/request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: opts?.rawBody ?? JSON.stringify(body),
  });
}

describe("/api/auth/email/request — Phase 4C wire-up", () => {
  let oldSecret: string | undefined;
  let oldDev: string | undefined;
  beforeEach(() => {
    oldSecret = process.env.WORMBASE_LEDGER_API_TOKEN;
    oldDev = process.env.WORMBASE_AUTH_DEV_MODE;
    process.env.WORMBASE_LEDGER_API_TOKEN = SECRET;
    delete process.env.WORMBASE_AUTH_DEV_MODE;
  });
  afterEach(() => {
    if (oldSecret === undefined) delete process.env.WORMBASE_LEDGER_API_TOKEN;
    else process.env.WORMBASE_LEDGER_API_TOKEN = oldSecret;
    if (oldDev === undefined) delete process.env.WORMBASE_AUTH_DEV_MODE;
    else process.env.WORMBASE_AUTH_DEV_MODE = oldDev;
  });

  it("returns 200 + sent=true for a valid email", async () => {
    const res = await requestRoute(
      makeRequest({ email: "evaluator@example.com" }) as unknown as never,
    );
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.sent).toBe(true);
    expect(typeof json.expires_in_s).toBe("number");
    expect(json.pending_token_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(json.magic_link).toBeUndefined(); // dev-mode off
  });

  it("returns 400 invalid_email for malformed inputs", async () => {
    const res = await requestRoute(
      makeRequest({ email: "not-an-email" }) as unknown as never,
    );
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe("invalid_email");
  });

  it("returns 400 bad_json for non-JSON bodies", async () => {
    const res = await requestRoute(
      makeRequest(null, { rawBody: "<<<" }) as unknown as never,
    );
    expect(res.status).toBe(400);
    expect((await res.json()).error).toBe("bad_json");
  });

  it("returns 503 auth_secret_unset when WORMBASE_LEDGER_API_TOKEN is missing", async () => {
    delete process.env.WORMBASE_LEDGER_API_TOKEN;
    const res = await requestRoute(
      makeRequest({ email: "x@y.com" }) as unknown as never,
    );
    expect(res.status).toBe(503);
    expect((await res.json()).error).toBe("auth_secret_unset");
  });

  it("includes the rendered magic_link in dev mode", async () => {
    process.env.WORMBASE_AUTH_DEV_MODE = "1";
    const res = await requestRoute(
      makeRequest({ email: "x@y.com" }) as unknown as never,
    );
    const json = await res.json();
    expect(typeof json.magic_link).toBe("string");
    expect(json.magic_link).toContain("/api/auth/email/confirm?token=");
  });
});
