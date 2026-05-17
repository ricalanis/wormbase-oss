/**
 * Opaque-secret connector classification tests.
 *
 * Drift-pin: when the worm-core Python registry adds a new opaque-
 * secret connector kind, the dashboard mirror must follow or the
 * CredentialRefInput will silently miss the new kind.
 */

import { describe, it, expect } from "vitest";
import {
  OPAQUE_SECRET_CONNECTOR_KINDS,
  isOpaqueSecretKind,
} from "../../lib/opaque-secret-connectors";

describe("opaque-secret-connectors", () => {
  it("classifies the four canonical opaque kinds", () => {
    expect(isOpaqueSecretKind("stripe")).toBe(true);
    expect(isOpaqueSecretKind("salesforce")).toBe(true);
    expect(isOpaqueSecretKind("hubspot")).toBe(true);
    expect(isOpaqueSecretKind("gsheets")).toBe(true);
  });

  it("does NOT classify URI-shaped kinds as opaque", () => {
    expect(isOpaqueSecretKind("csv_local")).toBe(false);
    expect(isOpaqueSecretKind("postgres")).toBe(false);
    expect(isOpaqueSecretKind("snowflake")).toBe(false);
    expect(isOpaqueSecretKind("bigquery")).toBe(false);
    expect(isOpaqueSecretKind("s3_csv")).toBe(false);
    expect(isOpaqueSecretKind("http_csv")).toBe(false);
  });

  it("treats unknown kinds as not opaque (default-safe)", () => {
    expect(isOpaqueSecretKind("mcp:custom_server")).toBe(false);
    expect(isOpaqueSecretKind("notion")).toBe(false);
    expect(isOpaqueSecretKind("linear")).toBe(false);
    expect(isOpaqueSecretKind("local_lake")).toBe(false);
  });

  it("handles null / undefined / empty defensively", () => {
    expect(isOpaqueSecretKind(null)).toBe(false);
    expect(isOpaqueSecretKind(undefined)).toBe(false);
    expect(isOpaqueSecretKind("")).toBe(false);
  });

  it("exports the canonical four-kind set", () => {
    expect([...OPAQUE_SECRET_CONNECTOR_KINDS].sort()).toEqual([
      "gsheets",
      "hubspot",
      "salesforce",
      "stripe",
    ]);
  });
});
