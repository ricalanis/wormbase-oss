/**
 * dashboard-url helpers (W7.A4).
 *
 * Verifies that ``getMcpServerUrl`` returns the right URL + mode for
 * each shape of ``WORMBASE_DASHBOARD_URL`` the dashboard service may
 * carry: localhost (dev / single-machine demo), cloudflared tunnel
 * (remote demo), and arbitrary public HTTPS origin (production).
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";

import {
  getDashboardOrigin,
  getMcpServerUrl,
} from "../../lib/server/dashboard-url";

const ENV_KEYS = ["WORMBASE_DASHBOARD_URL", "WORMBASE_MCP_PORT"] as const;

describe("getDashboardOrigin", () => {
  const originalEnv: Record<string, string | undefined> = {};
  beforeEach(() => {
    for (const key of ENV_KEYS) {
      originalEnv[key] = process.env[key];
      delete process.env[key];
    }
  });
  afterEach(() => {
    for (const key of ENV_KEYS) {
      if (originalEnv[key] === undefined) delete process.env[key];
      else process.env[key] = originalEnv[key];
    }
  });

  it("defaults to http://localhost:3000 when WORMBASE_DASHBOARD_URL is unset", () => {
    expect(getDashboardOrigin()).toBe("http://localhost:3000");
  });

  it("strips trailing slashes", () => {
    process.env.WORMBASE_DASHBOARD_URL =
      "https://demo-1234.trycloudflare.com/";
    expect(getDashboardOrigin()).toBe(
      "https://demo-1234.trycloudflare.com",
    );
  });

  it("preserves the port when present", () => {
    process.env.WORMBASE_DASHBOARD_URL = "http://localhost:3000";
    expect(getDashboardOrigin()).toBe("http://localhost:3000");
  });
});

describe("getMcpServerUrl", () => {
  const originalEnv: Record<string, string | undefined> = {};
  beforeEach(() => {
    for (const key of ENV_KEYS) {
      originalEnv[key] = process.env[key];
      delete process.env[key];
    }
  });
  afterEach(() => {
    for (const key of ENV_KEYS) {
      if (originalEnv[key] === undefined) delete process.env[key];
      else process.env[key] = originalEnv[key];
    }
  });

  it("returns http://localhost:9911/mcp + mode 'local' when dashboard is on localhost", () => {
    process.env.WORMBASE_DASHBOARD_URL = "http://localhost:3000";
    const result = getMcpServerUrl();
    expect(result.url).toBe("http://localhost:9911/mcp");
    expect(result.mode).toBe("local");
    expect(result.dashboardOrigin).toBe("http://localhost:3000");
  });

  it("honors WORMBASE_MCP_PORT override in local mode", () => {
    process.env.WORMBASE_DASHBOARD_URL = "http://localhost:3000";
    process.env.WORMBASE_MCP_PORT = "9999";
    const result = getMcpServerUrl();
    expect(result.url).toBe("http://localhost:9999/mcp");
    expect(result.mode).toBe("local");
  });

  it("returns <tunnel>/mcp + mode 'tunnel' for trycloudflare.com URLs", () => {
    process.env.WORMBASE_DASHBOARD_URL =
      "https://demo-1234.trycloudflare.com";
    const result = getMcpServerUrl();
    expect(result.url).toBe("https://demo-1234.trycloudflare.com/mcp");
    expect(result.mode).toBe("tunnel");
    expect(result.dashboardOrigin).toBe(
      "https://demo-1234.trycloudflare.com",
    );
  });

  it("treats any non-localhost public origin as tunnel mode", () => {
    process.env.WORMBASE_DASHBOARD_URL = "https://wormbase.example.com";
    const result = getMcpServerUrl();
    expect(result.url).toBe("https://wormbase.example.com/mcp");
    expect(result.mode).toBe("tunnel");
  });

  it("treats 127.0.0.1 / 0.0.0.0 / ::1 as local", () => {
    for (const host of [
      "http://127.0.0.1:3000",
      "http://0.0.0.0:3000",
      "http://[::1]:3000",
    ]) {
      process.env.WORMBASE_DASHBOARD_URL = host;
      const result = getMcpServerUrl();
      expect(result.mode).toBe("local");
      expect(result.url).toBe("http://localhost:9911/mcp");
    }
  });

  it("falls back to localhost defaults when env var is empty/missing", () => {
    // Empty string and unset both fall back.
    process.env.WORMBASE_DASHBOARD_URL = "";
    let result = getMcpServerUrl();
    expect(result.mode).toBe("local");
    expect(result.url).toBe("http://localhost:9911/mcp");

    delete process.env.WORMBASE_DASHBOARD_URL;
    result = getMcpServerUrl();
    expect(result.mode).toBe("local");
    expect(result.url).toBe("http://localhost:9911/mcp");
  });
});
