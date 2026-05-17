/**
 * InvitePersonForm component tests — Onboarding Sub-wave C (2026-05-30).
 *
 * Pins the invite form's surface contract: validates that at least
 * one of email/platform_id is supplied; routes the result into a
 * receipt strip; the role_intent dropdown round-trips the selection.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../../../app/(app)/onboard/person/actions", () => ({
  invitePersonAction: vi.fn(),
}));

import { invitePersonAction } from "../../../app/(app)/onboard/person/actions";
import { InvitePersonForm } from "../InvitePersonForm";

const mockedAction = vi.mocked(invitePersonAction);

describe("InvitePersonForm", () => {
  it("renders all fields + a submit button", () => {
    render(<InvitePersonForm />);
    expect(screen.getByTestId("onboard-person-invite-form")).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-person-invite-email"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-person-invite-platform-id"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-person-invite-role-intent"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("onboard-person-invite-submit"),
    ).toBeInTheDocument();
  });

  it("disables submit until at least one of email/platform_id is set", () => {
    render(<InvitePersonForm />);
    const submit = screen.getByTestId(
      "onboard-person-invite-submit",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fireEvent.change(screen.getByTestId("onboard-person-invite-email"), {
      target: { value: "alice@example.com" },
    });
    expect(submit.disabled).toBe(false);
  });

  it("submits email + role_intent and surfaces the receipt", async () => {
    mockedAction.mockResolvedValueOnce({
      ok: true,
      inviteeEmail: "alice@example.com",
      inviteePlatformId: null,
      roleIntent: "admin",
    });
    render(<InvitePersonForm />);
    fireEvent.change(screen.getByTestId("onboard-person-invite-email"), {
      target: { value: "alice@example.com" },
    });
    fireEvent.change(screen.getByTestId("onboard-person-invite-role-intent"), {
      target: { value: "admin" },
    });
    fireEvent.click(screen.getByTestId("onboard-person-invite-submit"));
    await waitFor(() => {
      expect(
        screen.getByTestId("onboard-person-invite-receipt"),
      ).toHaveTextContent("alice@example.com");
    });
    expect(invitePersonAction).toHaveBeenCalledWith(
      expect.objectContaining({
        inviteeEmail: "alice@example.com",
        roleIntent: "admin",
      }),
    );
  });

  it("surfaces the error when the action fails", async () => {
    mockedAction.mockResolvedValueOnce({
      ok: false,
      error: "at least one of email or platform_id required",
    });
    render(<InvitePersonForm />);
    // Force submit by populating email field
    fireEvent.change(screen.getByTestId("onboard-person-invite-email"), {
      target: { value: "bad@example.com" },
    });
    fireEvent.click(screen.getByTestId("onboard-person-invite-submit"));
    await waitFor(() => {
      expect(
        screen.getByTestId("onboard-person-invite-error"),
      ).toHaveTextContent("at least one of email");
    });
  });
});
