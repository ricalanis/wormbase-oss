/**
 * G3 — CredentialForm.
 *
 * Tests the schema-driven credential paste form: identity-first phase,
 * field rendering from connector schema, missing-required validation.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { CredentialForm } from "../../components/onboarding/CredentialForm";
import { getConnectorByKind } from "../../lib/connectors-catalog";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

describe("CredentialForm", () => {
  it("renders the IdentityForm first (identity must be captured before credentials)", () => {
    const postgres = getConnectorByKind("postgres")!;
    render(<CredentialForm connector={postgres} />);
    expect(screen.getByTestId("identity-form")).toBeInTheDocument();
    // Credential form not yet rendered.
    expect(screen.queryByTestId("credential-form")).toBeNull();
  });

  it("transitions to the credential form once identity is submitted", () => {
    const postgres = getConnectorByKind("postgres")!;
    render(<CredentialForm connector={postgres} />);

    fireEvent.change(screen.getByTestId("identity-name-input"), {
      target: { value: "Bob" },
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

    expect(screen.getByTestId("credential-form")).toBeInTheDocument();
    expect(
      screen.getByTestId("credential-form").getAttribute("data-connector-kind"),
    ).toBe("postgres");
  });

  it("renders one field input per connector schema field", () => {
    const snowflake = getConnectorByKind("snowflake")!;
    render(<CredentialForm connector={snowflake} />);
    fireEvent.change(screen.getByTestId("identity-name-input"), {
      target: { value: "Bob" },
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

    for (const field of snowflake.fields) {
      expect(
        screen.getByTestId(`credential-field-${field.name}`),
      ).toBeInTheDocument();
    }
  });

  it("submitting empty required fields surfaces a validation error", () => {
    const postgres = getConnectorByKind("postgres")!;
    render(<CredentialForm connector={postgres} />);

    fireEvent.change(screen.getByTestId("identity-name-input"), {
      target: { value: "Bob" },
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

    fireEvent.submit(screen.getByTestId("credential-form"));
    expect(screen.getByTestId("credential-form-error")).toBeInTheDocument();
  });
});
