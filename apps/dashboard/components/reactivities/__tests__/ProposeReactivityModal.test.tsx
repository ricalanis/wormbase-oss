/**
 * Tests for ProposeReactivityModal (W5.A5).
 *
 * Covers:
 *   - compose stage renders the textarea + "Sketch it" CTA
 *   - "Sketch it" POSTs to /api/v1/reactivities/propose?preview=1 and
 *     advances to the preview stage
 *   - the preview stage renders the parsed sketch + confidence
 *   - low-confidence sketches surface the warning banner
 *   - "Confirm propose" POSTs without ?preview=1 and fires onProposed
 *   - "Refine description" returns to the compose stage
 *   - "Reject" closes the modal
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ProposeReactivityModal } from "../ProposeReactivityModal";

const HIGH_CONF_SKETCH = {
  id: "prop_revenue_abcd1234",
  name: "ping me whenever someone mentions revenue",
  description: "ping me whenever someone mentions revenue",
  scope: "person",
  predicate_spec: { entry_kind: "chat_received", topic: "revenue" },
  condition_spec: {
    per_owner_per_day: 3,
    per_domain_per_day: 10,
    per_tenant_per_day: 50,
  },
  action_spec: { kind: "dm_owner" },
  confidence: 0.85,
  proposed_by: "dashboard-admin",
};

const LOW_CONF_SKETCH = {
  ...HIGH_CONF_SKETCH,
  predicate_spec: { entry_kind: "chat_received", topic: null },
  confidence: 0.3,
};

describe("ProposeReactivityModal", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders compose stage by default", () => {
    render(<ProposeReactivityModal onClose={() => {}} />);
    expect(screen.getByTestId("propose-reactivity-modal")).toBeInTheDocument();
    expect(
      screen.getByTestId("propose-reactivity-description"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("propose-reactivity-preview")).toBeInTheDocument();
  });

  it("Sketch it POSTs to ?preview=1 and advances to the preview stage", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ sketch: HIGH_CONF_SKETCH }),
      json: async () => ({ sketch: HIGH_CONF_SKETCH }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ProposeReactivityModal onClose={() => {}} />);
    fireEvent.change(
      screen.getByTestId("propose-reactivity-description"),
      { target: { value: "ping me on revenue" } },
    );
    fireEvent.click(screen.getByTestId("propose-reactivity-preview"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/reactivities/propose?preview=1",
    );
    await waitFor(() =>
      expect(screen.getByTestId("propose-reactivity-sketch")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("propose-reactivity-sketch-id")).toHaveTextContent(
      HIGH_CONF_SKETCH.id,
    );
  });

  it("low-confidence sketches surface a warning banner", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ sketch: LOW_CONF_SKETCH }),
      json: async () => ({ sketch: LOW_CONF_SKETCH }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ProposeReactivityModal onClose={() => {}} />);
    fireEvent.change(
      screen.getByTestId("propose-reactivity-description"),
      { target: { value: "do something" } },
    );
    fireEvent.click(screen.getByTestId("propose-reactivity-preview"));
    await waitFor(() =>
      expect(
        screen.getByTestId("propose-reactivity-low-confidence"),
      ).toBeInTheDocument(),
    );
  });

  it("Confirm propose POSTs without ?preview=1 and fires onProposed", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ sketch: HIGH_CONF_SKETCH }),
      json: async () => ({ sketch: HIGH_CONF_SKETCH }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 201,
        text: async () =>
          JSON.stringify({ sketch: HIGH_CONF_SKETCH, persisted: true }),
        json: async () => ({ sketch: HIGH_CONF_SKETCH, persisted: true }),
      });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const onProposed = vi.fn();
    render(<ProposeReactivityModal onClose={() => {}} onProposed={onProposed} />);
    fireEvent.change(
      screen.getByTestId("propose-reactivity-description"),
      { target: { value: "ping me on revenue" } },
    );
    fireEvent.click(screen.getByTestId("propose-reactivity-preview"));
    await waitFor(() =>
      expect(screen.getByTestId("propose-reactivity-sketch")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("propose-reactivity-confirm"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/reactivities/propose");
    await waitFor(() => expect(onProposed).toHaveBeenCalled());
    expect(screen.getByTestId("propose-reactivity-done")).toBeInTheDocument();
  });

  it("Refine description goes back to the compose stage", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ sketch: HIGH_CONF_SKETCH }),
      json: async () => ({ sketch: HIGH_CONF_SKETCH }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ProposeReactivityModal onClose={() => {}} />);
    fireEvent.change(
      screen.getByTestId("propose-reactivity-description"),
      { target: { value: "ping me" } },
    );
    fireEvent.click(screen.getByTestId("propose-reactivity-preview"));
    await waitFor(() =>
      expect(screen.getByTestId("propose-reactivity-sketch")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("propose-reactivity-refine"));
    await waitFor(() =>
      expect(
        screen.getByTestId("propose-reactivity-description"),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("propose-reactivity-sketch")).not.toBeInTheDocument();
  });

  it("Close fires onClose", () => {
    const onClose = vi.fn();
    render(<ProposeReactivityModal onClose={onClose} />);
    fireEvent.click(screen.getByTestId("propose-reactivity-close"));
    expect(onClose).toHaveBeenCalled();
  });
});
