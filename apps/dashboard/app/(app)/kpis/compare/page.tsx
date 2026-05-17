/**
 * /kpis/compare — Phase 3 Task 3E: compare a KPI at two replay timestamps.
 *
 * Reads ``id``, ``t1``, ``t2`` from search params, calls the read+replay
 * accessor twice, and renders side-by-side hash + value comparison. Pure
 * read surface — no entry-kinds added, no projections rebuilt, no writes.
 *
 * Demonstrates replay determinism via UI: same id, same T → same hash.
 * The "matches" badge fires when both columns landed on the same row.
 */
import Link from "next/link";
import { getKpiTree } from "../../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import { replayKpiCompare } from "../../../../lib/server/kpi-compare";
import { KpiCompareView } from "../../../../components/kpis/KpiCompareView";
import { KpiCompareForm } from "../../../../components/kpis/KpiCompareForm";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { EmptyState } from "../../../../components/chrome/EmptyState";
import type { KpiNodeRow } from "../../../../lib/ledger-client.types";

export const metadata = { title: "WormBase · KPIs · Compare runs" };
export const dynamic = "force-dynamic";

function flattenIds(n: KpiNodeRow, into: string[]): void {
  into.push(n.id);
  for (const c of n.children) flattenIds(c, into);
}

function firstString(v: string | string[] | undefined): string | null {
  if (typeof v === "string" && v.length > 0) return v;
  if (Array.isArray(v) && v.length > 0 && typeof v[0] === "string") return v[0];
  return null;
}

/**
 * Convert a ``datetime-local``-style search param (``YYYY-MM-DDTHH:MM``,
 * no zone) into an ISO-8601 string the SQL ``timestamptz`` cast accepts.
 * Already-zoned values pass through; bare values get a ``:00Z`` suffix
 * appended so the cast is unambiguous.
 */
function normalizeTs(v: string | null): string | null {
  if (!v) return null;
  const trimmed = v.trim();
  if (trimmed.length === 0) return null;
  // Already carries a zone (Z, +HH, +HH:MM, -HH, -HH:MM)?
  if (/(Z|[+-]\d{2}:?\d{2})$/.test(trimmed)) return trimmed;
  // YYYY-MM-DDTHH:MM:SS → append Z.
  if (/T\d{2}:\d{2}:\d{2}$/.test(trimmed)) return `${trimmed}Z`;
  // YYYY-MM-DDTHH:MM → append :00Z.
  if (/T\d{2}:\d{2}$/.test(trimmed)) return `${trimmed}:00Z`;
  // Anything else: pass through and let Postgres' timestamptz cast judge.
  return trimmed;
}

export default async function KpiComparePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const companyId = await getCurrentCompanyId();
  const kpiId = firstString(sp.id) ?? "";
  const t1Raw = firstString(sp.t1);
  const t2Raw = firstString(sp.t2);
  const t1 = normalizeTs(t1Raw);
  const t2 = normalizeTs(t2Raw);

  // Load the tree just to populate the picker. If no tree is wired yet
  // we still render the form (free-text id) so an auditor can probe a
  // specific id by hand.
  const tree = await getKpiTree(companyId);
  const ids: string[] = [];
  if (tree) flattenIds(tree, ids);

  const haveAnyKpi = ids.length > 0;
  const resolvedKpiId =
    kpiId || (haveAnyKpi ? ids[0] : "");

  const { a: snapshotA, b: snapshotB } = resolvedKpiId
    ? await replayKpiCompare(resolvedKpiId, t1, t2, companyId)
    : { a: emptySnap(), b: emptySnap() };

  return (
    <PageBoundary surface="kpi-compare" traceQuery="?surface=kpi-compare">
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <header
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          <span
            className="wb-mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--wb-color-hash-gray)",
            }}
          >
            Pl. VII · KPI · compare two replays
          </span>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              justifyContent: "space-between",
              gap: 16,
              flexWrap: "wrap",
            }}
          >
            <h1
              style={{
                margin: 0,
                fontFamily: "var(--wb-font-serif)",
                fontSize: 34,
                fontWeight: 500,
                letterSpacing: "-0.01em",
              }}
            >
              Compare two replays
            </h1>
            <Link
              href="/kpis"
              data-testid="kpi-compare-back-to-tree"
              className="wb-mono"
              style={{
                fontSize: 11,
                letterSpacing: "0.12em",
                textTransform: "uppercase",
                color: "var(--wb-color-hash-gray)",
              }}
            >
              ← Back to KPI tree
            </Link>
          </div>
          <p
            style={{
              margin: 0,
              fontFamily: "var(--wb-font-serif)",
              fontStyle: "italic",
              color: "var(--wb-color-hash-gray)",
              maxWidth: 640,
            }}
          >
            Pick a KPI and two timestamps. Each side shows the most-recent
            ledger row for that KPI at or before its T, plus its sha256
            hash. Same id, same T, same ledger → identical hash.
          </p>
        </header>

        {!haveAnyKpi && !kpiId ? (
          <EmptyState
            testId="kpi-compare-empty"
            eyebrow="no kpis yet"
            title="The worm hasn't proposed any KPIs to compare."
            description={
              "Compare-two-replays needs an emit_kpi_node row to look up. " +
              "Connect a source or invite the worm into a channel where a " +
              "metric gets discussed; the first KPI emit lands the row."
            }
            cta={{ label: "Back to KPI tree", href: "/kpis" }}
          />
        ) : (
          <>
            <KpiCompareForm
              kpiId={resolvedKpiId}
              initialT1={t1Raw}
              initialT2={t2Raw}
              kpiIds={ids}
            />
            <KpiCompareView
              kpiId={resolvedKpiId}
              t1={t1}
              t2={t2}
              snapshotA={snapshotA}
              snapshotB={snapshotB}
            />
          </>
        )}
      </div>
    </PageBoundary>
  );
}

function emptySnap() {
  return {
    found: false as const,
    value: null,
    hash: "",
    rowTs: null,
    rowSeq: 0,
    scanCount: 0,
  };
}
