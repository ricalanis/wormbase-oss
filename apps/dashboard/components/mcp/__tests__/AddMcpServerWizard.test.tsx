/**
 * Tests for AddMcpServerWizard (W2.A9).
 *
 * Covers: collapsed-by-default CTA toggle, preset-pick prefilling,
 * custom kind validation, success path POSTs the canonical body to
 * /api/v1/mcp/presets, errors surface inline.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AddMcpServerWizard } from "../AddMcpServerWizard";

describe("AddMcpServerWizard", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders only the CTA until clicked", () => {
    render(<AddMcpServerWizard />);
    expect(screen.getByTestId("add-mcp-server-cta")).toBeInTheDocument();
    expect(
      screen.queryByTestId("add-mcp-server-wizard"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("add-mcp-server-cta"));
    expect(screen.getByTestId("add-mcp-server-wizard")).toBeInTheDocument();
  });

  it("prefills the server URL when picking a curated preset", () => {
    render(<AddMcpServerWizard />);
    fireEvent.click(screen.getByTestId("add-mcp-server-cta"));
    fireEvent.click(screen.getByTestId("preset-atlassian"));
    const url = screen.getByTestId("server-url-input") as HTMLInputElement;
    expect(url.value).toContain("atlassian");
  });

  it("requires a custom kind when 'custom' is picked", async () => {
    render(<AddMcpServerWizard />);
    fireEvent.click(screen.getByTestId("add-mcp-server-cta"));
    fireEvent.click(screen.getByTestId("preset-custom"));
    fireEvent.change(screen.getByTestId("server-url-input"), {
      target: { value: "https://example.com/mcp" },
    });
    const submit = screen.getByTestId(
      "add-mcp-server-submit",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("custom-kind-input"), {
      target: { value: "gworkspace" },
    });
    expect(
      (screen.getByTestId("add-mcp-server-submit") as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("POSTs the preset to /api/v1/mcp/presets and surfaces success", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          source_id: "33333333-3333-3333-3333-333333333333",
          source_kind: "mcp:notion",
          uri: "https://mcp.notion.com/mcp",
          description: "",
          entry_ids: ["e1", "e2", "e3", "e4"],
        }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const onRegistered = vi.fn();

    render(<AddMcpServerWizard onRegistered={onRegistered} />);
    fireEvent.click(screen.getByTestId("add-mcp-server-cta"));
    // Default preset is the first one (notion).
    fireEvent.submit(
      screen
        .getByTestId("add-mcp-server-submit")
        .closest("form") as HTMLFormElement,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/mcp/presets");
    expect((init as RequestInit).method).toBe("POST");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({
      kind: "notion",
      serverUrl: "https://mcp.notion.com/mcp",
      suggestedDomain: "general",
      suggestedClassification: "internal",
    });

    await waitFor(() =>
      expect(
        screen.getByTestId("add-mcp-server-success"),
      ).toBeInTheDocument(),
    );
    expect(onRegistered).toHaveBeenCalledWith(
      "33333333-3333-3333-3333-333333333333",
      "mcp:notion",
    );
  });

  it("surfaces an upstream error inline rather than silently failing", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      text: async () =>
        JSON.stringify({ error: "worm_core_error", message: "down" }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<AddMcpServerWizard />);
    fireEvent.click(screen.getByTestId("add-mcp-server-cta"));
    fireEvent.submit(
      screen
        .getByTestId("add-mcp-server-submit")
        .closest("form") as HTMLFormElement,
    );

    await waitFor(() =>
      expect(screen.getByTestId("add-mcp-server-error")).toBeInTheDocument(),
    );
  });
});
