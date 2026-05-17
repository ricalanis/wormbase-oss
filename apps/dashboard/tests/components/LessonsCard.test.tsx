/**
 * LessonsCard — Demo-day P9 component test.
 *
 * Covers:
 *   - Renders header chrome.
 *   - Empty state when no lessons exist (per CLAUDE.md ¶9 honesty).
 *   - Per-scope columns render their counts.
 *   - Each lesson item links to /trace?ref_id=<prior_keep_id>.
 *   - applied_at presence flips the badge from "pending" → "applied @<seq>".
 *   - lesson_text + structured features (change_kind, delta_label) render.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { LessonsCard } from "../../components/research/LessonsCard";
import type { ExperimentLessonRow } from "../../lib/ledger-client.types";

function makeLesson(overrides: Partial<ExperimentLessonRow> = {}): ExperimentLessonRow {
  return {
    priorKeepId: "prior-keep-id-1",
    scope: "person",
    lessonText:
      "For position 'cfo' moving 'revenue', a kpi_definition on " +
      "'revenue_forecast' with predicate 'exclude_promo_signups_from_cohort' " +
      "was kept: observed +0.0360 hit ≥85% of expected +0.0400.",
    lessonFeatures: {
      metric: "revenue",
      position: "cfo",
      change_kind: "kpi_definition",
      change_target: "revenue_forecast",
      change_predicate: "exclude_promo_signups_from_cohort",
      delta_label: "hit_expectation",
      observed_delta: "+0.0360",
      expected_delta: "+0.0400",
      adjacent_discard_count: "1",
      predicate_was_novel_vs_discards: "true",
    },
    appliedToProposer: "autoresearch_loop",
    appliedAt: null,
    proposedBy: "autoresearch_loop",
    extractedAt: "2026-04-28T10:00:00Z",
    ledgerSeq: 42,
    receipt: {
      hash: "abc123def456",
      source: "autoresearch_loop · learn",
      owner: "autoresearch_loop",
      classification: "internal",
    },
    ...overrides,
  };
}

const EMPTY = { person: [], team: [], company: [] };

describe("LessonsCard", () => {
  it("renders the header chrome", () => {
    render(<LessonsCard byScope={EMPTY} />);
    expect(screen.getByTestId("research-lessons-card")).toBeTruthy();
    expect(screen.getByText("Lessons the worm has learnt")).toBeTruthy();
    expect(screen.getByText(/Karpathy learn step/i)).toBeTruthy();
  });

  it("renders an honest empty state when no lessons exist", () => {
    render(<LessonsCard byScope={EMPTY} />);
    const empty = screen.getByTestId("lessons-empty");
    expect(empty).toBeTruthy();
    expect(empty.textContent).toMatch(/no lessons yet/i);
    // No columns render in the empty branch.
    expect(screen.queryByTestId("lessons-columns")).toBeNull();
  });

  it("renders the three per-scope columns when lessons exist", () => {
    render(
      <LessonsCard
        byScope={{
          person: [makeLesson()],
          team: [],
          company: [],
        }}
      />,
    );
    expect(screen.getByTestId("lessons-columns")).toBeTruthy();
    expect(screen.getByTestId("lessons-scope-person")).toBeTruthy();
    expect(screen.getByTestId("lessons-scope-team")).toBeTruthy();
    expect(screen.getByTestId("lessons-scope-company")).toBeTruthy();
  });

  it("renders an empty-state per-column when only some scopes have lessons", () => {
    render(
      <LessonsCard
        byScope={{
          person: [makeLesson()],
          team: [],
          company: [],
        }}
      />,
    );
    expect(screen.queryByTestId("lessons-scope-person-empty")).toBeNull();
    expect(screen.getByTestId("lessons-scope-team-empty")).toBeTruthy();
    expect(screen.getByTestId("lessons-scope-company-empty")).toBeTruthy();
  });

  it("renders the lesson_text body for each lesson", () => {
    render(
      <LessonsCard
        byScope={{
          person: [makeLesson()],
          team: [],
          company: [],
        }}
      />,
    );
    expect(
      screen.getByText(/exclude_promo_signups_from_cohort/i),
    ).toBeTruthy();
  });

  it("links each lesson to /trace?ref_id=<prior_keep_id>", () => {
    const lesson = makeLesson({ priorKeepId: "uuid-prior-1" });
    render(
      <LessonsCard byScope={{ person: [lesson], team: [], company: [] }} />,
    );
    const link = screen.getByTestId(
      `lesson-link-${lesson.priorKeepId}`,
    ) as HTMLAnchorElement;
    expect(link.tagName.toLowerCase()).toBe("a");
    expect(link.getAttribute("href")).toBe(
      "/trace?ref_id=uuid-prior-1&surface=research",
    );
  });

  it("renders 'pending' when applied_at is null and 'applied @<seq>' otherwise", () => {
    const pending = makeLesson({ priorKeepId: "p-pending", appliedAt: null });
    const applied = makeLesson({ priorKeepId: "p-applied", appliedAt: 137 });
    render(
      <LessonsCard
        byScope={{ person: [pending, applied], team: [], company: [] }}
      />,
    );
    expect(
      screen.getByTestId("lesson-applied-p-pending").textContent,
    ).toMatch(/pending/i);
    expect(
      screen.getByTestId("lesson-applied-p-applied").textContent,
    ).toMatch(/applied @137/);
  });

  it("renders structured feature pills for change_kind / change_target / delta_label", () => {
    render(
      <LessonsCard
        byScope={{ person: [makeLesson()], team: [], company: [] }}
      />,
    );
    expect(screen.getByText("kpi_definition")).toBeTruthy();
    expect(screen.getByText("revenue_forecast")).toBeTruthy();
    expect(screen.getByText("hit_expectation")).toBeTruthy();
  });

  it("counts lessons in the scope header", () => {
    render(
      <LessonsCard
        byScope={{
          person: [makeLesson({ priorKeepId: "1" }), makeLesson({ priorKeepId: "2" })],
          team: [],
          company: [makeLesson({ priorKeepId: "3", scope: "company" })],
        }}
      />,
    );
    // Person header must read "Mine · 2"
    const personHeader = screen.getByTestId("lessons-scope-person");
    expect(personHeader.textContent).toMatch(/Mine.*2/);
    const companyHeader = screen.getByTestId("lessons-scope-company");
    expect(companyHeader.textContent).toMatch(/Company.*1/);
  });
});
