/**
 * InviteModal — opens on trigger; validates required fields (name +
 * platform + platform_user_id); submits POST /api/people; closes on
 * success; surfaces error on 4xx/5xx.
 *
 * The previous "Send SSO link" no-op toggle and the synthesized
 * ``pending_email`` platform shim were deleted in the production
 * onboarding pass; tests below assert the modal now requires a real
 * platform identity.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock, push: vi.fn() }),
}));

import { InviteModal } from "../../components/people/InviteModal";

beforeEach(() => {
  refreshMock.mockReset();
  vi.unstubAllGlobals();
});

function stubFetch(impl: (url: string, init?: RequestInit) => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl) as unknown as typeof fetch);
}

describe("InviteModal", () => {
  it("opens the modal when the trigger button is clicked", () => {
    render(<InviteModal />);
    expect(screen.queryByTestId("invite-modal")).toBeNull();
    fireEvent.click(screen.getByTestId("invite-open"));
    expect(screen.getByTestId("invite-modal")).toBeInTheDocument();
  });

  it("validates name is required", async () => {
    stubFetch(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 201 }),
    );
    render(<InviteModal />);
    fireEvent.click(screen.getByTestId("invite-open"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("invite-submit"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("invite-error").textContent).toContain("name");
    });
  });

  it("requires platform_user_id", async () => {
    stubFetch(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 201 }),
    );
    render(<InviteModal />);
    fireEvent.click(screen.getByTestId("invite-open"));
    fireEvent.change(screen.getByTestId("invite-name"), {
      target: { value: "Carol" },
    });
    // Default platform is "slack"; platform_user_id remains empty.
    await act(async () => {
      fireEvent.click(screen.getByTestId("invite-submit"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("invite-error").textContent).toContain(
        "platform_user_id",
      );
    });
  });

  it("submits a POST to /api/people on valid input and closes the modal", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    stubFetch(async (url, init) => {
      calls.push({ url, init });
      return new Response(
        JSON.stringify({ person_id: "p_new", entry_ids: [] }),
        { status: 201 },
      );
    });
    render(<InviteModal />);
    fireEvent.click(screen.getByTestId("invite-open"));
    fireEvent.change(screen.getByTestId("invite-name"), {
      target: { value: "Carol Reyes" },
    });
    fireEvent.change(screen.getByTestId("invite-email"), {
      target: { value: "carol@x.co" },
    });
    fireEvent.change(screen.getByTestId("invite-position"), {
      target: { value: "CFO" },
    });
    fireEvent.change(screen.getByTestId("invite-platform-user-id"), {
      target: { value: "UCAROL" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("invite-submit"));
    });

    await waitFor(() => {
      const post = calls.find((c) => c.init?.method === "POST");
      expect(post).toBeTruthy();
      expect(post!.url).toBe("/api/people");
      const body = JSON.parse(String(post!.init!.body));
      expect(body.name).toBe("Carol Reyes");
      expect(body.email).toBe("carol@x.co");
      expect(body.position).toBe("CFO");
      // Real platform identity, no pending_email shim.
      expect(body.platform).toBe("slack");
      expect(body.platform_user_id).toBe("UCAROL");
      // proposed_by no longer carries the SSO-link annotation.
      expect(body.proposed_by).toBe("admin_invite");
    });

    await waitFor(() => {
      expect(screen.queryByTestId("invite-modal")).toBeNull();
    });
    expect(refreshMock).toHaveBeenCalled();
  });

  it("surfaces the server error on 5xx and keeps the modal open", async () => {
    stubFetch(async () =>
      new Response(
        JSON.stringify({ error: "worm_core_error", message: "boom" }),
        { status: 502 },
      ),
    );
    render(<InviteModal />);
    fireEvent.click(screen.getByTestId("invite-open"));
    fireEvent.change(screen.getByTestId("invite-name"), {
      target: { value: "Carol" },
    });
    fireEvent.change(screen.getByTestId("invite-platform-user-id"), {
      target: { value: "UCAROL" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("invite-submit"));
    });
    await waitFor(() => {
      expect(screen.getByTestId("invite-error").textContent).toContain("boom");
    });
    expect(screen.getByTestId("invite-modal")).toBeInTheDocument();
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("does NOT render a 'Send SSO link' toggle (deleted)", () => {
    render(<InviteModal />);
    fireEvent.click(screen.getByTestId("invite-open"));
    expect(screen.queryByTestId("invite-sso-toggle")).toBeNull();
    expect(screen.queryByTestId("invite-sso-toggle-label")).toBeNull();
  });

  it("surfaces the explanatory help copy guiding admins to ask for handles", () => {
    render(<InviteModal />);
    fireEvent.click(screen.getByTestId("invite-open"));
    const helpText = screen.getByTestId("invite-help").textContent ?? "";
    expect(helpText.toLowerCase()).toContain("platform handle");
    expect(helpText.toLowerCase()).toContain("auto-discover");
  });
});
