/**
 * D8 — ShareViewButton.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { ShareViewButton } from "../../components/chrome/ShareViewButton";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ShareViewButton", () => {
  it("renders the default 'share view' label", () => {
    render(<ShareViewButton />);
    const btn = screen.getByTestId("share-view-button");
    expect(btn.textContent).toContain("share view");
  });

  it("respects an explicit label override", () => {
    render(<ShareViewButton label="copy view" />);
    expect(screen.getByTestId("share-view-button").textContent).toContain(
      "copy view",
    );
  });

  it("writes the current URL to the clipboard and flashes 'copied'", async () => {
    const writeText = vi.fn().mockResolvedValueOnce(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(<ShareViewButton />);
    fireEvent.click(screen.getByTestId("share-view-button"));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(window.location.href),
    );
    await waitFor(() =>
      expect(screen.getByTestId("share-view-button").textContent).toContain(
        "copied",
      ),
    );
  });

  it("falls back to window.prompt when navigator.clipboard is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    });
    const promptSpy = vi
      .spyOn(window, "prompt")
      .mockImplementation(() => null);
    render(<ShareViewButton />);
    fireEvent.click(screen.getByTestId("share-view-button"));
    await waitFor(() => expect(promptSpy).toHaveBeenCalledTimes(1));
    promptSpy.mockRestore();
  });
});
