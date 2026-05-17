/**
 * Tests for ReactivityCard (W5.A5).
 *
 * Covers:
 *   - renders id + name + scope chip + state pill
 *   - shows "Confirm" CTA only for proposed state
 *   - shows "Disable" CTA + reason input only for active state
 *   - confirm POSTs to the right URL
 *   - disable surfaces a validation error when reason is blank
 *   - "Show fires" toggles ReactivityFiresLog mount
 *   - disabled cards are visible but greyed-out (opacity)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ReactivityCard } from "../ReactivityCard";
import type { Reactivity } from "../../../lib/ledger-client.types";

const ACTIVE: Reactivity = {
  id: "statement_to_owner",
  name: "Statement to Owner",
  description: "DM the owner of a referenced resource.",
  scope: "company",
  state: "active",
  proposedBy: null,
  confirmedBy: null,
  disabledBy: null,
  disableReason: null,
  lastFiredAt: "2026-04-28T10:00:00.000Z",
  predicateSpec: {},
  conditionSpec: {},
  actionSpec: {},
};

const PROPOSED: Reactivity = {
  ...ACTIVE,
  id: "prop_xyz",
  name: "Proposed reactivity",
  state: "proposed",
  lastFiredAt: null,
};

const DISABLED: Reactivity = {
  ...ACTIVE,
  id: "stale",
  name: "Stale reactivity",
  state: "disabled",
  disableReason: "noisy in #revenue",
};

describe("ReactivityCard", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders id, name, scope chip, and state pill for active rows", () => {
    render(<ReactivityCard reactivity={ACTIVE} />);
    expect(screen.getByText(ACTIVE.name)).toBeInTheDocument();
    expect(screen.getByTestId(`reactivity-scope-${ACTIVE.id}`)).toHaveTextContent(
      "company",
    );
    expect(screen.getByTestId(`reactivity-state-${ACTIVE.id}`)).toHaveTextContent(
      "active",
    );
  });

  it("shows Confirm CTA only for proposed reactivities", () => {
    const { rerender } = render(<ReactivityCard reactivity={ACTIVE} />);
    expect(
      screen.queryByTestId(`reactivity-confirm-${ACTIVE.id}`),
    ).not.toBeInTheDocument();
    rerender(<ReactivityCard reactivity={PROPOSED} />);
    expect(
      screen.getByTestId(`reactivity-confirm-${PROPOSED.id}`),
    ).toBeInTheDocument();
  });

  it("shows Disable CTA + reason input only for active reactivities", () => {
    render(<ReactivityCard reactivity={ACTIVE} />);
    expect(
      screen.getByTestId(`reactivity-disable-${ACTIVE.id}`),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId(`reactivity-disable-reason-input-${ACTIVE.id}`),
    ).toBeInTheDocument();
  });

  it("confirm POSTs to /api/v1/reactivities/{id}/confirm and refreshes", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => "{}",
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const onMutated = vi.fn();
    render(<ReactivityCard reactivity={PROPOSED} onMutated={onMutated} />);
    fireEvent.click(screen.getByTestId(`reactivity-confirm-${PROPOSED.id}`));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/v1/reactivities/${PROPOSED.id}/confirm`,
    );
    await waitFor(() => expect(onMutated).toHaveBeenCalled());
  });

  it("disable refuses without a reason", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ReactivityCard reactivity={ACTIVE} />);
    fireEvent.click(screen.getByTestId(`reactivity-disable-${ACTIVE.id}`));
    await waitFor(() =>
      expect(
        screen.getByTestId(`reactivity-error-${ACTIVE.id}`),
      ).toHaveTextContent(/reason/i),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("disable POSTs reason when provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => "{}",
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ReactivityCard reactivity={ACTIVE} />);
    fireEvent.change(
      screen.getByTestId(`reactivity-disable-reason-input-${ACTIVE.id}`),
      { target: { value: "noisy" } },
    );
    fireEvent.click(screen.getByTestId(`reactivity-disable-${ACTIVE.id}`));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ reason: "noisy" });
  });

  it("Show fires toggles the fires log mount", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ fires: [] }),
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    render(<ReactivityCard reactivity={ACTIVE} />);
    expect(
      screen.queryByTestId(`reactivity-fires-log-${ACTIVE.id}`),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId(`reactivity-show-fires-${ACTIVE.id}`));
    await waitFor(() =>
      expect(
        screen.getByTestId(`reactivity-fires-log-${ACTIVE.id}`),
      ).toBeInTheDocument(),
    );
  });

  it("disabled rows render the disable reason and grey-out chrome", () => {
    render(<ReactivityCard reactivity={DISABLED} />);
    expect(
      screen.getByTestId(`reactivity-disable-reason-${DISABLED.id}`),
    ).toHaveTextContent("noisy in #revenue");
    const card = screen.getByTestId(`reactivity-card-${DISABLED.id}`);
    expect(card).toHaveAttribute("data-state", "disabled");
  });
});
