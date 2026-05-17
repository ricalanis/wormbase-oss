/**
 * DbtManifestImportForm component tests (Wave 3.2 Hole #2).
 *
 * Pure-presentational component; the page handles the admin-role gate
 * before mounting. These tests pin:
 *
 *   * Both fields render (manifest URI + domain select).
 *   * Submit is disabled when manifest_uri is empty.
 *   * Submitting calls the injected `importAction` with the typed values.
 *   * On `{ok: true, sourceId}`, the form navigates to `/sources` via
 *     `router.push`.
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

import { DbtManifestImportForm } from "../DbtManifestImportForm";
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

describe("DbtManifestImportForm", () => {
  it("renders both fields (manifest URI + domain select)", () => {
    const domains = [domain({ domainId: "d-1", name: "Finance" })];
    render(
      <DbtManifestImportForm domains={domains} importAction={vi.fn()} />,
    );
    expect(screen.getByTestId("dbt-manifest-uri")).toBeInTheDocument();
    expect(screen.getByTestId("dbt-manifest-domain")).toBeInTheDocument();
    expect(screen.getByTestId("dbt-manifest-submit")).toBeInTheDocument();
  });

  it("disables submit when manifest URI is empty", () => {
    const domains = [domain({ domainId: "d-1" })];
    render(
      <DbtManifestImportForm domains={domains} importAction={vi.fn()} />,
    );
    const submit = screen.getByTestId(
      "dbt-manifest-submit",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it("calls importAction with the typed values on submit", async () => {
    const importAction = vi.fn(async () => ({
      ok: true,
      sourceId: "src-xyz",
    }));
    const domains = [
      domain({ domainId: "d-1", name: "Finance" }),
      domain({ domainId: "d-2", name: "Sales" }),
    ];
    render(
      <DbtManifestImportForm
        domains={domains}
        importAction={importAction}
      />,
    );

    fireEvent.change(screen.getByTestId("dbt-manifest-uri"), {
      target: { value: "https://artifacts.example.com/manifest.json" },
    });
    fireEvent.change(screen.getByTestId("dbt-manifest-domain"), {
      target: { value: "d-2" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("dbt-manifest-submit"));
    });

    await waitFor(() => {
      expect(importAction).toHaveBeenCalledWith({
        manifestUri: "https://artifacts.example.com/manifest.json",
        domainId: "d-2",
      });
    });
  });

  it("navigates to /sources on success", async () => {
    const importAction = vi.fn(async () => ({
      ok: true,
      sourceId: "src-xyz",
    }));
    const domains = [domain({ domainId: "d-1" })];
    render(
      <DbtManifestImportForm
        domains={domains}
        importAction={importAction}
      />,
    );
    fireEvent.change(screen.getByTestId("dbt-manifest-uri"), {
      target: { value: "/tmp/manifest.json" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("dbt-manifest-submit"));
    });
    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/sources");
    });
  });

  it("shows the inline error and stays mounted on action failure", async () => {
    const importAction = vi.fn(async () => ({
      ok: false,
      error: "import_dbt_catalog endpoint v1.1",
    }));
    const domains = [domain({ domainId: "d-1" })];
    render(
      <DbtManifestImportForm
        domains={domains}
        importAction={importAction}
      />,
    );
    fireEvent.change(screen.getByTestId("dbt-manifest-uri"), {
      target: { value: "/tmp/manifest.json" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("dbt-manifest-submit"));
    });

    await waitFor(() => {
      expect(
        screen.getByTestId("dbt-manifest-import-error").textContent,
      ).toContain("endpoint v1.1");
    });
    expect(
      screen.getByTestId("dbt-manifest-import-form"),
    ).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("surfaces an empty-domains callout pointing at Tier 2 onboarding", () => {
    render(
      <DbtManifestImportForm domains={[]} importAction={vi.fn()} />,
    );
    expect(
      screen.getByTestId("dbt-manifest-domains-empty"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("dbt-manifest-domains-empty").textContent,
    ).toContain("Tier 2 onboarding");
  });
});
