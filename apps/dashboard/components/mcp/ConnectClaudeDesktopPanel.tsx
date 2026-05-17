"use client";
/**
 * ConnectClaudeDesktopPanel — W2.A9.
 *
 * "Connect Claude Desktop" surface on /mcp. Generates a Person-scoped
 * compact bearer token via ``POST /api/v1/mcp/tokens`` and renders a
 * copy-paste config snippet:
 *
 *   {
 *     "mcpServers": {
 *       "wormbase": {
 *         "transport": "http",
 *         "url": "<NEXT_PUBLIC_WORMBASE_MCP_URL>",
 *         "headers": { "Authorization": "Bearer <token>" }
 *       }
 *     }
 *   }
 *
 * Flow:
 *   1. Operator clicks "Generate token"
 *   2. We POST /api/v1/mcp/tokens with optional {label}; the dashboard
 *      route resolves the current admin via getCurrentPerson and proxies
 *      to worm-core.
 *   3. We render a JSON snippet + a copy-to-clipboard button.
 *   4. Token is shown ONCE — the panel never persists it client-side.
 *      A refresh forgets it (intentional: re-issue if you lose track).
 *
 * The panel is server-side render-able as a placeholder (the button is
 * the only interactive surface), so dropping it into the /mcp tab
 * doesn't disturb its RSC story.
 */

import { useCallback, useState } from "react";

const DEFAULT_MCP_URL = "http://localhost:9911/mcp";

/**
 * Snippet-mode marker (W7.A4):
 *   * ``"local"`` — snippet points at ``http://localhost:<port>/mcp``;
 *     only works when Claude Desktop runs on the same machine as the
 *     worm-core service.
 *   * ``"tunnel"`` — snippet points at the dashboard's public origin
 *     (typically cloudflared); a Next.js rewrite proxies ``/mcp``
 *     traffic to worm-core internally.
 */
export type ConnectClaudeMode = "local" | "tunnel";

export interface ConnectClaudeDesktopPanelProps {
  /**
   * The MCP server URL. Server components should compute this with
   * ``getMcpServerUrl()`` and pass it in. The browser sees only the
   * public URL; tenancy is enforced by the bearer token, not by the
   * URL. Falls back to ``http://localhost:9911/mcp`` when unset.
   */
  mcpUrl?: string;
  /**
   * Default config-key name in the rendered snippet (the key under
   * `mcpServers` in Claude Desktop's config). Defaults to "wormbase".
   */
  configKey?: string;
  /**
   * Whether the URL is a localhost direct-to-worm-core link (``"local"``)
   * or a tunnel-routed link (``"tunnel"``). Drives the explanatory
   * badge rendered next to the snippet.
   */
  mode?: ConnectClaudeMode;
}

interface TokenResponse {
  token: string;
  person_id: string;
  tenant_slug: string;
  ttl_seconds: number;
  issued_at: string;
  expires_at: string;
  label: string;
}

type Status = "idle" | "issuing" | "ok" | "error";

