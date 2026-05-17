/**
 * WS5 S4 — AskTheWormPanel.
 *
 * Mocks fetch, asserts the submit + render-response cycle. Today the
 * /api/ask response is the honest stub explaining that the worm-core
 * /api/v1/ask handler is a v1.5 task; the panel renders that as a
 * "wiring note" tile.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { AskTheWormPanel } from "../../components/dashboard/AskTheWormPanel";
import type { AskResponseBody } from "../../app/api/ask/route";

const STUB_RESPONSE: AskResponseBody = {
  ok: true,
  answer:
    "The Ask The Worm endpoint is wired to the dashboard. The worm-core HTTP /api/v1/ask handler is a v1.5 task.",
  references: [],
  passthrough: false,
};

describe("AskTheWormPanel (WS5 S4)", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the panel with textarea, submit button, and intro copy", () => {
    render(<AskTheWormPanel />);
    expect(screen.getByTestId("ask-the-worm-panel")).toBeTruthy();
    expect(screen.getByTestId("ask-the-worm-input")).toBeTruthy();
    expect(screen.getByTestId("ask-the-worm-submit")).toBeTruthy();
    expect(screen.getByText(/What do you want to know/)).toBeTruthy();
  });

  it("does NOT call fetch when the textarea is empty", async () => {
    render(<AskTheWormPanel />);
    fireEvent.click(screen.getByTestId("ask-the-worm-submit"));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("ask-the-worm-error")).toBeTruthy();
  });

  it("POSTs the question to /api/ask and renders the response", async () => {
    fetchMock.mockResolvedValueOnce({
      json: async () => STUB_RESPONSE,
    } as Response);

    render(<AskTheWormPanel />);
    const input = screen.getByTestId("ask-the-worm-input") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "What's our Q3 net revenue?" } });
    fireEvent.click(screen.getByTestId("ask-the-worm-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("ask-the-worm-response")).toBeTruthy();
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/ask",
      expect.objectContaining({
        method: "POST",
        headers: { "content-type": "application/json" },
      }),
    );
    const callArgs = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(String(callArgs.body))).toEqual({
      question: "What's our Q3 net revenue?",
    });

    const respEl = screen.getByTestId("ask-the-worm-response");
    expect(respEl.getAttribute("data-passthrough")).toBe("false");
    expect(respEl.textContent).toContain("v1.5");
    expect(respEl.textContent).toContain("wiring note");
  });

  it("renders 'answer' eyebrow when the upstream is a real pass-through", async () => {
    const passthrough: AskResponseBody = {
      ok: true,
      answer: "Q3 net revenue was $4.2M, computed by sum(stripe.charges).",
      references: [{ kind: "kpi", ref: "q3_net_revenue" }],
      passthrough: true,
    };
    fetchMock.mockResolvedValueOnce({
      json: async () => passthrough,
    } as Response);

    render(<AskTheWormPanel />);
    fireEvent.change(screen.getByTestId("ask-the-worm-input"), {
      target: { value: "What's Q3 net revenue?" },
    });
    fireEvent.click(screen.getByTestId("ask-the-worm-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("ask-the-worm-response")).toBeTruthy();
    });
    const respEl = screen.getByTestId("ask-the-worm-response");
    expect(respEl.getAttribute("data-passthrough")).toBe("true");
    expect(respEl.textContent).toContain("answer");
    expect(respEl.textContent).toContain("kpi · q3_net_revenue");
  });

  it("surfaces a network error in the panel without claiming an answer", async () => {
    fetchMock.mockRejectedValueOnce(new Error("connection refused"));
    render(<AskTheWormPanel />);
    fireEvent.change(screen.getByTestId("ask-the-worm-input"), {
      target: { value: "ping" },
    });
    fireEvent.click(screen.getByTestId("ask-the-worm-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("ask-the-worm-error")).toBeTruthy();
    });
    expect(screen.queryByTestId("ask-the-worm-response")).toBeNull();
    expect(screen.getByTestId("ask-the-worm-error").textContent).toContain(
      "connection refused",
    );
  });
});
