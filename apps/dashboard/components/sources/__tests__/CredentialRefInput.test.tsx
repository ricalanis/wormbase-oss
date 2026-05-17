/**
 * CredentialRefInput tests — opaque-secret onboarding seam.
 *
 * Closes carry-forward #1 from the 2026-06-10 CredentialBroker
 * integration close-out: the dashboard now has a typed input for the
 * operator's broker slot key, gated by connector kind, that threads
 * through the ``/api/sources/propose`` action to the worm-core ledger.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CredentialRefInput } from "../CredentialRefInput";

describe("CredentialRefInput", () => {
  it("renders nothing for URI-shaped connector kinds", () => {
    const onChange = vi.fn();
    const { container } = render(
      <CredentialRefInput
        connectorKind="csv_local"
        value=""
        onChange={onChange}
      />
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing for postgres / snowflake / bigquery", () => {
    const onChange = vi.fn();
    for (const kind of ["postgres", "snowflake", "bigquery", "s3_csv", "http_csv"]) {
      const { container, unmount } = render(
        <CredentialRefInput connectorKind={kind} value="" onChange={onChange} />
      );
      expect(container.innerHTML).toBe("");
      unmount();
    }
  });

  it("renders nothing for an empty kind (defensive)", () => {
    const onChange = vi.fn();
    const { container } = render(
      <CredentialRefInput connectorKind="" value="" onChange={onChange} />
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders the input for stripe (opaque-secret kind)", () => {
    const onChange = vi.fn();
    render(
      <CredentialRefInput connectorKind="stripe" value="" onChange={onChange} />
    );
    expect(screen.getByTestId("credential-ref-input")).toBeInTheDocument();
    const field = screen.getByTestId("credential-ref-input-field");
    expect(field).toBeInTheDocument();
    expect((field as HTMLInputElement).placeholder).toMatch(/stripe-prod/i);
  });

  it("renders for salesforce / hubspot / gsheets too", () => {
    const onChange = vi.fn();
    for (const kind of ["salesforce", "hubspot", "gsheets"]) {
      const { unmount } = render(
        <CredentialRefInput connectorKind={kind} value="" onChange={onChange} />
      );
      expect(screen.getByTestId("credential-ref-input")).toBeInTheDocument();
      expect(
        screen.getByTestId("credential-ref-input").getAttribute("data-connector-kind"),
      ).toBe(kind);
      unmount();
    }
  });

  it("calls onChange when the operator types in the field", () => {
    const onChange = vi.fn();
    render(
      <CredentialRefInput
        connectorKind="stripe"
        value="abc"
        onChange={onChange}
      />
    );
    const field = screen.getByTestId("credential-ref-input-field") as HTMLInputElement;
    expect(field.value).toBe("abc");
    fireEvent.change(field, { target: { value: "vault://stripe-prod" } });
    expect(onChange).toHaveBeenCalledWith("vault://stripe-prod");
  });

  it("respects the disabled prop", () => {
    const onChange = vi.fn();
    render(
      <CredentialRefInput
        connectorKind="stripe"
        value=""
        onChange={onChange}
        disabled
      />
    );
    const field = screen.getByTestId(
      "credential-ref-input-field",
    ) as HTMLInputElement;
    expect(field.disabled).toBe(true);
  });

  it("exposes a help link to the broker docs", () => {
    const onChange = vi.fn();
    render(
      <CredentialRefInput connectorKind="stripe" value="" onChange={onChange} />
    );
    const help = screen.getByTestId("credential-ref-input-help");
    expect(help.getAttribute("href")).toBe("/docs/credential-broker");
  });

  it("explains the optional posture (operator may submit blank)", () => {
    const onChange = vi.fn();
    render(
      <CredentialRefInput connectorKind="stripe" value="" onChange={onChange} />
    );
    const section = screen.getByTestId("credential-ref-input");
    expect(section.textContent).toMatch(/CredentialBroker/);
    expect(section.textContent).toMatch(/optional/i);
  });
});
