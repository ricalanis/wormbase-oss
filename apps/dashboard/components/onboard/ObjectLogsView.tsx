/**
 * ObjectLogsView — universal logs surface for ``@logs <object>``
 * (Onboarding Sub-wave B, 2026-05-30).
 *
 * Renders an ``ObjectLogsPage`` (paginated ledger entries filtered by
 * id-match against payload args). The shape mirrors v2.A's subscription
 * audit panel — a thin scrollable table of (kind, ts, quadrant,
 * summary) rows.
 *
 * Pagination is link-based (``?offset=N``) so the page stays a server
 * component; no client-side state.
 */

import Link from "next/link";
import type { JSX } from "react";

import type {
  ObjectLogsPage,
  StatusKind,
} from "../../lib/onboard";

export interface ObjectLogsViewProps {
  kind: StatusKind;
  objectId: string;
  page: ObjectLogsPage;
  /** Current offset (used to compose the prev/next links). */
  offset: number;
  /** Limit per page (matched against the accessor default). */
  limit: number;
}

function quadrantColor(q: ObjectLogsPage["entries"][number]["quadrant"]): string {
  switch (q) {
    case "propose":
      return "var(--wb-color-hash-gray, #7c7569)";
    case "execute":
      return "var(--wb-color-aged-ink, #2a2620)";
    case "verify":
      return "var(--wb-color-botanical-green-deep, #2d5d3a)";
    case "resolve":
      return "var(--wb-color-sepia-warning-deep, #b6741c)";
  }
}

export function ObjectLogsView({
  kind,
  objectId,
  page,
  offset,
  limit,
}: ObjectLogsViewProps): JSX.Element {
  const baseHref = `/logs/${kind}/${encodeURIComponent(objectId)}`;
  const prevOffset = Math.max(0, offset - limit);
  const showPrev = offset > 0;
  const showNext = page.nextOffset !== null;

  return (
    <section
      data-testid={`object-logs-${kind}`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 14,
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
          {kind} · logs
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 28,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          Ledger entries for {objectId}
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          Raw-ledger scan filtered by id-match. {page.total} entr
          {page.total === 1 ? "y" : "ies"} matched in the most-recent window.
        </p>
      </header>

      {page.entries.length === 0 ? (
        <div
          data-testid={`object-logs-empty-${kind}`}
          style={{
            border: "1px dashed var(--wb-color-aged-ink)",
            padding: 24,
            background: "var(--wb-color-paper)",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            no entries
          </span>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              fontSize: 13,
              color: "var(--wb-color-aged-ink)",
              maxWidth: 720,
            }}
          >
            No ledger entries reference this id in the most-recent
            {" "}{500}-entry scan window. The id may be stale, the
            scan window too small, or the object has never received a
            write.
          </p>
        </div>
      ) : (
        <ul
          data-testid={`object-logs-table-${kind}`}
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            border: "1px solid var(--wb-color-paper-edge)",
            borderTop: "none",
          }}
        >
          {page.entries.map((entry) => (
            <li
              key={entry.hash}
              data-testid={`object-log-row-${entry.hash}`}
              style={{
                display: "grid",
                gridTemplateColumns:
                  "minmax(160px, 200px) minmax(140px, 180px) minmax(80px, 100px) 1fr",
                gap: 12,
                alignItems: "baseline",
                padding: "10px 12px",
                borderTop: "1px solid var(--wb-color-paper-edge)",
                background: "var(--wb-color-paper)",
              }}
            >
              <span
                className="wb-mono"
                style={{
                  fontSize: 11,
                  color: "var(--wb-color-hash-gray)",
                }}
              >
                {entry.ts}
              </span>
              <code
                className="wb-mono"
                style={{
                  fontSize: 12,
                  color: "var(--wb-color-aged-ink)",
                }}
              >
                {entry.kind}
              </code>
              <span
                className="wb-mono"
                data-testid={`object-log-quadrant-${entry.hash}`}
                style={{
                  fontSize: 10,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: quadrantColor(entry.quadrant),
                }}
              >
                {entry.quadrant}
              </span>
              <span
                style={{
                  fontFamily: "var(--wb-font-monospace, ui-monospace)",
                  fontSize: 11,
                  color: "var(--wb-color-aged-ink)",
                  overflowWrap: "anywhere",
                }}
              >
                {entry.summary}
              </span>
            </li>
          ))}
        </ul>
      )}

      <nav
        data-testid={`object-logs-pager-${kind}`}
        style={{
          display: "flex",
          gap: 12,
          marginTop: 6,
          flexWrap: "wrap",
        }}
      >
        {showPrev ? (
          <Link
            href={`${baseHref}?offset=${prevOffset}&limit=${limit}`}
            data-testid={`object-logs-prev-${kind}`}
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              padding: "6px 12px",
              border: "1px solid var(--wb-color-aged-ink)",
              background: "transparent",
              color: "var(--wb-color-aged-ink)",
              textDecoration: "none",
            }}
          >
            ← Previous
          </Link>
        ) : null}
        {showNext ? (
          <Link
            href={`${baseHref}?offset=${page.nextOffset}&limit=${limit}`}
            data-testid={`object-logs-next-${kind}`}
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.1em",
              textTransform: "uppercase",
              padding: "6px 12px",
              border: "1px solid var(--wb-color-aged-ink)",
              background: "transparent",
              color: "var(--wb-color-aged-ink)",
              textDecoration: "none",
            }}
          >
            Next →
          </Link>
        ) : null}
        <Link
          href={`/status/${kind}/${encodeURIComponent(objectId)}`}
          data-testid={`object-logs-status-link-${kind}`}
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            padding: "6px 12px",
            border: "1px solid var(--wb-color-aged-ink)",
            background: "var(--wb-color-paper)",
            color: "var(--wb-color-aged-ink)",
            textDecoration: "none",
          }}
        >
          See status
        </Link>
      </nav>
    </section>
  );
}
