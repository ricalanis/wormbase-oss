/**
 * Dashboard URL helpers (W7.A4) — server-only.
 *
 * The dashboard is reachable at one of two kinds of origins at any
 * given time:
 *
 *   * ``http://localhost:3000`` — local-dev or single-machine demo. The
 *     MCP server (worm-core, port 9911) is reachable on the same host
 *     by Claude Desktop directly.
 *
 *   * ``https://<slug>.trycloudflare.com`` (or any non-localhost https
 *     origin) — a cloudflared tunnel exposing the dashboard for remote
 *     demos. Claude Desktop can NOT reach localhost:9911 from a remote
 *     machine, so the snippet must point at the tunnel host. We add a
 *     Next.js rewrite from ``/mcp/*`` → worm-core ``9911/mcp/*`` so the
 *     tunnel transparently proxies the MCP traffic.
 *
 * These helpers are import-only on the server. They read
 * ``WORMBASE_DASHBOARD_URL`` from ``process.env`` (set in compose) and
 * never leak it to the browser. Callers that need the URL on the client
 * should pass it in via component props after computing it server-side
 * (see ``app/(app)/mcp/page.tsx`` for the canonical pattern).
 *
 * This module reads ``process.env`` at call time (not at module-load
 * time), so tests can stub the env per-case without re-importing.
 */

/** Default fallback when ``WORMBASE_DASHBOARD_URL`` is unset. */
const DEFAULT_DASHBOARD_URL = "http://localhost:3000";

/** The MCP server port worm-core binds when ``WORMBASE_MCP_ENABLED=1``. */
const DEFAULT_MCP_PORT = "9911";

function getMcpPort(): string {
  const raw = (process.env.WORMBASE_MCP_PORT ?? "").trim();
  return raw.length > 0 ? raw : DEFAULT_MCP_PORT;
}

export interface McpServerUrlInfo {
  /** The URL Claude Desktop should POST to in its config snippet. */
  url: string;
  /**
   * ``"local"`` when the URL targets ``localhost`` directly (only works
   * when Claude Desktop runs on the same machine as worm-core);
   * ``"tunnel"`` when the URL goes through the dashboard origin (a
   * cloudflared tunnel proxy in front of the Next.js rewrite, reachable
   * from remote machines).
   */
  mode: "local" | "tunnel";
  /** The dashboard origin this URL was derived from, after canonicalization. */
  dashboardOrigin: string;
}

/**
 * Return the dashboard's public origin, canonicalized (no trailing
 * slash). Reads ``WORMBASE_DASHBOARD_URL`` from the environment;
 * defaults to ``http://localhost:3000`` when unset.
 */
export function getDashboardOrigin(): string {
  const raw = (process.env.WORMBASE_DASHBOARD_URL ?? "").trim();
  const value = raw.length > 0 ? raw : DEFAULT_DASHBOARD_URL;
  return canonicalizeOrigin(value);
}

/**
 * Return the URL Claude Desktop should hit for MCP traffic, plus a
 * ``mode`` indicator the panel uses to render a "via tunnel" / "local
 * only" badge.
 *
 * Rules:
 *   * If ``WORMBASE_DASHBOARD_URL`` resolves to a localhost origin →
 *     return ``http://localhost:<MCP_PORT>/mcp`` so Claude Desktop
 *     bypasses the dashboard and talks to worm-core directly. Mode
 *     ``"local"``.
 *   * Otherwise → return ``<origin>/mcp``. Mode ``"tunnel"``. The
 *     Next.js rewrite (next.config.mjs) routes ``/mcp/:path*`` to
 *     worm-core internally, so the tunnel proxies MCP transparently.
 */
export function getMcpServerUrl(): McpServerUrlInfo {
  const origin = getDashboardOrigin();
  if (isLocalhost(origin)) {
    return {
      url: `http://localhost:${getMcpPort()}/mcp`,
      mode: "local",
      dashboardOrigin: origin,
    };
  }
  return {
    url: `${origin}/mcp`,
    mode: "tunnel",
    dashboardOrigin: origin,
  };
}

function canonicalizeOrigin(value: string): string {
  // Strip trailing slashes; keep scheme + host[:port] intact.
  return value.replace(/\/+$/, "");
}

function isLocalhost(origin: string): boolean {
  // ``URL`` is the most robust parser available in the Node runtime;
  // fall back to a substring check if the origin is malformed (e.g. a
  // bare hostname without a scheme — should never happen in practice
  // since compose seeds the env with a full URL).
  try {
    const u = new URL(origin);
    const host = u.hostname;
    return (
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "0.0.0.0" ||
      host === "[::1]"
    );
  } catch {
    return /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(origin);
  }
}
