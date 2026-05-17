/**
 * SourceRow freshness feed tests — Phase 3 Task 3D (validation gap P2.8).
 *
 * Pins the freshness column, drift indicator, and 30-day maintenance
 * timeline rendered on each source row. The data is read-only — every
 * field comes from the `projection_sources` projection (`last_seen`)
 * and the lake-maintainer's `emit_source_*` ledger entries (drift +
 * timeline). No new entry kinds.
 */
import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { SourceRow } from "../../components/sources/SourceRow";
import { SourceListInteractive } from "../../components/sources/SourceListInteractive";
import type {
  SourceRow as SourceRowModel,
  MaintenanceSignal,
} from "../../lib/ledger-client.types";

const baseRow: SourceRowModel = {
  sourceId: "src_freshness",
  uri: "snowflake://demo.q3_revenue",
  kind: "table",
  addedByPerson: "carla-bot",
  addedAt: "2026-04-23T14:02:00Z",
  addedViaFlow: "drop_and_profile",
  addedInResponseTo: null,
  rowCount: 10000,
  lastProfileTs: "2026-04-23T14:04:00Z",
  receipt: {
    hash: "abcd1234",
    source: "snowflake://demo.q3_revenue",
    owner: "carla-bot",
    classification: "internal",
  },
};

describe("SourceRow freshness column (P2.8)", () => {
  it("renders a freshness chip when lastSeen is set", () => {
    const row: SourceRowModel = {
      ...baseRow,
      lastSeen: "2026-05-03T10:00:00Z",
    };
    const { container } = render(<SourceRow row={row} />);
    const chip = container.querySelector(
      `[data-testid="source-freshness-${row.sourceId}"]`,
    );
    expect(chip).toBeTruthy();
    expect(chip!.textContent).toMatch(/last seen/i);
  });

  it("renders an honest empty-state freshness chip when lastSeen is null", () => {
    const row: SourceRowModel = {
      ...baseRow,
      lastSeen: null,
    };
    const { container } = render(<SourceRow row={row} />);
    const chip = container.querySelector(
      `[data-testid="source-freshness-${row.sourceId}"]`,
    );
    expect(chip).toBeTruthy();
    // Honest fallback: don't pretend a maintainer has run when it hasn't.
    expect(chip!.textContent).toMatch(/never seen|not yet/i);
  });

  it("falls back to lastProfileTs when lastSeen is undefined (back-compat)", () => {
    // Pre-Wave-G fixtures don't carry lastSeen; the row should still render
    // a meaningful freshness chip from lastProfileTs to avoid a regression
    // on rows folded from older ledgers.
    const { container } = render(<SourceRow row={baseRow} />);
    const chip = container.querySelector(
      `[data-testid="source-freshness-${baseRow.sourceId}"]`,
    );
    expect(chip).toBeTruthy();
  });
});

describe("SourceRow drift indicator (P2.8)", () => {
  it("shows a drift badge when driftDetected is true", () => {
    const row: SourceRowModel = {
      ...baseRow,
      driftDetected: true,
      driftReason: "schema hash changed",
    };
    const { container } = render(<SourceRow row={row} />);
    const badge = container.querySelector(
      `[data-testid="source-drift-${row.sourceId}"]`,
    );
    expect(badge).toBeTruthy();
    expect(badge!.textContent).toMatch(/drift/i);
    expect(badge!.getAttribute("data-drift")).toBe("true");
    // The reason is surfaced via title for hover (and accessible name).
    expect(badge!.getAttribute("title")).toMatch(/schema hash changed/);
  });

  it("does not render a drift badge when driftDetected is false / undefined", () => {
    const { container } = render(<SourceRow row={baseRow} />);
    expect(
      container.querySelector(
        `[data-testid="source-drift-${baseRow.sourceId}"]`,
      ),
    ).toBeNull();
  });
});

describe("SourceRow maintenance signal timeline (P2.8)", () => {
  it("renders an honest empty-state when no signals are present", () => {
    const row: SourceRowModel = {
      ...baseRow,
      maintenanceSignals: [],
    };
    const { container } = render(<SourceRow row={row} />);
    const timeline = container.querySelector(
      `[data-testid="source-maintenance-timeline-${row.sourceId}"]`,
    );
    expect(timeline).toBeTruthy();
    expect(timeline!.textContent).toMatch(/no maintenance signals/i);
  });

  it("renders one chip per maintenance signal, newest first", () => {
    const signals: MaintenanceSignal[] = [
      {
        kind: "drift",
        ts: "2026-05-02T10:00:00Z",
        tool: "emit_source_drift_detected",
        reason: "schema hash changed",
      },
      {
        kind: "staleness",
        ts: "2026-04-30T10:00:00Z",
        tool: "emit_source_staleness_signaled",
        reason: null,
      },
      {
        kind: "classification_refresh",
        ts: "2026-04-15T10:00:00Z",
        tool: "emit_source_classification_refreshed",
        reason: "PII column detected",
      },
    ];
    const row: SourceRowModel = {
      ...baseRow,
      maintenanceSignals: signals,
    };
    const { container } = render(<SourceRow row={row} />);
    const timeline = container.querySelector(
      `[data-testid="source-maintenance-timeline-${row.sourceId}"]`,
    );
    expect(timeline).toBeTruthy();
    const chips = timeline!.querySelectorAll(
      `[data-testid^="source-maintenance-signal-${row.sourceId}-"]`,
    );
    expect(chips.length).toBe(3);
    // First chip is the newest (drift on 2026-05-02).
    expect(chips[0].getAttribute("data-kind")).toBe("drift");
    expect(chips[1].getAttribute("data-kind")).toBe("staleness");
    expect(chips[2].getAttribute("data-kind")).toBe("classification_refresh");
  });

  it("renders no timeline section when maintenanceSignals is undefined (back-compat)", () => {
    const { container } = render(<SourceRow row={baseRow} />);
    const timeline = container.querySelector(
      `[data-testid="source-maintenance-timeline-${baseRow.sourceId}"]`,
    );
    // Pre-3D fixtures don't carry maintenanceSignals — the section is
    // omitted entirely so older rows render exactly as before.
    expect(timeline).toBeNull();
  });
});

