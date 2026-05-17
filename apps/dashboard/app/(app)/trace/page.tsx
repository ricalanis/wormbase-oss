import { getTraceEntries } from "../../../lib/ledger-client";
import { getCurrentCompanyId } from "../../../lib/tenant-cookies";
import { TraceRow } from "../../../components/trace/TraceRow";
import { TraceFilterBar } from "../../../components/trace/TraceFilterBar";
import { EmptyState } from "../../../components/chrome/EmptyState";
import type { LedgerQuadrant } from "../../../lib/ledger-client.types";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Trace" };
export const dynamic = "force-dynamic";

const QUADRANT_VALUES: ReadonlySet<LedgerQuadrant> = new Set([
  "propose",
  "execute",
  "verify",
  "resolve",
]);

function asString(v: string | string[] | undefined): string | undefined {
  if (typeof v === "string" && v.length > 0) return v;
  if (Array.isArray(v) && v.length > 0 && typeof v[0] === "string")
    return v[0];
  return undefined;
}

export default async function TracePage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const companyId = await getCurrentCompanyId();

  // The filter bar publishes `kind` as either a quadrant literal (drop-down)
  // or a free-text substring (e.g. `source_proposed`). The ledger client
  // accepts both via `kind` (substring) + `quadrant` (exact). Promote the
  // literal to `quadrant` so the SQL fast-path can short-circuit, and keep
  // the substring on `kind` for everything else.
  const kindRaw = asString(params.kind);
  const quadrant: LedgerQuadrant | undefined =
    kindRaw && QUADRANT_VALUES.has(kindRaw as LedgerQuadrant)
      ? (kindRaw as LedgerQuadrant)
      : undefined;
  const kindFilter =
    kindRaw && !QUADRANT_VALUES.has(kindRaw as LedgerQuadrant)
      ? kindRaw
      : undefined;

  const personId = asString(params.person_id);
  const channelId = asString(params.channel_id);
  const tsFrom = asString(params.ts_from);
  const tsTo = asString(params.ts_to);

  const filtersActive = Boolean(
    kindRaw || personId || channelId || tsFrom || tsTo,
  );

  const page = await getTraceEntries(companyId, {
    limit: 50,
    quadrant,
    kind: kindFilter,
    personId,
    channelId,
    tsFrom,
    tsTo,
  });

  return (
    <PageBoundary surface="trace" traceQuery="?surface=trace">
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
          Pl. VIII · Append-only ledger
        </span>
        <h1
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 34,
            fontWeight: 500,
            letterSpacing: "-0.01em",
          }}
        >
          Trace · {page.entries.length}
          <span
            className="wb-mono"
            style={{
              fontSize: 11,
              marginLeft: 12,
              color: "var(--wb-color-hash-gray)",
              letterSpacing: "0.04em",
            }}
          >
            {filtersActive
              ? `${page.entries.length} entries match the active filters`
              : `most-recent ${page.entries.length} entries`}
          </span>
        </h1>
      </header>

      <TraceFilterBar />

      {page.entries.length === 0 ? (
        filtersActive ? (
          <EmptyState
            testId="trace-empty-filtered"
            eyebrow="no entries match"
            title="No ledger entries match the active filters."
            description={
              "Loosen the kind / person / channel / time-range constraints, " +
              "or clear them to see the most recent entries again."
            }
          />
        ) : (
          <EmptyState
            testId="trace-empty"
            eyebrow="no ledger entries yet"
            title="The append-only ledger is empty for this tenant."
            description={
              "Every action — proposed source, confirmed concept, fired gate, " +
              "policy applied — writes a hash-chained entry here. Run onboarding " +
              "to seed the first entries, or connect a chat platform so the " +
              "channel-adapter starts capturing the wire."
            }
            cta={{ label: "Run the wizard", href: "/onboarding" }}
            secondaryCta={{ label: "Connect a chat platform", href: "/channels" }}
          />
        )
      ) : (
        <ul
          data-testid="trace-stream"
          style={{ padding: 0, margin: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}
        >
          {page.entries.map((e) => (
            <TraceRow key={e.id} entry={e} />
          ))}
        </ul>
      )}
    </PageBoundary>
  );
}
