"use client";
/**
 * LessonsCard — /research per-scope ``experiment_lesson`` surface (P9).
 *
 * The Karpathy autoresearch loop's *learn step* visualised: every kept
 * experiment produces a structured lesson (lesson_text + lesson_features)
 * that the next proposer reads. This card renders the trailing 5 lessons
 * per scope (person / team / company); each row clicks through to /trace
 * filtered by the lesson's ``prior_keep_id`` (the kept experiment it
 * learned from).
 *
 * Empty-state honesty (CLAUDE.md ¶9): when no lessons exist, the card
 * renders a meaningful "the worm has not learnt yet" message instead of
 * a fixture row. Once the autoresearch loop fires its first keep, the
 * lesson appears within one polling cycle.
 *
 * Visual chrome mirrors ResearchOverviewCard: editorial ledger feel,
 * sepia rule lines, wb-mono labels, serif body. No icons, no animations.
 */

import type { ExperimentLessonRow, LessonScope } from "../../lib/ledger-client.types";

const SCOPE_LABELS: Record<LessonScope, string> = {
  person: "Mine",
  team: "Team",
  company: "Company",
};

const SCOPE_HINTS: Record<LessonScope, string> = {
  person: "Lessons the worm extracted from your kept experiments.",
  team: "Lessons from team-scope keeps; shared by every team member.",
  company: "Lessons from company-wide keeps. The apex of the loop.",
};

export interface LessonsCardProps {
  byScope: {
    person: ExperimentLessonRow[];
    team: ExperimentLessonRow[];
    company: ExperimentLessonRow[];
  };
}

export function LessonsCard({ byScope }: LessonsCardProps) {
  const totalCount =
    byScope.person.length + byScope.team.length + byScope.company.length;

  return (
    <section
      data-testid="research-lessons-card"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        borderTop: "1px solid var(--wb-color-rule-line)",
        paddingTop: 24,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          Karpathy learn step · per scope
        </span>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-lg)",
            fontWeight: 500,
          }}
        >
          Lessons the worm has learnt
        </h2>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-sm)",
            color: "var(--wb-color-hash-gray)",
            fontStyle: "italic",
          }}
        >
          When an experiment is kept, the harness writes back a structured
          lesson. The next proposer reads it. This is the loop closing on
          itself.
        </p>
      </header>

      {totalCount === 0 ? (
        <p
          data-testid="lessons-empty"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            paddingTop: 12,
          }}
        >
          No lessons yet — the worm extracts a lesson from every kept
          experiment. Once the autoresearch loop fires its first keep, it
          lands here.
        </p>
      ) : (
        <div
          data-testid="lessons-columns"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 24,
          }}
        >
          {(["person", "team", "company"] as const).map((scope) => (
            <ScopeColumn
              key={scope}
              scope={scope}
              lessons={byScope[scope]}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ScopeColumn({
  scope,
  lessons,
}: {
  scope: LessonScope;
  lessons: ExperimentLessonRow[];
}) {
  return (
    <section
      data-testid={`lessons-scope-${scope}`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        borderTop: "1px solid var(--wb-color-paper-edge)",
        paddingTop: 12,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--wb-color-aged-ink)",
          }}
        >
          {SCOPE_LABELS[scope]} · {lessons.length}
        </span>
        <span
          style={{
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-xs)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {SCOPE_HINTS[scope]}
        </span>
      </header>

      {lessons.length === 0 ? (
        <p
          data-testid={`lessons-scope-${scope}-empty`}
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-sm)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          No {SCOPE_LABELS[scope].toLowerCase()}-scope lessons yet.
        </p>
      ) : (
        <ul
          data-testid={`lessons-scope-${scope}-list`}
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          {lessons.map((lesson) => (
            <LessonItem key={lesson.priorKeepId} lesson={lesson} />
          ))}
        </ul>
      )}
    </section>
  );
}

function LessonItem({ lesson }: { lesson: ExperimentLessonRow }) {
  // Click-through to /trace filtered by prior_keep_id (the kept experiment
  // this lesson was extracted from).
  const traceHref = `/trace?ref_id=${encodeURIComponent(lesson.priorKeepId)}&surface=research`;
  const features = lesson.lessonFeatures ?? {};
  const metric = features.metric ?? "";
  const changeKind = features.change_kind ?? "";
  const changeTarget = features.change_target ?? "";
  const deltaLabel = features.delta_label ?? "";
  const novel = features.predicate_was_novel_vs_discards === "true";

  return (
    <li
      data-testid={`lesson-item-${lesson.priorKeepId}`}
      style={{
        borderBottom: "1px solid var(--wb-color-paper-edge)",
        paddingBottom: 10,
      }}
    >
      <a
        href={traceHref}
        data-testid={`lesson-link-${lesson.priorKeepId}`}
        style={{
          textDecoration: "none",
          color: "inherit",
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        <header
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 8,
            alignItems: "baseline",
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {metric || "—"}
            {novel ? " · novel" : ""}
          </span>
          <span
            className="wb-mono"
            data-testid={`lesson-applied-${lesson.priorKeepId}`}
            style={{
              fontSize: 10,
              color:
                lesson.appliedAt !== null
                  ? "var(--wb-color-botanical-green)"
                  : "var(--wb-color-hash-gray)",
            }}
            title={
              lesson.appliedAt !== null
                ? `Applied at ledger seq ${lesson.appliedAt}`
                : "Extracted but not yet applied"
            }
          >
            {lesson.appliedAt !== null ? `applied @${lesson.appliedAt}` : "pending"}
          </span>
        </header>

        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: "var(--wb-text-sm)",
            lineHeight: 1.45,
          }}
        >
          {lesson.lessonText}
        </p>

        <footer
          style={{
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            alignItems: "baseline",
          }}
        >
          {changeKind ? (
            <FeaturePill label={changeKind} />
          ) : null}
          {changeTarget ? (
            <FeaturePill label={changeTarget} />
          ) : null}
          {deltaLabel ? (
            <FeaturePill label={deltaLabel} />
          ) : null}
          <span
            className="wb-mono"
            style={{
              marginLeft: "auto",
              fontSize: 10,
              color: "var(--wb-color-hash-gray)",
            }}
          >
            {lesson.receipt.hash}
          </span>
        </footer>
      </a>
    </li>
  );
}

function FeaturePill({ label }: { label: string }) {
  return (
    <span
      className="wb-mono"
      style={{
        fontSize: 9,
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        padding: "2px 6px",
        borderRadius: 2,
        background: "var(--wb-color-paper-edge)",
        color: "var(--wb-color-aged-ink)",
      }}
    >
      {label}
    </span>
  );
}