export function ConnectClaudeDesktopPanel({
  mcpUrl,
  configKey = "wormbase",
  mode,
}: ConnectClaudeDesktopPanelProps) {
  const [label, setLabel] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [errMsg, setErrMsg] = useState<string | null>(null);
  const [token, setToken] = useState<TokenResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const resolvedUrl =
    mcpUrl ??
    (typeof process !== "undefined"
      ? process.env.NEXT_PUBLIC_WORMBASE_MCP_URL ?? DEFAULT_MCP_URL
      : DEFAULT_MCP_URL);
  // Default the badge from the URL shape when an explicit ``mode`` was
  // not threaded through. This keeps the panel useful in legacy
  // contexts (e.g. unit tests that stub ``mcpUrl`` directly) without
  // the caller having to also pass ``mode``.
  const resolvedMode: ConnectClaudeMode =
    mode ?? (isLocalhostUrl(resolvedUrl) ? "local" : "tunnel");

  const snippet = token
    ? buildSnippet(configKey, resolvedUrl, token.token)
    : null;

  const handleGenerate = useCallback(async () => {
    setStatus("issuing");
    setErrMsg(null);
    setToken(null);
    setCopied(false);
    try {
      const res = await fetch("/api/v1/mcp/tokens", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label }),
      });
      const text = await res.text();
      if (!res.ok) {
        setStatus("error");
        setErrMsg(text.slice(0, 240) || `HTTP ${res.status}`);
        return;
      }
      const json = JSON.parse(text) as TokenResponse;
      setToken(json);
      setStatus("ok");
    } catch (err) {
      setStatus("error");
      setErrMsg((err as Error).message);
    }
  }, [label]);

  const handleCopy = useCallback(async () => {
    if (!snippet) return;
    try {
      if (
        typeof navigator !== "undefined" &&
        navigator.clipboard?.writeText
      ) {
        await navigator.clipboard.writeText(snippet);
        setCopied(true);
        setTimeout(() => setCopied(false), 2500);
      }
    } catch {
      // Clipboard may be denied; the textarea is selectable as a fallback.
    }
  }, [snippet]);

  return (
    <section
      data-testid="connect-claude-desktop"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 12,
        border: "1px solid var(--wb-color-aged-ink)",
        padding: "16px 20px",
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Outbound · MCP
        </span>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <h3
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontSize: 18,
              fontWeight: 500,
            }}
          >
            Connect Claude Desktop
          </h3>
          <ModeBadge mode={resolvedMode} url={resolvedUrl} />
        </div>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          Generate a Person-scoped bearer token, then paste the snippet
          into Claude Desktop&apos;s <code>claude_desktop_config.json</code>{" "}
          to expose this tenant&apos;s tools, resources, and prompts to
          your Claude session.
        </p>
      </header>

      <label
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
          fontFamily: "var(--wb-font-serif)",
          fontSize: 13,
        }}
      >
        <span>
          Token label
          <span
            style={{
              marginLeft: 6,
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
              fontSize: 12,
            }}
          >
            (optional · audited in /mcp)
          </span>
        </span>
        <input
          data-testid="connect-claude-label-input"
          type="text"
          value={label}
          placeholder="e.g. Carol&rsquo;s MacBook"
          onChange={(e) => setLabel(e.target.value)}
          style={{
            padding: "6px 8px",
            border: "1px solid var(--wb-color-rule-line)",
            fontFamily: "var(--wb-font-mono)",
            fontSize: 13,
            background: "var(--wb-color-paper)",
          }}
        />
      </label>

      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <button
          type="button"
          data-testid="connect-claude-generate"
          onClick={handleGenerate}
          disabled={status === "issuing"}
          style={{
            fontFamily: "var(--wb-font-mono)",
            fontSize: 12,
            padding: "8px 14px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-paper)",
            color: "var(--wb-color-aged-ink)",
            cursor: status === "issuing" ? "default" : "pointer",
            opacity: status === "issuing" ? 0.7 : 1,
          }}
        >
          {status === "issuing"
            ? "issuing token…"
            : status === "ok"
              ? "regenerate token"
              : "generate token"}
        </button>
        {token ? (
          <span
            data-testid="connect-claude-token-meta"
            className="wb-mono"
            style={{
              fontSize: 11,
              color: "var(--wb-color-hash-gray)",
            }}
          >
            scope · {token.tenant_slug} · person {token.person_id.slice(0, 8)}
            … · expires{" "}
            {new Date(token.expires_at).toISOString().slice(0, 10)}
          </span>
        ) : null}
      </div>

      {status === "error" && errMsg ? (
        <p
          data-testid="connect-claude-error"
          style={{
            margin: 0,
            color: "var(--wb-color-aged-ink)",
            fontFamily: "var(--wb-font-mono)",
            fontSize: 12,
            background: "var(--wb-color-paper-edge)",
            padding: "8px 12px",
            border: "1px solid var(--wb-color-rule-line)",
          }}
        >
          {errMsg}
        </p>
      ) : null}

      {snippet ? (
        <>
          <pre
            data-testid="connect-claude-snippet"
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-mono)",
              fontSize: 12,
              padding: "12px 14px",
              background: "var(--wb-color-paper-edge)",
              border: "1px solid var(--wb-color-rule-line)",
              overflowX: "auto",
              whiteSpace: "pre",
            }}
          >
            {snippet}
          </pre>
          <div style={{ display: "flex", gap: 10 }}>
            <button
              type="button"
              data-testid="connect-claude-copy"
              onClick={handleCopy}
              style={{
                fontFamily: "var(--wb-font-mono)",
                fontSize: 11,
                padding: "6px 10px",
                border: "1px solid var(--wb-color-rule-line)",
                background: "var(--wb-color-paper)",
                color: "var(--wb-color-aged-ink)",
                cursor: "pointer",
              }}
            >
              {copied ? "copied ✓" : "copy snippet"}
            </button>
            <span
              className="wb-mono"
              style={{
                fontSize: 11,
                color: "var(--wb-color-hash-gray)",
                alignSelf: "center",
              }}
            >
              save in <code>~/Library/Application Support/Claude/claude_desktop_config.json</code> &middot; restart Claude Desktop
            </span>
          </div>
        </>
      ) : null}
    </section>
  );
}

export function buildSnippet(
  configKey: string,
  url: string,
  token: string,
): string {
  const obj = {
    mcpServers: {
      [configKey]: {
        transport: "http",
        url,
        headers: {
          Authorization: `Bearer ${token}`,
        },
      },
    },
  };
  return JSON.stringify(obj, null, 2);
}

/**
 * Best-effort localhost test for the snippet URL. Used to default the
 * mode badge when the caller didn't pass an explicit ``mode`` prop.
 */
export function isLocalhostUrl(url: string): boolean {
  try {
    const u = new URL(url);
    const host = u.hostname;
    return (
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "0.0.0.0" ||
      host === "[::1]"
    );
  } catch {
    return /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(url);
  }
}

function ModeBadge({
  mode,
  url,
}: {
  mode: ConnectClaudeMode;
  url: string;
}) {
  const isTunnel = mode === "tunnel";
  const label = isTunnel ? "via tunnel" : "local only";
  const hint = isTunnel
    ? `proxied through ${safeHost(url)} → worm-core /mcp`
    : "Claude Desktop must run on this machine";
  return (
    <span
      data-testid="connect-claude-mode-badge"
      data-mode={mode}
      title={hint}
      className="wb-mono"
      style={{
        fontSize: 10,
        letterSpacing: "0.14em",
        textTransform: "uppercase",
        padding: "2px 8px",
        border: "1px solid var(--wb-color-rule-line)",
        background: isTunnel
          ? "var(--wb-color-paper-edge)"
          : "var(--wb-color-paper)",
        color: "var(--wb-color-aged-ink)",
      }}
    >
      {label}
    </span>
  );
}

function safeHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
