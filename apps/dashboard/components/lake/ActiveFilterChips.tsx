/**
 * ActiveFilterChips — shared filter-chip row for consumer lake pages
 * that accept ``upstream_*_id`` URL params (2026-05-16).
 *
 * Renders a horizontal row of monospaced chips, one per active filter
 * key, with a "Clear filters" link that navigates back to the base
 * page URL. When no filters are active, the component returns
 * ``null`` (honest empty — no chrome when no filter applies).
 *
 * Per the reverse-arc bundle (commit ``7311ecf``) and L4↦L2 Half B
 * close-out (commit ``14064d5``), four consumer lake pages
 * (/lake/schema-impact, /lake/column-classification,
 * /lake/entity-stitches, /lake/quality-checks) accept URL params
 * that filter the rendered tables to rows derived from a specific
 * upstream entity (semantic type, classification, lineage edge,
 * source/table/column tuple). This component surfaces the active
 * filter set in a consistent way across all four surfaces.
 *
 * No state, no client-side reactivity — purely declarative.
 */

import Link from "next/link";

export interface ActiveFilterChipsProps {
  /** Active filter map. Keys with ``undefined`` / empty values are
   *  ignored. When all values are absent, the component renders
   *  nothing. */
  filter: Record<string, string | undefined>;
  /** Base page URL the "Clear filters" link navigates to (i.e. the
   *  page URL with no query params). */
  clearHref: string;
  /** Optional friendly labels per filter key. When a key has no
   *  label override, the raw key is rendered. */
  labels?: Record<string, string>;
  /** Optional testid override (default ``active-filter-chips``). */
  testId?: string;
}

export function ActiveFilterChips({
  filter,
  clearHref,
  labels,
  testId,
}: ActiveFilterChipsProps): JSX.Element | null {
  const active = Object.entries(filter).filter(
    ([, v]) => typeof v === "string" && v.length > 0,
  ) as Array<[string, string]>;
  if (active.length === 0) return null;

  return (
    <section
      data-testid={testId ?? "active-filter-chips"}
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 8,
        padding: "8px 12px",
        border: "1px solid var(--wb-color-sepia-warning-deep, #b6741c)",
        background: "var(--wb-color-paper-deep, #f4eedb)",
        fontFamily: "var(--wb-font-serif)",
        fontSize: 12,
      }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--wb-color-sepia-warning-deep, #b6741c)",
        }}
      >
        Filtered by:
      </span>
      {active.map(([k, v]) => (
        <span
          key={k}
          data-testid={`active-filter-chip-${k}`}
          className="wb-mono"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "2px 8px",
            border: "1px solid var(--wb-color-paper-edge, #d8d2c2)",
            background: "var(--wb-color-paper, #f8f3e1)",
            color: "var(--wb-color-aged-ink, #2a2620)",
            fontSize: 11,
          }}
        >
          <span
            style={{
              fontSize: 10,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray, #7c7569)",
            }}
          >
            {labels?.[k] ?? k}:
          </span>
          <code style={{ fontSize: 11 }}>{v}</code>
        </span>
      ))}
      <Link
        href={clearHref}
        data-testid="active-filter-clear-link"
        className="wb-mono"
        style={{
          marginLeft: "auto",
          fontSize: 10,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--wb-color-botanical-green-deep, #2d5d3a)",
          textDecoration: "underline",
        }}
      >
        Clear filters
      </Link>
    </section>
  );
}
