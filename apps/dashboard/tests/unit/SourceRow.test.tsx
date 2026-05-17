import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SourceRow } from "../../components/sources/SourceRow";
import { ProvenanceMarker } from "../../components/sources/ProvenanceMarker";
import type { SourceRow as SourceRowModel, SourceFlow } from "../../lib/ledger-client.types";

const baseRow: SourceRowModel = {
  sourceId: "src_x",
  uri: "snowflake://demo.x",
  kind: "table",
  addedByPerson: "carla-bot",
  addedAt: "2026-04-23T14:02:00Z",
  addedViaFlow: "drop_and_profile",
  addedInResponseTo: "#data drop",
  rowCount: 1234,
  lastProfileTs: "2026-04-23T14:04:00Z",
  receipt: {
    hash: "abcd1234",
    source: "snowflake://demo.x",
    owner: "carla-bot",
    classification: "internal",
  },
};

describe("ProvenanceMarker", () => {
  it("emits a distinct data-flow attribute for each of the 5 flows", () => {
    const flows: SourceFlow[] = [
      "drop_and_profile",
      "credential_offered_in_dm",
      "mentioned_in_conversation",
      "dashboard_form",
      "kpi_gap_triggered",
    ];
    const seen = new Set<string>();
    for (const f of flows) {
      const { container } = render(
        <ProvenanceMarker
          addedByPerson="x"
          addedAt="2026-04-23T00:00:00Z"
          addedViaFlow={f}
          addedInResponseTo={null}
        />
      );
      const node = container.querySelector("[data-flow]");
      expect(node).toBeTruthy();
      seen.add(node!.getAttribute("data-flow")!);
    }
    expect(seen.size).toBe(5);
  });

  it("renders the literal mono provenance line", () => {
    const { container } = render(
      <ProvenanceMarker
        addedByPerson="carla-bot"
        addedAt="2026-04-23T14:02:00Z"
        addedViaFlow="drop_and_profile"
        addedInResponseTo="#data drop"
      />
    );
    expect(container.textContent).toMatch(/added by/);
    expect(container.textContent).toMatch(/@carla-bot/);
    expect(container.textContent).toMatch(/drop_and_profile/);
  });
});

describe("SourceRow", () => {
  it("renders URI in mono, the provenance marker, and a Receipt", () => {
    const { container } = render(<SourceRow row={baseRow} />);
    expect(container.querySelector(`[data-testid="source-${baseRow.sourceId}"]`)).toBeTruthy();
    expect(container.querySelector("[data-flow]")).toBeTruthy();
    expect(container.querySelector("[data-receipt]")).toBeTruthy();
  });

  it("renders the connector kind, classification, and maintainer chips (D5)", () => {
    const { container } = render(<SourceRow row={baseRow} />);
    const meta = container.querySelector(
      `[data-testid="source-metadata-${baseRow.sourceId}"]`,
    );
    expect(meta).toBeTruthy();
    const kind = container.querySelector(
      `[data-testid="source-connector-kind-${baseRow.sourceId}"]`,
    );
    expect(kind?.textContent).toBe(baseRow.kind);
    const classification = container.querySelector(
      `[data-testid="source-classification-${baseRow.sourceId}"]`,
    );
    expect(classification?.textContent).toBe(baseRow.receipt.classification);
    // unassigned maintainer fallback when no person id is supplied
    const maint = container.querySelector(
      `[data-testid="source-maintainer-${baseRow.sourceId}"]`,
    );
    expect(maint?.textContent).toBe("unassigned");
  });

  it("links the maintainer to /people/{id} when one is assigned (D5)", () => {
    const row: SourceRowModel = {
      ...baseRow,
      maintainerPersonId: "p_carol",
      maintainerName: "Carol Reyes",
    };
    const { container } = render(<SourceRow row={row} />);
    const link = container.querySelector(
      `[data-testid="source-maintainer-${baseRow.sourceId}"]`,
    );
    expect(link?.getAttribute("href")).toBe("/people/p_carol");
    expect(link?.textContent).toBe("Carol Reyes");
  });

  it("links the owner domain to /domains#{name} when present (D5)", () => {
    const row: SourceRowModel = { ...baseRow, ownerDomain: "finance" };
    const { container } = render(<SourceRow row={row} />);
    const link = container.querySelector(
      `[data-testid="source-domain-${baseRow.sourceId}"]`,
    );
    expect(link?.getAttribute("href")).toBe("/domains#finance");
    expect(link?.textContent).toBe("finance");
  });

  it("renders the default-lake banner when kind=local_lake AND added_via_flow=provisioned_at_install (I4)", () => {
    const row: SourceRowModel = {
      ...baseRow,
      sourceId: "default-lake-1",
      kind: "local_lake",
      addedViaFlow: "provisioned_at_install",
      uri: "local-lake://tenant-uuid",
    };
    const { container } = render(<SourceRow row={row} />);
    const banner = container.querySelector(
      `[data-testid="source-default-banner-${row.sourceId}"]`,
    );
    expect(banner).toBeTruthy();
    expect(banner!.textContent).toMatch(/default/i);
    expect(banner!.textContent).toMatch(/minute zero/i);
    // The article carries the data-default-local-lake attribute used
    // by the page-level sort + by N2's onboarding-tail invariants.
    const article = container.querySelector(
      `[data-testid="source-${row.sourceId}"]`,
    );
    expect(article?.getAttribute("data-default-local-lake")).toBe("true");
  });

  it("does NOT render the default-lake banner for non-default sources", () => {
    // A user-driven source labelled local_lake (e.g. a local-fs power user)
    // must not pick up the banner — the marker requires both kind and
    // provisioned_at_install provenance.
    const masquerader: SourceRowModel = {
      ...baseRow,
      sourceId: "fake-lake",
      kind: "local_lake",
      addedViaFlow: "dashboard_form",
    };
    const { container } = render(<SourceRow row={masquerader} />);
    expect(
      container.querySelector(
        `[data-testid="source-default-banner-${masquerader.sourceId}"]`,
      ),
    ).toBeNull();
    // And no banner on the canonical baseRow either.
    const { container: c2 } = render(<SourceRow row={baseRow} />);
    expect(
      c2.querySelector(
        `[data-testid="source-default-banner-${baseRow.sourceId}"]`,
      ),
    ).toBeNull();
  });
});
