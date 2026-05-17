/**
 * Tests for ApproveExperimentButton + RejectExperimentButton (W2.A9).
 *
 * Asserts:
 *   * idle / pending / ok / error status transitions
 *   * the POST body and URL match the worm-core route shape
 *   * upstream errors surface inline rather than silently failing
 *   * onResolved fires with the resolved outcome on success
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ApproveExperimentButton } from "../ApproveExperimentButton";
import { RejectExperimentButton } from "../RejectExperimentButton";

const EXP_ID = "11111111-1111-1111-1111-111111111111";

describe("ApproveExperimentButton", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders idle by default", () => {
    render(<ApproveExperimentButton experimentId={EXP_ID} />);
    const btn = screen.getByTestId(`approve-experiment-${EXP_ID}`);
    expect(btn).toHaveAttribute("data-status", "idle");
    expect(btn).toHaveTextContent(/approve/i);
  });

  it("POSTs to /api/v1/experiments/{id}/approve and fires onResolved on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          experiment_id: EXP_ID,
          outcome: "keep",
          rationale: "stub",
          entry_ids: ["e1", "e2", "e3", "e4"],
        }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const onResolved = vi.fn();

    render(
      <ApproveExperimentButton
        experimentId={EXP_ID}
        rationale="operator-approved"
        observedDelta={0.123}
        onResolved={onResolved}
      />,
    );
    fireEvent.click(screen.getByTestId(`approve-experiment-${EXP_ID}`));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`/api/v1/experiments/${EXP_ID}/approve`);
    expect((init as RequestInit).method).toBe("POST");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({
      rationale: "operator-approved",
      observedDelta: 0.123,
    });

    await waitFor(() =>
      expect(
        screen.getByTestId(`approve-experiment-${EXP_ID}`),
      ).toHaveAttribute("data-status", "ok"),
    );
    expect(onResolved).toHaveBeenCalledWith(
      expect.objectContaining({
        experimentId: EXP_ID,
        outcome: "keep",
      }),
    );
  });

  it("surfaces a non-OK response inline instead of silently failing", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      text: async () =>
        JSON.stringify({ error: "worm_core_error", message: "down" }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<ApproveExperimentButton experimentId={EXP_ID} />);
    fireEvent.click(screen.getByTestId(`approve-experiment-${EXP_ID}`));

    await waitFor(() =>
      expect(
        screen.getByTestId(`approve-experiment-${EXP_ID}`),
      ).toHaveAttribute("data-status", "error"),
    );
    expect(
      screen.getByTestId(`approve-experiment-${EXP_ID}-error`),
    ).toBeInTheDocument();
  });
});

describe("RejectExperimentButton", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("POSTs to /api/v1/experiments/{id}/reject and reflects the discard outcome", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          experiment_id: EXP_ID,
          outcome: "discard",
          rationale: "stub",
          entry_ids: ["e1"],
        }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const onResolved = vi.fn();

    render(
      <RejectExperimentButton
        experimentId={EXP_ID}
        onResolved={onResolved}
      />,
    );
    fireEvent.click(screen.getByTestId(`reject-experiment-${EXP_ID}`));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`/api/v1/experiments/${EXP_ID}/reject`);
    await waitFor(() =>
      expect(
        screen.getByTestId(`reject-experiment-${EXP_ID}`),
      ).toHaveAttribute("data-status", "ok"),
    );
    expect(onResolved).toHaveBeenCalledWith(
      expect.objectContaining({
        experimentId: EXP_ID,
        outcome: "discard",
      }),
    );
  });
});
