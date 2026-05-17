import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import {
  TestConnectionPanel,
  configIsComplete,
} from "../TestConnectionPanel";

describe("TestConnectionPanel (W2.A5)", () => {
  let originalFetch: typeof globalThis.fetch | undefined;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    if (originalFetch) {
      globalThis.fetch = originalFetch;
    }
  });

  it("calls /api/v1/connectors/test/{kind} with the supplied config", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    globalThis.fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(url), init });
      return new Response(
        JSON.stringify({
          ok: true,
          kind: "postgres",
          handle_id: "abc123",
          version: "16.2",
          hash: "deadbeef1234",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof globalThis.fetch;

    render(
      <TestConnectionPanel
        kind="postgres"
        config={{ dsn: "postgres://x:y@h/db" }}
      />,
    );
    fireEvent.click(screen.getByTestId("test-connection-button"));
    await waitFor(() => {
      expect(screen.getByTestId("test-connection-success")).toBeInTheDocument();
    });
    expect(calls.length).toBe(1);
    expect(calls[0].url).toBe("/api/v1/connectors/test/postgres");
    const body = JSON.parse(String(calls[0].init?.body ?? "{}"));
    expect(body.config).toEqual({ dsn: "postgres://x:y@h/db" });
    expect(screen.getByTestId("test-connection-receipt").textContent).toMatch(
      /deadbeef1234/,
    );
  });

  it("surfaces an honest failure with the upstream error message", async () => {
    globalThis.fetch = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          ok: false,
          kind: "postgres",
          error: "postgres authenticate failed: connection refused",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof globalThis.fetch;

    render(<TestConnectionPanel kind="postgres" config={{ dsn: "bad" }} />);
    fireEvent.click(screen.getByTestId("test-connection-button"));
    await waitFor(() => {
      expect(screen.getByTestId("test-connection-failure")).toBeInTheDocument();
    });
    expect(screen.getByTestId("test-connection-failure").textContent).toMatch(
      /connection refused/,
    );
  });

  it("configIsComplete returns false when a required field is empty", () => {
    expect(
      configIsComplete(
        [{ name: "dsn", label: "DSN", type: "password", required: true }],
        {},
      ),
    ).toBe(false);
    expect(
      configIsComplete(
        [{ name: "dsn", label: "DSN", type: "password", required: true }],
        { dsn: "  " },
      ),
    ).toBe(false);
    expect(
      configIsComplete(
        [{ name: "dsn", label: "DSN", type: "password", required: true }],
        { dsn: "postgres://..." },
      ),
    ).toBe(true);
  });
});
