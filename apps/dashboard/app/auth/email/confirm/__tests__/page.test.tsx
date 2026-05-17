/**
 * Phase 4 Task 4C — visitor-facing confirm page.
 *
 * The actual session-binding lives in /api/auth/email/confirm. This page
 * exists to give magic-link visitors a friendly UX layer (rendered while
 * the API route runs) and to surface honest errors when the token is
 * missing/expired/invalid. On success the page server-redirects to the
 * API route which sets the session cookie and 303s to /dashboard.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  redirect: vi.fn((target: string) => {
    throw new Error(`__redirect__:${target}`);
  }),
}));

import ConfirmPage from "../page";
import { redirect } from "next/navigation";

describe("/auth/email/confirm page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders an honest 'missing token' panel when ?token= is absent", async () => {
    const ui = await ConfirmPage({ searchParams: Promise.resolve({}) });
    render(ui);
    expect(screen.getByTestId("confirm-error")).toBeInTheDocument();
    expect(screen.getByTestId("confirm-error").textContent).toMatch(
      /token/i,
    );
  });

  it("redirects to /api/auth/email/confirm with the token preserved", async () => {
    try {
      await ConfirmPage({
        searchParams: Promise.resolve({ token: "abc.def" }),
      });
    } catch (e) {
      // expected — the redirect mock throws.
      expect((e as Error).message).toMatch(/^__redirect__:/);
    }
    expect(redirect).toHaveBeenCalledTimes(1);
    const target = (redirect as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0][0];
    expect(target).toBe("/api/auth/email/confirm?token=abc.def");
  });

  it("URL-encodes the token before redirecting", async () => {
    try {
      await ConfirmPage({
        searchParams: Promise.resolve({ token: "a b/c+d" }),
      });
    } catch {
      /* expected */
    }
    const target = (redirect as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0][0];
    expect(target).toBe("/api/auth/email/confirm?token=a%20b%2Fc%2Bd");
  });

  it("renders a 'magic link expired' panel when ?error=invalid_or_expired", async () => {
    const ui = await ConfirmPage({
      searchParams: Promise.resolve({ error: "invalid_or_expired" }),
    });
    render(ui);
    expect(screen.getByTestId("confirm-error")).toBeInTheDocument();
    expect(screen.getByTestId("confirm-error").textContent).toMatch(
      /expired|invalid/i,
    );
  });
});
