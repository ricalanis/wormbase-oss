/**
 * SnowflakeCatalogImportForm component tests (Wave 3.2 Hole #2).
 *
 * Pure-presentational component; the page handles the admin-role gate
 * before mounting. These tests pin:
 *
 *   * All required fields render (account/user/database/schema/warehouse/
 *     role/domain).
 *   * Submit is disabled until all required fields are filled.
 *   * Submitting calls the injected `importAction` with the typed values.
 *   * On `{ok: true, sourceId}`, the form navigates to `/sources` via
 *     `router.push`.
 *   * On `{ok: false, error}`, the inline error surfaces.
 *   * Empty-domains state surfaces an honest callout pointing at Tier 2
 *     onboarding.
 *   * Optional `role` is omitted when blank.
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

import { SnowflakeCatalogImportForm } from "../SnowflakeCatalogImportForm";
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

function fillRequired() {
  fireEvent.change(screen.getByTestId("snowflake-account"), {
    target: { value: "abc12345.us-east-1.aws" },
  });
  fireEvent.change(screen.getByTestId("snowflake-user"), {
    target: { value: "WORMBASE_INGEST" },
  });
  fireEvent.change(screen.getByTestId("snowflake-database"), {
    target: { value: "ANALYTICS" },
  });
  fireEvent.change(screen.getByTestId("snowflake-schema"), {
    target: { value: "MARTS" },
  });
  fireEvent.change(screen.getByTestId("snowflake-warehouse"), {
    target: { value: "WORMBASE_WH" },
  });
}

beforeEach(() => {
  pushMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SnowflakeCatalogImportForm", () => {
  it("renders all required fields + role + domain", () => {
    const domains = [domain({ domainId: "d-1", name: "Finance" })];
    render(
      <SnowflakeCatalogImportForm
        domains={domains}
        importAction={vi.fn()}
      />,
    );
    expect(screen.getByTestId("snowflake-account")).toBeInTheDocument();
    expect(screen.getByTestId("snowflake-user")).toBeInTheDocument();
    expect(screen.getByTestId("snowflake-database")).toBeInTheDocument();
    expect(screen.getByTestId("snowflake-schema")).toBeInTheDocument();
    expect(screen.getByTestId("snowflake-warehouse")).toBeInTheDocument();
    expect(screen.getByTestId("snowflake-role")).toBeInTheDocument();
    expect(
      screen.getByTestId("snowflake-catalog-domain"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("snowflake-catalog-submit"),
    ).toBeInTheDocument();
  });

  it("disables submit until all required fields are filled", () => {
    const domains = [domain({ domainId: "d-1" })];
    render(
      <SnowflakeCatalogImportForm
        domains={domains}
        importAction={vi.fn()}
      />,
    );
    const submit = screen.getByTestId(
      "snowflake-catalog-submit",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fireEvent.change(screen.getByTestId("snowflake-account"), {
      target: { value: "abc.us-east-1.aws" },
    });
    expect(submit.disabled).toBe(true); // still missing the rest
  });

  it("calls importAction with the typed values on submit", async () => {
    const importAction = vi.fn(async () => ({
      ok: true,
      sourceId: "src-snow-1",
    }));
    const domains = [domain({ domainId: "d-1", name: "Finance" })];
    render(
      <SnowflakeCatalogImportForm
        domains={domains}
        importAction={importAction}
      />,
    );

    fillRequired();
    fireEvent.change(screen.getByTestId("snowflake-role"), {
      target: { value: "WORMBASE_RO" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("snowflake-catalog-submit"));
    });

    await waitFor(() => {
      expect(importAction).toHaveBeenCalledWith({
        account: "abc12345.us-east-1.aws",
        user: "WORMBASE_INGEST",
        database: "ANALYTICS",
        schema: "MARTS",
        warehouse: "WORMBASE_WH",
        role: "WORMBASE_RO",
        domainId: "d-1",
      });
    });
  });

  it("omits role when the field is blank", async () => {
    const importAction = vi.fn(async () => ({
      ok: true,
      sourceId: "src-1",
    }));
    const domains = [domain({ domainId: "d-1" })];
    render(
      <SnowflakeCatalogImportForm
        domains={domains}
        importAction={importAction}
      />,
    );
    fillRequired();
    await act(async () => {
      fireEvent.click(screen.getByTestId("snowflake-catalog-submit"));
    });
    await waitFor(() => {
      expect(importAction).toHaveBeenCalled();
      const call = importAction.mock.calls[0];
      expect(call).toBeDefined();
       
      const args = (call as any[])[0];
      expect(args.role).toBeUndefined();
    });
  });

  it("navigates to /sources on success", async () => {
    const importAction = vi.fn(async () => ({
      ok: true,
      sourceId: "src-1",
    }));
    const domains = [domain({ domainId: "d-1" })];
    render(
      <SnowflakeCatalogImportForm
        domains={domains}
        importAction={importAction}
      />,
    );
    fillRequired();
    await act(async () => {
      fireEvent.click(screen.getByTestId("snowflake-catalog-submit"));
    });
    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/sources");
    });
  });

  it("shows the inline error and stays mounted on action failure", async () => {
    const importAction = vi.fn(async () => ({
      ok: false,
      error: "import_snowflake_catalog endpoint v1.1",
    }));
    const domains = [domain({ domainId: "d-1" })];
    render(
      <SnowflakeCatalogImportForm
        domains={domains}
        importAction={importAction}
      />,
    );
    fillRequired();
    await act(async () => {
      fireEvent.click(screen.getByTestId("snowflake-catalog-submit"));
    });

    await waitFor(() => {
      expect(
        screen.getByTestId("snowflake-catalog-import-error").textContent,
      ).toContain("endpoint v1.1");
    });
    expect(
      screen.getByTestId("snowflake-catalog-import-form"),
    ).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("surfaces an empty-domains callout pointing at Tier 2 onboarding", () => {
    render(
      <SnowflakeCatalogImportForm domains={[]} importAction={vi.fn()} />,
    );
    expect(
      screen.getByTestId("snowflake-catalog-domains-empty"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("snowflake-catalog-domains-empty").textContent,
    ).toContain("Tier 2 onboarding");
  });
});
