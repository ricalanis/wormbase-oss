/**
 * AgentRegistrationForm component tests (Wave 3.2 Hole #1).
 *
 * Pure-presentational component; the page handles the admin-role gate
 * before mounting. These tests pin:
 *
 *   * All four fields render (provider, display_name, domain checkboxes,
 *     budget).
 *   * The submit button is disabled when display_name is empty.
 *   * Submitting calls the injected `registerAction` with the typed form
 *     values, including selected domain ids and the (optional) budget.
 *   * On `{ok: true, agentId}`, the form navigates to
 *     `/people/agents/[id]` via `router.push`.
 *   * On `{ok: false, error}`, the inline error surfaces and the form
 *     stays mounted for retry.
 *   * Empty-domains state surfaces an honest callout pointing at Tier 2
 *     onboarding.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn(), refresh: vi.fn() }),
}));

import { AgentRegistrationForm } from "../AgentRegistrationForm";
import type { DomainRow } from "../../../lib/ledger-client.types";

function domain(partial: Partial<DomainRow> & Pick<DomainRow, "domainId">): DomainRow {
  return {
    domainId: partial.domainId,
    name: partial.name ?? `domain ${partial.domainId.slice(0, 4)}`,
    owner: partial.owner ?? "unassigned",
    classificationDefault: partial.classificationDefault ?? "internal",
    resourceCount: partial.resourceCount ?? 0,
    receipt: partial.receipt ?? {
      hash: "abcdef012345",
      source: "domains-projection",
      owner: partial.owner ?? "unassigned",
      classification: partial.classificationDefault ?? "internal",
    },
  };
}

beforeEach(() => {
  pushMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AgentRegistrationForm", () => {
  it("renders all four fields (provider, display_name, domain grants, budget)", () => {
    const domains = [
      domain({ domainId: "11111111-1111-1111-1111-111111111111", name: "Finance" }),
    ];
    render(
      <AgentRegistrationForm domains={domains} registerAction={vi.fn()} />,
    );

    expect(screen.getByTestId("agent-external-provider")).toBeInTheDocument();
    expect(screen.getByTestId("agent-display-name")).toBeInTheDocument();
    expect(screen.getByTestId("agent-domain-grants")).toBeInTheDocument();
    expect(
      screen.getByTestId("agent-domain-11111111-1111-1111-1111-111111111111"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("agent-budget")).toBeInTheDocument();
    expect(screen.getByTestId("agent-register-submit")).toBeInTheDocument();
  });

  it("disables submit when display_name is empty", () => {
    render(
      <AgentRegistrationForm domains={[]} registerAction={vi.fn()} />,
    );
    const submit = screen.getByTestId(
      "agent-register-submit",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it("calls registerAction with the form values on submit", async () => {
    const register = vi.fn(async () => ({ ok: true, agentId: "agent-xyz" }));
    const domains = [
      domain({ domainId: "d-1", name: "Finance" }),
      domain({ domainId: "d-2", name: "Sales" }),
    ];
    render(
      <AgentRegistrationForm domains={domains} registerAction={register} />,
    );

    fireEvent.change(screen.getByTestId("agent-external-provider"), {
      target: { value: "openai" },
    });
    fireEvent.change(screen.getByTestId("agent-display-name"), {
      target: { value: "revenue-bot" },
    });
    fireEvent.click(screen.getByTestId("agent-domain-d-1"));
    fireEvent.change(screen.getByTestId("agent-budget"), {
      target: { value: "25.50" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("agent-register-submit"));
    });

    await waitFor(() => {
      expect(register).toHaveBeenCalledWith({
        externalProvider: "openai",
        displayName: "revenue-bot",
        domainReadIds: ["d-1"],
        modelAccessBudgetUsd: "25.50",
      });
    });
  });

  it("navigates to /people/agents/[id] on success", async () => {
    const register = vi.fn(async () => ({ ok: true, agentId: "agent-xyz" }));
    render(
      <AgentRegistrationForm domains={[]} registerAction={register} />,
    );
    fireEvent.change(screen.getByTestId("agent-display-name"), {
      target: { value: "x" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("agent-register-submit"));
    });

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/people/agents/agent-xyz");
    });
  });

  it("shows the inline error and stays mounted on action failure", async () => {
    const register = vi.fn(async () => ({
      ok: false,
      error: "register_agent endpoint v1.1",
    }));
    render(
      <AgentRegistrationForm domains={[]} registerAction={register} />,
    );
    fireEvent.change(screen.getByTestId("agent-display-name"), {
      target: { value: "x" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("agent-register-submit"));
    });

    await waitFor(() => {
      expect(
        screen.getByTestId("agent-registration-error").textContent,
      ).toContain("endpoint v1.1");
    });
    // Form is still mounted for retry.
    expect(screen.getByTestId("agent-registration-form")).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("surfaces an empty-domains callout when no domains exist", () => {
    render(
      <AgentRegistrationForm domains={[]} registerAction={vi.fn()} />,
    );
    expect(screen.getByTestId("agent-domains-empty")).toBeInTheDocument();
    expect(
      screen.getByTestId("agent-domains-empty").textContent,
    ).toContain("Tier 2 onboarding");
  });

  it("omits modelAccessBudgetUsd when the budget input is blank", async () => {
    const register = vi.fn(async () => ({ ok: true, agentId: "a-1" }));
    render(
      <AgentRegistrationForm domains={[]} registerAction={register} />,
    );
    fireEvent.change(screen.getByTestId("agent-display-name"), {
      target: { value: "no-budget-bot" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("agent-register-submit"));
    });
    await waitFor(() => {
      expect(register).toHaveBeenCalledWith({
        externalProvider: "claude",
        displayName: "no-budget-bot",
        domainReadIds: [],
        modelAccessBudgetUsd: undefined,
      });
    });
  });
});
