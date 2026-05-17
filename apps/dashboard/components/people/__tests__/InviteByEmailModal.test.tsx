/**
 * Tests for `InviteByEmailModal` (W2.A6).
 *
 * Covers: trigger toggling, validation gates, success path POSTs the
 * canonical body to `/api/v1/people/invite`, and upstream errors surface
 * in the modal.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { InviteByEmailModal } from "../InviteByEmailModal";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: vi.fn(),
    push: vi.fn(),
    replace: vi.fn(),
  }),
}));

describe("InviteByEmailModal", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("does not render the form until the trigger is clicked", () => {
    render(<InviteByEmailModal />);
    expect(screen.queryByTestId("invite-by-email-modal")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("invite-by-email-open"));
    expect(screen.getByTestId("invite-by-email-modal")).toBeInTheDocument();
  });

  it("blocks submit when required fields are missing", async () => {
    render(<InviteByEmailModal />);
    fireEvent.click(screen.getByTestId("invite-by-email-open"));
    fireEvent.submit(screen.getByTestId("invite-by-email-form"));
    await waitFor(() =>
      expect(screen.getByTestId("invite-by-email-error")).toHaveTextContent(
        /name is required/i,
      ),
    );
  });

  it("requires email and position before posting", async () => {
    render(<InviteByEmailModal />);
    fireEvent.click(screen.getByTestId("invite-by-email-open"));
    fireEvent.change(screen.getByTestId("invite-by-email-name"), {
      target: { value: "Carol Reyes" },
    });
    fireEvent.submit(screen.getByTestId("invite-by-email-form"));
    await waitFor(() =>
      expect(screen.getByTestId("invite-by-email-error")).toHaveTextContent(
        /email is required/i,
      ),
    );
    fireEvent.change(screen.getByTestId("invite-by-email-email"), {
      target: { value: "carol@x.co" },
    });
    fireEvent.submit(screen.getByTestId("invite-by-email-form"));
    await waitFor(() =>
      expect(screen.getByTestId("invite-by-email-error")).toHaveTextContent(
        /position is required/i,
      ),
    );
  });

  it("POSTs to /api/v1/people/invite with the expected body on success", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({ person_id: "p-1", entry_ids: ["e1"] }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<InviteByEmailModal />);
    fireEvent.click(screen.getByTestId("invite-by-email-open"));
    fireEvent.change(screen.getByTestId("invite-by-email-name"), {
      target: { value: "Carol" },
    });
    fireEvent.change(screen.getByTestId("invite-by-email-email"), {
      target: { value: "carol@x.co" },
    });
    fireEvent.change(screen.getByTestId("invite-by-email-position"), {
      target: { value: "CFO" },
    });
    fireEvent.change(screen.getByTestId("invite-by-email-platform-user-id"), {
      target: { value: "U-carol" },
    });
    fireEvent.submit(screen.getByTestId("invite-by-email-form"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/people/invite");
    expect((init as RequestInit).method).toBe("POST");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toMatchObject({
      name: "Carol",
      email: "carol@x.co",
      position: "CFO",
      platform: "slack",
      platform_user_id: "U-carol",
    });
    // Modal closes on success.
    await waitFor(() =>
      expect(screen.queryByTestId("invite-by-email-modal")).not.toBeInTheDocument(),
    );
  });

  it("surfaces upstream errors instead of silently closing", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => ({ message: "worm_core_error: down" }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    render(<InviteByEmailModal />);
    fireEvent.click(screen.getByTestId("invite-by-email-open"));
    fireEvent.change(screen.getByTestId("invite-by-email-name"), {
      target: { value: "Carol" },
    });
    fireEvent.change(screen.getByTestId("invite-by-email-email"), {
      target: { value: "carol@x.co" },
    });
    fireEvent.change(screen.getByTestId("invite-by-email-position"), {
      target: { value: "CFO" },
    });
    fireEvent.change(screen.getByTestId("invite-by-email-platform-user-id"), {
      target: { value: "U-carol" },
    });
    fireEvent.submit(screen.getByTestId("invite-by-email-form"));

    await waitFor(() =>
      expect(screen.getByTestId("invite-by-email-error")).toHaveTextContent(
        /worm_core_error: down/i,
      ),
    );
    expect(screen.getByTestId("invite-by-email-modal")).toBeInTheDocument();
  });
});
