/**
 * Phase 4 Task 4C — landing-page SignupCTA tests.
 *
 * Replaces the placeholder coverage in landing-sections.test.tsx (which
 * pinned the disabled-button shape from 4A). 4C wires the primary CTA
 * to ``/api/auth/slack/start`` and adds an inline email magic-link form
 * that POSTs to ``/api/auth/email/request``. The secondary CTA (walk
 * the demo workspace via ``/onboarding``) is preserved so visitors with
 * a half-finished install still have the existing path.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { SignupCTA } from "../../components/landing/SignupCTA";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SignupCTA — Phase 4C wire-up", () => {
  it("primary signup CTA links to /api/auth/slack/start", () => {
    render(<SignupCTA />);
    const cta = screen.getByTestId("signup-primary");
    expect(cta).not.toBeDisabled();
    // Either the button is wrapped in an <a href=...> or is itself a link.
    const href =
      cta.getAttribute("href") ??
      cta.closest("a")?.getAttribute("href") ??
      "";
    expect(href).toBe("/api/auth/slack/start");
  });

  it("preserves the secondary 'walk the demo workspace' CTA", () => {
    render(<SignupCTA />);
    const secondary = screen.getByTestId("signup-secondary");
    expect(secondary).toHaveAttribute("href", "/onboarding");
  });

  it("renders an email magic-link form", () => {
    render(<SignupCTA />);
    expect(screen.getByTestId("signup-email-form")).toBeInTheDocument();
    const input = screen.getByTestId("signup-email-input") as HTMLInputElement;
    expect(input.tagName).toBe("INPUT");
    expect(input.getAttribute("type")).toBe("email");
    expect(input.required).toBe(true);
    const submit = screen.getByTestId("signup-email-submit");
    expect(submit).toBeInTheDocument();
  });

  it("rejects empty/blank emails inline (does not hit the API)", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<SignupCTA />);
    const form = screen.getByTestId("signup-email-form");
    fireEvent.submit(form);
    // No network call.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("POSTs the entered email to /api/auth/email/request on submit", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ sent: true, expires_in_s: 900 }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<SignupCTA />);
    const input = screen.getByTestId("signup-email-input");
    fireEvent.change(input, { target: { value: "evaluator@example.com" } });
    fireEvent.submit(screen.getByTestId("signup-email-form"));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/email/request");
    expect(init?.method).toBe("POST");
    const body = JSON.parse((init?.body as string) ?? "{}");
    expect(body.email).toBe("evaluator@example.com");

    await waitFor(() =>
      expect(screen.getByTestId("signup-email-success")).toBeInTheDocument(),
    );
  });

  it("surfaces an honest error state when the API returns 4xx/5xx", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        new Response(
          JSON.stringify({ error: "auth_secret_unset" }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<SignupCTA />);
    fireEvent.change(screen.getByTestId("signup-email-input"), {
      target: { value: "x@y.com" },
    });
    fireEvent.submit(screen.getByTestId("signup-email-form"));
    await waitFor(() =>
      expect(screen.getByTestId("signup-email-error")).toBeInTheDocument(),
    );
  });
});
