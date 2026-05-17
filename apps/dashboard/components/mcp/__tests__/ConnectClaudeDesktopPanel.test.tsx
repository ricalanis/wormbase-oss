/**
 * Tests for ConnectClaudeDesktopPanel (W2.A9 + W7.A4).
 *
 * Covers the wire-level acceptance: clicking "generate token" POSTs to
 * /api/v1/mcp/tokens, then renders a copy-paste config snippet whose
 * shape Claude Desktop expects ({mcpServers:{wormbase:{transport,url,
 * headers:{Authorization}}}}).
 *
 * W7.A4 extends with:
 *   * snippet uses ``localhost:9911/mcp`` when the dashboard is local
 *   * snippet uses ``<tunnel>.trycloudflare.com/mcp`` when the dashboard
 *     is exposed through a cloudflared tunnel
 *   * a "via tunnel" / "local only" badge surfaces the mode visibly
 *   * the produced JSON is a valid Claude Desktop config in both modes
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  ConnectClaudeDesktopPanel,
  buildSnippet,
  isLocalhostUrl,
} from "../ConnectClaudeDesktopPanel";

describe("buildSnippet", () => {
  it("produces the exact Claude Desktop config shape", () => {
    const json = buildSnippet(
      "wormbase",
      "http://localhost:9911/mcp",
      "abc.def",
    );
    const parsed = JSON.parse(json);
    expect(parsed).toEqual({
      mcpServers: {
        wormbase: {
          transport: "http",
          url: "http://localhost:9911/mcp",
          headers: {
            Authorization: "Bearer abc.def",
          },
        },
      },
    });
  });
});

describe("ConnectClaudeDesktopPanel", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders the panel with a generate-token CTA but no snippet initially", () => {
    render(<ConnectClaudeDesktopPanel />);
    expect(screen.getByTestId("connect-claude-desktop")).toBeInTheDocument();
    expect(screen.getByTestId("connect-claude-generate")).toBeInTheDocument();
    expect(
      screen.queryByTestId("connect-claude-snippet"),
    ).not.toBeInTheDocument();
  });

  it("POSTs to /api/v1/mcp/tokens with the label and renders the snippet", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          token: "tok.sig",
          person_id: "00000000-0000-0000-0000-000000000abc",
          tenant_slug: "baseworm",
          ttl_seconds: 3600,
          issued_at: "2026-04-28T00:00:00.000Z",
          expires_at: "2026-04-28T01:00:00.000Z",
          label: "Carol",
        }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<ConnectClaudeDesktopPanel mcpUrl="http://localhost:9911/mcp" />);
    fireEvent.change(screen.getByTestId("connect-claude-label-input"), {
      target: { value: "Carol" },
    });
    fireEvent.click(screen.getByTestId("connect-claude-generate"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/mcp/tokens");
    expect((init as RequestInit).method).toBe("POST");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({ label: "Carol" });

    await waitFor(() =>
      expect(screen.getByTestId("connect-claude-snippet")).toBeInTheDocument(),
    );
    const snippetText =
      screen.getByTestId("connect-claude-snippet").textContent ?? "";
    expect(snippetText).toContain('"transport"');
    expect(snippetText).toContain('"http"');
    expect(snippetText).toContain('"Bearer tok.sig"');
    expect(snippetText).toContain("http://localhost:9911/mcp");
  });

  it("surfaces an error when the issuance endpoint returns non-OK", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: async () =>
        JSON.stringify({ error: "no_admin_person", message: "no admin" }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<ConnectClaudeDesktopPanel />);
    fireEvent.click(screen.getByTestId("connect-claude-generate"));

    await waitFor(() =>
      expect(screen.getByTestId("connect-claude-error")).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("connect-claude-snippet"),
    ).not.toBeInTheDocument();
  });
});

// W7.A4 — mode badge + tunnel-aware snippet rendering
describe("ConnectClaudeDesktopPanel — mode badge", () => {
  it("renders 'local only' when the URL is localhost", () => {
    render(
      <ConnectClaudeDesktopPanel mcpUrl="http://localhost:9911/mcp" />,
    );
    const badge = screen.getByTestId("connect-claude-mode-badge");
    expect(badge).toBeInTheDocument();
    expect(badge.textContent?.toLowerCase()).toContain("local only");
    expect(badge.getAttribute("data-mode")).toBe("local");
  });

  it("renders 'via tunnel' when the URL is a cloudflared tunnel", () => {
    render(
      <ConnectClaudeDesktopPanel
        mcpUrl="https://demo-1234.trycloudflare.com/mcp"
        mode="tunnel"
      />,
    );
    const badge = screen.getByTestId("connect-claude-mode-badge");
    expect(badge).toBeInTheDocument();
    expect(badge.textContent?.toLowerCase()).toContain("via tunnel");
    expect(badge.getAttribute("data-mode")).toBe("tunnel");
  });

  it("auto-detects tunnel mode from the URL when the prop is omitted", () => {
    render(
      <ConnectClaudeDesktopPanel mcpUrl="https://abc.trycloudflare.com/mcp" />,
    );
    const badge = screen.getByTestId("connect-claude-mode-badge");
    expect(badge.getAttribute("data-mode")).toBe("tunnel");
  });
});

// W7.A4 — snippet content per mode
describe("ConnectClaudeDesktopPanel — snippet URL per mode", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  function mockTokenResponse(): typeof fetch {
    return vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          token: "tok.sig",
          person_id: "00000000-0000-0000-0000-000000000abc",
          tenant_slug: "baseworm",
          ttl_seconds: 3600,
          issued_at: "2026-04-28T00:00:00.000Z",
          expires_at: "2026-04-28T01:00:00.000Z",
          label: "Carol",
        }),
    }) as unknown as typeof fetch;
  }

  it("local mode → snippet contains http://localhost:9911/mcp", async () => {
    globalThis.fetch = mockTokenResponse();
    render(
      <ConnectClaudeDesktopPanel
        mcpUrl="http://localhost:9911/mcp"
        mode="local"
      />,
    );
    fireEvent.click(screen.getByTestId("connect-claude-generate"));
    await waitFor(() =>
      expect(screen.getByTestId("connect-claude-snippet")).toBeInTheDocument(),
    );
    const snippet =
      screen.getByTestId("connect-claude-snippet").textContent ?? "";
    expect(snippet).toContain("http://localhost:9911/mcp");
    // JSON snippet is a valid Claude Desktop config
    const parsed = JSON.parse(snippet);
    expect(parsed.mcpServers.wormbase.url).toBe("http://localhost:9911/mcp");
    expect(parsed.mcpServers.wormbase.transport).toBe("http");
    expect(parsed.mcpServers.wormbase.headers.Authorization).toMatch(
      /^Bearer /,
    );
  });

  it("tunnel mode → snippet contains the trycloudflare URL + 'via tunnel' badge", async () => {
    globalThis.fetch = mockTokenResponse();
    render(
      <ConnectClaudeDesktopPanel
        mcpUrl="https://demo-1234.trycloudflare.com/mcp"
        mode="tunnel"
      />,
    );
    fireEvent.click(screen.getByTestId("connect-claude-generate"));
    await waitFor(() =>
      expect(screen.getByTestId("connect-claude-snippet")).toBeInTheDocument(),
    );
    const snippet =
      screen.getByTestId("connect-claude-snippet").textContent ?? "";
    expect(snippet).toContain("https://demo-1234.trycloudflare.com/mcp");
    expect(snippet).not.toContain("localhost");
    // Badge surfaces the tunnel mode visibly
    const badge = screen.getByTestId("connect-claude-mode-badge");
    expect(badge.textContent?.toLowerCase()).toContain("via tunnel");
    // JSON snippet is a valid Claude Desktop config
    const parsed = JSON.parse(snippet);
    expect(parsed.mcpServers.wormbase.url).toBe(
      "https://demo-1234.trycloudflare.com/mcp",
    );
  });
});

// W7.A4 — small URL helper used to default the badge
describe("isLocalhostUrl", () => {
  it("returns true for localhost variants", () => {
    expect(isLocalhostUrl("http://localhost:9911/mcp")).toBe(true);
    expect(isLocalhostUrl("http://127.0.0.1:9911/mcp")).toBe(true);
    expect(isLocalhostUrl("http://0.0.0.0:9911/mcp")).toBe(true);
  });

  it("returns false for tunnel and public URLs", () => {
    expect(isLocalhostUrl("https://abc.trycloudflare.com/mcp")).toBe(false);
    expect(isLocalhostUrl("https://wormbase.example.com/mcp")).toBe(false);
  });

  it("survives malformed URLs without throwing", () => {
    expect(() => isLocalhostUrl("not-a-url")).not.toThrow();
    expect(isLocalhostUrl("not-a-url")).toBe(false);
  });
});
