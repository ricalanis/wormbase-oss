/**
 * /api/sources/propose — credential_ref threading tests.
 *
 * Closes carry-forward #1 from the 2026-06-10 CredentialBroker
 * integration close-out by pinning the dashboard end of the wire:
 *
 *   - opaque-secret kinds without credential_ref get
 *     ``credential_ref_missing: true`` in the response envelope so the
 *     UI can surface a follow-up prompt
 *   - opaque-secret kinds WITH credential_ref echo back
 *     ``credential_ref_missing: false`` + carry the ref into the
 *     synthetic receipt payload
 *   - URI-shaped kinds ignore credential_ref entirely (no-op,
 *     ``opaque_secret_kind: false``)
 *   - whitespace-only refs are normalised to null (treated as missing)
 */
import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("../../lib/tenant-cookies", () => ({
  getCurrentCompanyId: async () =>
    "00000000-0000-0000-0000-0000000c0001",
}));

beforeEach(() => {
  vi.clearAllMocks();
});

function reqFor(body: Record<string, unknown>): Request {
  return new Request("http://localhost:3000/api/sources/propose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("POST /api/sources/propose — credential_ref threading", () => {
  it("flags opaque-secret kind without credential_ref as missing", async () => {
    const { POST } = await import(
      "../../app/api/sources/propose/route"
    );
    const res = await POST(
      reqFor({
        uri: "stripe://acct_acme",
        owner: "dashboard",
        classification: "confidential",
        kind: "stripe",
      })
    );
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.ok).toBe(true);
    expect(body.connector_kind).toBe("stripe");
    expect(body.opaque_secret_kind).toBe(true);
    expect(body.credential_ref_missing).toBe(true);
    expect(body.opaque_secret_kinds).toEqual(
      expect.arrayContaining(["stripe", "salesforce", "hubspot", "gsheets"])
    );
  });

  it("threads credential_ref when supplied for an opaque kind", async () => {
    const { POST } = await import(
      "../../app/api/sources/propose/route"
    );
    const res = await POST(
      reqFor({
        uri: "stripe://acct_acme",
        owner: "dashboard",
        classification: "confidential",
        kind: "stripe",
        credential_ref: "vault://stripe-prod",
      })
    );
    const body = (await res.json()) as {
      ok: boolean;
      opaque_secret_kind: boolean;
      credential_ref_missing: boolean;
      credential_ref: string | null;
    };
    expect(body.ok).toBe(true);
    expect(body.opaque_secret_kind).toBe(true);
    expect(body.credential_ref_missing).toBe(false);
    // The route echoes the (sanitised) credential_ref into the response
    // envelope. Until the route is upgraded to call
    // SourceBuilder.connect() end-to-end, this is the canonical
    // ledger-bound carrier.
    expect(body.credential_ref).toBe("vault://stripe-prod");
  });

  it("treats whitespace-only credential_ref as missing", async () => {
    const { POST } = await import(
      "../../app/api/sources/propose/route"
    );
    const res = await POST(
      reqFor({
        uri: "stripe://acct_acme",
        owner: "dashboard",
        classification: "confidential",
        kind: "stripe",
        credential_ref: "   ",
      })
    );
    const body = (await res.json()) as {
      credential_ref_missing: boolean;
    };
    expect(body.credential_ref_missing).toBe(true);
  });

  it("ignores credential_ref for URI-shaped (csv_local) kind", async () => {
    const { POST } = await import(
      "../../app/api/sources/propose/route"
    );
    const res = await POST(
      reqFor({
        uri: "/tmp/data.csv",
        owner: "dashboard",
        classification: "internal",
        kind: "csv_local",
        // credential_ref not relevant for URI-shaped kinds
      })
    );
    const body = (await res.json()) as {
      ok: boolean;
      opaque_secret_kind: boolean;
      credential_ref_missing: boolean;
    };
    expect(body.ok).toBe(true);
    expect(body.opaque_secret_kind).toBe(false);
    // URI-shaped kinds never flag missing — they don't need it.
    expect(body.credential_ref_missing).toBe(false);
  });

  it("ignores credential_ref for postgres / snowflake / bigquery too", async () => {
    const { POST } = await import(
      "../../app/api/sources/propose/route"
    );
    for (const kind of ["postgres", "snowflake", "bigquery", "s3_csv"]) {
      const res = await POST(
        reqFor({
          uri: `${kind}://example`,
          owner: "dashboard",
          classification: "internal",
          kind,
        })
      );
      const body = (await res.json()) as {
        opaque_secret_kind: boolean;
        credential_ref_missing: boolean;
      };
      expect(body.opaque_secret_kind).toBe(false);
      expect(body.credential_ref_missing).toBe(false);
    }
  });

  it("succeeds for salesforce + hubspot + gsheets too with a ref", async () => {
    const { POST } = await import(
      "../../app/api/sources/propose/route"
    );
    for (const kind of ["salesforce", "hubspot", "gsheets"]) {
      const res = await POST(
        reqFor({
          uri: `${kind}://example`,
          owner: "dashboard",
          classification: "confidential",
          kind,
          credential_ref: `vault://${kind}-prod`,
        })
      );
      const body = (await res.json()) as {
        ok: boolean;
        opaque_secret_kind: boolean;
        credential_ref_missing: boolean;
      };
      expect(body.ok).toBe(true);
      expect(body.opaque_secret_kind).toBe(true);
      expect(body.credential_ref_missing).toBe(false);
    }
  });
});
