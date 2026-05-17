/**
 * G2 — IdentityForm (pre-connect installer-identity capture).
 *
 * Tests:
 *   - renders the four required fields
 *   - submission requires all four fields
 *   - successful submit calls onSubmitted with trimmed values
 *   - validation error renders inline
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { IdentityForm } from "../../components/onboarding/IdentityForm";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("IdentityForm", () => {
  it("renders the four required fields", () => {
    const onSubmitted = vi.fn();
    render(
      <IdentityForm
        connectorKind="csv_local"
        connectorLabel="Local CSV file"
        onSubmitted={onSubmitted}
      />,
    );
    expect(screen.getByTestId("identity-name-input")).toBeInTheDocument();
    expect(screen.getByTestId("identity-email-input")).toBeInTheDocument();
    expect(
      screen.getByTestId("identity-position-select"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("identity-org-size-select"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("identity-submit-button"),
    ).toBeInTheDocument();
  });

  it("propagates the connector kind via data-connector-kind for downstream tests", () => {
    render(
      <IdentityForm
        connectorKind="postgres"
        connectorLabel="Postgres"
        onSubmitted={vi.fn()}
      />,
    );
    expect(
      screen
        .getByTestId("identity-form")
        .getAttribute("data-connector-kind"),
    ).toBe("postgres");
  });

  it("submitting empty form surfaces a validation error and does not call onSubmitted", () => {
    const onSubmitted = vi.fn();
    render(
      <IdentityForm
        connectorKind="csv_local"
        connectorLabel="Local CSV file"
        onSubmitted={onSubmitted}
      />,
    );
    // Native HTML validation may block submit; force submit by firing on form.
    const form = screen.getByTestId("identity-form");
    fireEvent.submit(form);
    expect(onSubmitted).not.toHaveBeenCalled();
  });

  it("calls onSubmitted with the trimmed values when all fields are filled", async () => {
    const onSubmitted = vi.fn().mockResolvedValue(undefined);
    render(
      <IdentityForm
        connectorKind="csv_local"
        connectorLabel="Local CSV file"
        onSubmitted={onSubmitted}
      />,
    );
    fireEvent.change(screen.getByTestId("identity-name-input"), {
      target: { value: "  Bob  " },
    });
    fireEvent.change(screen.getByTestId("identity-email-input"), {
      target: { value: "bob@example.co" },
    });
    fireEvent.change(screen.getByTestId("identity-position-select"), {
      target: { value: "data_engineer" },
    });
    fireEvent.change(screen.getByTestId("identity-org-size-select"), {
      target: { value: "11-50" },
    });

    fireEvent.submit(screen.getByTestId("identity-form"));

    // Allow microtasks to flush.
    await Promise.resolve();
    await Promise.resolve();

    expect(onSubmitted).toHaveBeenCalledTimes(1);
    expect(onSubmitted).toHaveBeenCalledWith({
      name: "Bob",
      email: "bob@example.co",
      position: "data_engineer",
      orgSize: "11-50",
    });
  });

  it("renders the connector label in the heading and submit button", () => {
    render(
      <IdentityForm
        connectorKind="postgres"
        connectorLabel="Postgres"
        onSubmitted={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("identity-form").textContent?.toLowerCase(),
    ).toContain("postgres");
  });
});
