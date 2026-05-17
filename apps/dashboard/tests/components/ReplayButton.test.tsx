/**
 * ReplayButton — strict-replay UX (W2.A8).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { ReplayButton } from "../../components/data-products/ReplayButton";

const DP_ID = "11111111-1111-1111-1111-111111111111";

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ReplayButton", () => {
  it("renders the primary CTA in idle state", () => {
    render(<ReplayButton dataProductId={DP_ID} reloadOnMatch={false} />);
    const btn = screen.getByTestId("replay-button");
    expect(btn.textContent).toMatch(/Replay against pinned source-hashes/i);
    expect(btn).not.toBeDisabled();
  });

  it("posts to /api/v1/data-products/{id}/replay and surfaces the bit-identical badge on match", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data_product_id: DP_ID,
        run_id: "r1",
        content_hash: "abcdef0123456789abcdef0123456789",
        expected_content_hash: "abcdef0123456789abcdef0123456789",
        matches_original: true,
        entry_ids: ["e1", "e2", "e3", "e4"],
      }),
      text: async () => "",
    });
    vi.stubGlobal("fetch", fetchSpy);

    render(<ReplayButton dataProductId={DP_ID} reloadOnMatch={false} />);
    fireEvent.click(screen.getByTestId("replay-button"));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(1);
    });
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe(`/api/v1/data-products/${DP_ID}/replay`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toMatchObject({
      strict: true,
      generated_by: "replay",
    });

    const badge = await screen.findByTestId("replay-match-badge");
    expect(badge.textContent).toContain("bit-identical content_hash");
    expect(badge.textContent).toContain("abcdef0123456789");
  });

  it("surfaces the drift badge when the API returns 409 replay_mismatch", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        error: "replay_mismatch",
        message: "expected=abc actual=xyz",
      }),
      text: async () => "",
    });
    vi.stubGlobal("fetch", fetchSpy);

    render(<ReplayButton dataProductId={DP_ID} reloadOnMatch={false} />);
    fireEvent.click(screen.getByTestId("replay-button"));

    const badge = await screen.findByTestId("replay-mismatch-badge");
    expect(badge.textContent).toContain("content_hash drift");
    expect(badge.textContent).toContain("expected=abc actual=xyz");
    // No success badge.
    expect(screen.queryByTestId("replay-match-badge")).toBeNull();
  });

  it("shows an error message on 5xx", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({}),
      text: async () => "worm-core unavailable",
    });
    vi.stubGlobal("fetch", fetchSpy);

    render(<ReplayButton dataProductId={DP_ID} reloadOnMatch={false} />);
    fireEvent.click(screen.getByTestId("replay-button"));

    const err = await screen.findByTestId("replay-error");
    expect(err.textContent).toContain("502");
  });
});
