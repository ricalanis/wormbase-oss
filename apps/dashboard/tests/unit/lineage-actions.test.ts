/**
 * Server-action tests for /lake/lineage/actions.ts — L3 Sub-wave D.
 *
 * Direct-tests the input validation + the test-hook exports. Network
 * paths (POST to worm-core) are exercised by the worm-core HTTP
 * integration test suite in Sub-wave C.
 */
import { describe, expect, it } from "vitest";

import { __test__ } from "../../app/(app)/lake/lineage/actions";

const { VALID_REJECT_REASONS, readBase, readToken } = __test__;

describe("/lake/lineage actions — reject reasons enum", () => {
  it("accepts only the 5 canonical reasons", () => {
    expect(VALID_REJECT_REASONS.has("false_positive")).toBe(true);
    expect(VALID_REJECT_REASONS.has("wrong_direction")).toBe(true);
    expect(VALID_REJECT_REASONS.has("low_confidence")).toBe(true);
    expect(VALID_REJECT_REASONS.has("out_of_scope")).toBe(true);
    expect(VALID_REJECT_REASONS.has("other")).toBe(true);
    expect(VALID_REJECT_REASONS.size).toBe(5);
  });

  it("rejects unknown reasons", () => {
    expect(VALID_REJECT_REASONS.has("totally_wrong")).toBe(false);
    expect(VALID_REJECT_REASONS.has("")).toBe(false);
    expect(VALID_REJECT_REASONS.has("  false_positive  ")).toBe(false);
  });
});

describe("/lake/lineage actions — env-knob readers", () => {
  it("readBase trims trailing slashes", () => {
    const old = process.env.WORM_CORE_API_URL;
    process.env.WORM_CORE_API_URL = "http://worm-core:8910///";
    try {
      expect(readBase()).toBe("http://worm-core:8910");
    } finally {
      if (old === undefined) delete process.env.WORM_CORE_API_URL;
      else process.env.WORM_CORE_API_URL = old;
    }
  });

  it("readBase prefers WORM_CORE_API_URL over WORMBASE_LEDGER_API_BASE", () => {
    const oldA = process.env.WORM_CORE_API_URL;
    const oldB = process.env.WORMBASE_LEDGER_API_BASE;
    process.env.WORM_CORE_API_URL = "http://a:1";
    process.env.WORMBASE_LEDGER_API_BASE = "http://b:2";
    try {
      expect(readBase()).toBe("http://a:1");
    } finally {
      if (oldA === undefined) delete process.env.WORM_CORE_API_URL;
      else process.env.WORM_CORE_API_URL = oldA;
      if (oldB === undefined) delete process.env.WORMBASE_LEDGER_API_BASE;
      else process.env.WORMBASE_LEDGER_API_BASE = oldB;
    }
  });

  it("readBase returns empty string when neither env knob is set", () => {
    const oldA = process.env.WORM_CORE_API_URL;
    const oldB = process.env.WORMBASE_LEDGER_API_BASE;
    delete process.env.WORM_CORE_API_URL;
    delete process.env.WORMBASE_LEDGER_API_BASE;
    try {
      expect(readBase()).toBe("");
    } finally {
      if (oldA !== undefined) process.env.WORM_CORE_API_URL = oldA;
      if (oldB !== undefined) process.env.WORMBASE_LEDGER_API_BASE = oldB;
    }
  });

  it("readToken trims whitespace", () => {
    const old = process.env.WORMBASE_LEDGER_API_TOKEN;
    process.env.WORMBASE_LEDGER_API_TOKEN = "   secret-token   ";
    try {
      expect(readToken()).toBe("secret-token");
    } finally {
      if (old === undefined) delete process.env.WORMBASE_LEDGER_API_TOKEN;
      else process.env.WORMBASE_LEDGER_API_TOKEN = old;
    }
  });
});
