/**
 * BeforeAfterDelta component tests — L2 Sub-wave D (2026-06-09).
 *
 * Pins per-drift_kind rendering for all 5 enum values:
 *
 *   * ``column_type_changed`` — renders ``before → after`` (e.g.
 *     ``varchar(255) → text``) with both descriptors visible.
 *   * ``table_added`` / ``column_added`` — renders ``+ <descriptor>``
 *     in additive green; only ``after`` is meaningful.
 *   * ``table_removed`` / ``column_removed`` — renders ``− <descriptor>``
 *     with strikethrough; only ``before`` is meaningful.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { BeforeAfterDelta } from "../BeforeAfterDelta";

describe("BeforeAfterDelta — column_type_changed", () => {
  it("renders before → after with both type descriptors", () => {
    render(
      <BeforeAfterDelta
        driftKind="column_type_changed"
        before={{ type: "varchar(255)" }}
        after={{ type: "text" }}
        testIdSuffix="t-1"
      />,
    );
    expect(
      screen.getByTestId("catalog-drift-delta-before-t-1"),
    ).toHaveTextContent("varchar(255)");
    expect(
      screen.getByTestId("catalog-drift-delta-after-t-1"),
    ).toHaveTextContent("text");
    expect(screen.getByTestId("catalog-drift-delta-t-1")).toBeInTheDocument();
  });

  it("data-drift-kind attribute is set to the kind", () => {
    render(
      <BeforeAfterDelta
        driftKind="column_type_changed"
        before={{ type: "int" }}
        after={{ type: "bigint" }}
        testIdSuffix="t-2"
      />,
    );
    const delta = screen.getByTestId("catalog-drift-delta-t-2");
    expect(delta.getAttribute("data-drift-kind")).toBe("column_type_changed");
  });
});

describe("BeforeAfterDelta — table_added", () => {
  it("renders + <table_id> in additive style from after dict", () => {
    render(
      <BeforeAfterDelta
        driftKind="table_added"
        before={null}
        after={{ table_id: "orders_v2" }}
        testIdSuffix="ta-1"
      />,
    );
    const delta = screen.getByTestId("catalog-drift-delta-ta-1");
    expect(delta).toHaveTextContent("+");
    expect(
      screen.getByTestId("catalog-drift-delta-after-ta-1"),
    ).toHaveTextContent("orders_v2");
  });

  it("does NOT render a 'before' descriptor", () => {
    render(
      <BeforeAfterDelta
        driftKind="table_added"
        before={null}
        after={{ table_id: "events_v3" }}
        testIdSuffix="ta-2"
      />,
    );
    expect(
      screen.queryByTestId("catalog-drift-delta-before-ta-2"),
    ).toBeNull();
  });
});

describe("BeforeAfterDelta — column_added", () => {
  it("renders + <column_name> from after dict", () => {
    render(
      <BeforeAfterDelta
        driftKind="column_added"
        before={null}
        after={{ column_name: "first_seen_at" }}
        testIdSuffix="ca-1"
      />,
    );
    expect(
      screen.getByTestId("catalog-drift-delta-after-ca-1"),
    ).toHaveTextContent("first_seen_at");
    expect(screen.getByTestId("catalog-drift-delta-ca-1")).toHaveTextContent(
      "+",
    );
  });
});

describe("BeforeAfterDelta — table_removed", () => {
  it("renders − <table_id> from before dict with strikethrough", () => {
    render(
      <BeforeAfterDelta
        driftKind="table_removed"
        before={{ table_id: "legacy_audit" }}
        after={null}
        testIdSuffix="tr-1"
      />,
    );
    const beforeEl = screen.getByTestId("catalog-drift-delta-before-tr-1");
    expect(beforeEl).toHaveTextContent("legacy_audit");
    expect(beforeEl.getAttribute("style") ?? "").toContain("line-through");
    expect(screen.getByTestId("catalog-drift-delta-tr-1")).toHaveTextContent(
      "−",
    );
  });

  it("does NOT render an 'after' descriptor", () => {
    render(
      <BeforeAfterDelta
        driftKind="table_removed"
        before={{ table_id: "stale_events" }}
        after={null}
        testIdSuffix="tr-2"
      />,
    );
    expect(
      screen.queryByTestId("catalog-drift-delta-after-tr-2"),
    ).toBeNull();
  });
});

describe("BeforeAfterDelta — column_removed", () => {
  it("renders − <column_name> from before dict with strikethrough", () => {
    render(
      <BeforeAfterDelta
        driftKind="column_removed"
        before={{ column_name: "deprecated_flag" }}
        after={null}
        testIdSuffix="cr-1"
      />,
    );
    const beforeEl = screen.getByTestId("catalog-drift-delta-before-cr-1");
    expect(beforeEl).toHaveTextContent("deprecated_flag");
    expect(beforeEl.getAttribute("style") ?? "").toContain("line-through");
  });
});

describe("BeforeAfterDelta — descriptor fallbacks", () => {
  it("falls back to JSON-stringify when no recognized key present", () => {
    render(
      <BeforeAfterDelta
        driftKind="table_added"
        before={null}
        after={{ arbitrary_key: "value" }}
        testIdSuffix="fb-1"
      />,
    );
    const afterEl = screen.getByTestId("catalog-drift-delta-after-fb-1");
    expect(afterEl.textContent).toContain("arbitrary_key");
  });

  it("data-drift-kind attribute is set for every drift_kind", () => {
    const kinds = [
      "table_added",
      "table_removed",
      "column_added",
      "column_removed",
      "column_type_changed",
    ] as const;
    for (const kind of kinds) {
      const before =
        kind === "table_added" || kind === "column_added"
          ? null
          : { type: "A", table_id: "t", column_name: "c" };
      const after =
        kind === "table_removed" || kind === "column_removed"
          ? null
          : { type: "B", table_id: "t", column_name: "c" };
      const { unmount } = render(
        <BeforeAfterDelta
          driftKind={kind}
          before={before}
          after={after}
          testIdSuffix={`k-${kind}`}
        />,
      );
      const el = screen.getByTestId(`catalog-drift-delta-k-${kind}`);
      expect(el.getAttribute("data-drift-kind")).toBe(kind);
      unmount();
    }
  });
});
