/**
 * Capability-honesty: every connector in the catalog declares
 * ``status`` + ``statusNote``.
 *
 * Mirrors packages/lake-surfaces/tests/test_connector_status.py — both
 * sides of the cross-language schema sync are enforced.
 */
import { describe, it, expect } from "vitest";
import {
  CONNECTOR_CATALOG,
  getConnectorByKind,
  type ConnectorStatus,
} from "../../lib/lake-surfaces-catalog";

const ALLOWED: ReadonlyArray<ConnectorStatus> = [
  "production",
  "preview",
  "coming_soon",
];

const EXPECTED: Record<string, ConnectorStatus> = {
  csv_local: "production",
  postgres: "production",
  snowflake: "production",
  s3_csv: "production",
  http_csv: "production",
  stripe: "production",
  bigquery: "coming_soon",
  salesforce: "coming_soon",
  hubspot: "coming_soon",
  gsheets: "coming_soon",
  notion: "coming_soon",
  linear: "coming_soon",
};

describe("lake-surfaces-catalog: capability honesty", () => {
  it("every entry has a non-empty status from the allowed set", () => {
    for (const c of CONNECTOR_CATALOG) {
      expect(ALLOWED).toContain(c.status);
    }
  });

  it("every entry has a non-empty statusNote ≤ 200 chars", () => {
    for (const c of CONNECTOR_CATALOG) {
      expect(typeof c.statusNote).toBe("string");
      expect(c.statusNote.length).toBeGreaterThan(0);
      expect(c.statusNote.length).toBeLessThanOrEqual(200);
    }
  });

  it("statuses match the Python registry expectations", () => {
    for (const [kind, expected] of Object.entries(EXPECTED)) {
      const entry = getConnectorByKind(kind);
      expect(entry, `${kind} should be in the catalog`).toBeTruthy();
      expect(entry?.status).toBe(expected);
    }
  });

  it("ready=true if and only if status='production'", () => {
    for (const c of CONNECTOR_CATALOG) {
      expect(c.ready).toBe(c.status === "production");
    }
  });

  it("includes all 12 day-one kinds", () => {
    const kinds = CONNECTOR_CATALOG.map((c) => c.kind).sort();
    expect(kinds).toEqual(
      [
        "bigquery",
        "csv_local",
        "gsheets",
        "http_csv",
        "hubspot",
        "linear",
        "notion",
        "postgres",
        "s3_csv",
        "salesforce",
        "snowflake",
        "stripe",
      ].sort(),
    );
  });
});