describe("SourceListInteractive freshness sort (P2.8)", () => {
  function makeRow(
    overrides: Partial<SourceRowModel> & { sourceId: string },
  ): SourceRowModel {
    return {
      ...baseRow,
      ...overrides,
      sourceId: overrides.sourceId,
    };
  }

  const fresh = makeRow({
    sourceId: "src_fresh",
    uri: "snowflake://demo.fresh",
    lastSeen: "2026-05-03T10:00:00Z",
  });
  const middle = makeRow({
    sourceId: "src_middle",
    uri: "snowflake://demo.middle",
    lastSeen: "2026-04-29T10:00:00Z",
  });
  const stale = makeRow({
    sourceId: "src_stale",
    uri: "snowflake://demo.stale",
    lastSeen: "2026-04-15T10:00:00Z",
  });
  const neverSeen = makeRow({
    sourceId: "src_never",
    uri: "snowflake://demo.never",
    lastSeen: null,
    // No profile either — this row has never been touched by any
    // maintainer or profile run, so freshnessScore returns -Infinity
    // and stale-sort lands the row at the very top.
    lastProfileTs: null,
  });

  it("renders three sort buttons (default / fresh / stale)", () => {
    const { container } = render(
      <SourceListInteractive
        rows={[fresh, stale, middle]}
        currentPersonId={null}
      />,
    );
    expect(
      container.querySelector('[data-testid="sources-sort-default"]'),
    ).toBeTruthy();
    expect(
      container.querySelector('[data-testid="sources-sort-fresh"]'),
    ).toBeTruthy();
    expect(
      container.querySelector('[data-testid="sources-sort-stale"]'),
    ).toBeTruthy();
  });

  it("clicking 'freshest' orders rows newest-first by lastSeen", () => {
    const { container, getByTestId } = render(
      <SourceListInteractive
        rows={[stale, fresh, middle]}
        currentPersonId={null}
      />,
    );
    fireEvent.click(getByTestId("sources-sort-fresh"));
    const ids = Array.from(
      container.querySelectorAll('[data-testid^="source-row-clickable-"]'),
    ).map((n) => n.getAttribute("data-testid"));
    expect(ids).toEqual([
      "source-row-clickable-src_fresh",
      "source-row-clickable-src_middle",
      "source-row-clickable-src_stale",
    ]);
  });

  it("clicking 'stalest' orders rows oldest-first by lastSeen and pushes never-seen rows last", () => {
    // Note: never-seen sentinel is -Infinity, so under "stalest" (asc)
    // it lands at the very top (oldest). That's the operator-friendly
    // ordering: a maintainer that never fired against a source is the
    // stalest possible state.
    const { container, getByTestId } = render(
      <SourceListInteractive
        rows={[fresh, stale, neverSeen]}
        currentPersonId={null}
      />,
    );
    fireEvent.click(getByTestId("sources-sort-stale"));
    const ids = Array.from(
      container.querySelectorAll('[data-testid^="source-row-clickable-"]'),
    ).map((n) => n.getAttribute("data-testid"));
    expect(ids).toEqual([
      "source-row-clickable-src_never",
      "source-row-clickable-src_stale",
      "source-row-clickable-src_fresh",
    ]);
  });

  it("default lake pins to top regardless of freshness sort", () => {
    const defaultLake = makeRow({
      sourceId: "default-lake",
      kind: "local_lake",
      addedViaFlow: "provisioned_at_install",
      uri: "local-lake://tenant",
      lastSeen: "2026-04-01T10:00:00Z", // very stale
    });
    const { container, getByTestId } = render(
      <SourceListInteractive
        rows={[fresh, defaultLake, stale]}
        currentPersonId={null}
      />,
    );
    fireEvent.click(getByTestId("sources-sort-fresh"));
    const ids = Array.from(
      container.querySelectorAll('[data-testid^="source-row-clickable-"]'),
    ).map((n) => n.getAttribute("data-testid"));
    expect(ids[0]).toBe("source-row-clickable-default-lake");
    // Even though the lake is staler than `fresh`, the pin keeps it on top.
  });
});
