/**
 * /governance/tenant-quota — post-rest #3 (2026-05-13).
 *
 * Admin-only audit panel for ``tenant_quota_consumed`` ledger entries —
 * the opt-in ``LedgerQuotaTracker`` (final-wave item #7) emits one entry
 * per tenant at cadence (every 100 requests OR every 5 min per tenant,
 * whichever fires first; immediate on quota_exhausted).
 *
 * Surface contract:
 *
 *   * Per-tenant 24h summary table with consumption-band badges
 *     (red >90%, yellow >70%) — calling out tenants approaching the
 *     quota cap.
 *   * Flat recent-events list (last 100, ordered seq DESC) with the
 *     trigger discriminator inline and quota-exhausted rows visually
 *     emphasized — the audit trail for the deny moments.
 *
 * Defense in depth: page short-circuits to an "admin required" panel for
 * non-admins; the read accessors run server-side with companyId scoped
 * via the signed session cookie.
 *
 * Honest empty state: when no ``tenant_quota_consumed`` entries exist
 * (the default state when ``WORMBASE_TENANT_QUOTA_LEDGER`` is unset),
 * the page renders an env-knob hint instead of a fixture-faked summary.
 */
import Link from "next/link";

import { EmptyState } from "../../../../components/chrome/EmptyState";
import { PageBoundary } from "../../../../components/chrome/PageBoundary";
import { getCurrentCompanyId } from "../../../../lib/tenant-cookies";
import { getCurrentPerson } from "../../../../lib/server/identity";
import { getRolesForPerson } from "../../../../lib/ledger-client";
import { relativeTime } from "../../../../lib/people-display";
import {
  consumptionBand,
  getRecentQuotaEvents,
  getTenantQuotaSummary,
  type ConsumptionBand,
  type QuotaEvent,
  type QuotaTrigger,
  type TenantQuotaSummary,
} from "../../../../lib/tenant-quota";

export const metadata = { title: "WormBase · Tenant quota audit" };
export const dynamic = "force-dynamic";

const TRIGGER_FILTERS: ReadonlyArray<QuotaTrigger | "all"> = [
  "all",
  "count_threshold",
  "time_threshold",
  "quota_exhausted",
];

const TRIGGER_LABELS: Record<QuotaTrigger, string> = {
  count_threshold: "count threshold",
  time_threshold: "time threshold",
  quota_exhausted: "quota exhausted",
};

export default async function TenantQuotaPage({
  searchParams,
}: {
  searchParams?: Promise<{ triggered_by?: string }>;
}): Promise<JSX.Element> {
  const search = (await searchParams) ?? {};
  const companyId = await getCurrentCompanyId();
  const person = await getCurrentPerson(companyId);
  const isAdmin = await resolveIsAdmin(companyId, person);

  return (
    <PageBoundary
      surface="governance tenant-quota"
      traceQuery="?surface=governance.tenant_quota"
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
          Pl. IX · Governance lens · tenant quota
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
          Tenant quota audit
        </h1>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            maxWidth: 720,
          }}
        >
          Per-tenant MCP-request quota consumption, sourced from{" "}
          <code>tenant_quota_consumed</code> ledger entries emitted by{" "}
          <code>LedgerQuotaTracker</code>. The deny moments
          (<code>triggered_by=quota_exhausted</code>) are recorded immediately
          for SOC-2 replay; periodic windows summarise the rest.
        </p>
      </header>

      {!isAdmin ? (
        <EmptyState
          testId="tenant-quota-not-admin"
          eyebrow="admin required"
          title="Admin role required to view tenant-quota audit."
          description={
            "Only Persons with an unrevoked tenancy.admin (or " +
            "tenancy.installer) grant can view this audit panel. " +
            "It surfaces per-tenant quota consumption for the entire " +
            "deployment — privacy-bounded to admins by design."
          }
          cta={{ label: "Back to dashboard", href: "/dashboard" }}
        />
      ) : (
        <AdminContent
          companyId={companyId}
          triggeredByParam={
            typeof search.triggered_by === "string" ? search.triggered_by : null
          }
        />
      )}
    </PageBoundary>
  );
}

async function AdminContent({
  companyId,
  triggeredByParam,
}: {
  companyId: string;
  triggeredByParam: string | null;
}): Promise<JSX.Element> {
  const triggeredBy = normalizeTriggerFilter(triggeredByParam);
  const [summary, events] = await Promise.all([
    getTenantQuotaSummary(companyId),
    getRecentQuotaEvents(
      companyId,
      triggeredBy === "all" ? { limit: 100 } : { limit: 100, triggeredBy },
    ),
  ]);

  if (summary.length === 0 && events.length === 0) {
    return (
      <EmptyState
        testId="tenant-quota-empty"
        eyebrow="no quota events"
        title="No tenant quota events recorded."
        description={
          'Enable WORMBASE_TENANT_QUOTA_LEDGER=true to start emitting audit ' +
          "events. Without the env knob, LedgerQuotaTracker stays off and " +
          "the InMemoryQuotaTracker path runs byte-identical to pre-#7 " +
          "behaviour."
        }
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
      <SummarySection summary={summary} />
      <EventsSection events={events} activeTrigger={triggeredBy} />
    </div>
  );
}

function SummarySection({
  summary,
}: {
  summary: TenantQuotaSummary[];
}): JSX.Element {
  return (
    <section
      data-testid="tenant-quota-summary-section"
      style={{ display: "flex", flexDirection: "column", gap: 10 }}
    >
      <header
        style={{ display: "flex", alignItems: "baseline", gap: 12 }}
      >
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 20,
            fontWeight: 500,
          }}
        >
          Per-tenant · last 24h
        </h2>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
            letterSpacing: "0.04em",
          }}
        >
          {summary.length} tenant{summary.length === 1 ? "" : "s"}
        </span>
      </header>

      {summary.length === 0 ? (
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          No per-tenant activity in the last 24h. The events list below may
          include older entries.
        </p>
      ) : (
        <div
          style={{
            border: "1px solid var(--wb-color-aged-ink)",
            overflowX: "auto",
          }}
        >
          <table
            data-testid="tenant-quota-summary-table"
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
              fontSize: 12,
            }}
          >
            <thead>
              <tr style={{ background: "var(--wb-color-paper)" }}>
                <Th>Tenant slug</Th>
                <Th align="right">Consumed (24h)</Th>
                <Th align="right">Limit</Th>
                <Th align="right">Remaining</Th>
                <Th>Last event</Th>
                <Th>Last trigger</Th>
              </tr>
            </thead>
            <tbody>
              {summary.map((row) => (
                <SummaryRow key={row.tenantSlug} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function SummaryRow({ row }: { row: TenantQuotaSummary }): JSX.Element {
  const band = consumptionBand(row.consumed24h, row.quotaLimit);
  const badge = bandBadge(band);
  return (
    <tr
      data-testid={`tenant-quota-row-${row.tenantSlug}`}
      data-band={band}
      data-exhausted-count={row.exhaustedCount24h}
      style={{
        borderTop: "1px solid var(--wb-color-aged-ink)",
        background:
          band === "critical" ? "rgba(180, 60, 60, 0.06)" : "transparent",
      }}
    >
      <Td>
        <span style={{ fontWeight: 500 }}>{row.tenantSlug}</span>
      </Td>
      <Td align="right">
        <span style={{ display: "inline-flex", gap: 6, alignItems: "baseline" }}>
          {formatNumber(row.consumed24h)}
          {badge}
        </span>
      </Td>
      <Td align="right">{formatNumber(row.quotaLimit)}</Td>
      <Td align="right">{formatNumber(row.remaining)}</Td>
      <Td>
        <span title={row.lastEventTs}>{relativeTime(row.lastEventTs)}</span>
      </Td>
      <Td>
        <TriggerPill trigger={row.lastTriggeredBy} />
      </Td>
    </tr>
  );
}

function EventsSection({
  events,
  activeTrigger,
}: {
  events: QuotaEvent[];
  activeTrigger: QuotaTrigger | "all";
}): JSX.Element {
  return (
    <section
      data-testid="tenant-quota-events-section"
      style={{ display: "flex", flexDirection: "column", gap: 10 }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 20,
            fontWeight: 500,
          }}
        >
          Recent quota events
        </h2>
        <span
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-hash-gray)",
            letterSpacing: "0.04em",
          }}
        >
          {events.length} event{events.length === 1 ? "" : "s"} · seq DESC
        </span>
        <TriggerFilter active={activeTrigger} />
      </header>

      {events.length === 0 ? (
        <p
          data-testid="tenant-quota-events-empty"
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-hash-gray)",
            fontSize: 13,
          }}
        >
          No events match the current filter.
        </p>
      ) : (
        <div
          style={{
            border: "1px solid var(--wb-color-aged-ink)",
            overflowX: "auto",
          }}
        >
          <table
            data-testid="tenant-quota-events-table"
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
              fontSize: 12,
            }}
          >
            <thead>
              <tr style={{ background: "var(--wb-color-paper)" }}>
                <Th>Timestamp</Th>
                <Th>Tenant</Th>
                <Th>Trigger</Th>
                <Th align="right">Consumption</Th>
                <Th align="right">Remaining</Th>
                <Th>Hash</Th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <EventRow key={`${event.seq}`} event={event} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function EventRow({ event }: { event: QuotaEvent }): JSX.Element {
  const exhausted = event.triggeredBy === "quota_exhausted";
  return (
    <tr
      data-testid={`tenant-quota-event-${event.seq}`}
      data-trigger={event.triggeredBy}
      style={{
        borderTop: "1px solid var(--wb-color-aged-ink)",
        background: exhausted ? "rgba(180, 60, 60, 0.08)" : "transparent",
        color: exhausted ? "var(--wb-color-aged-ink)" : undefined,
        fontWeight: exhausted ? 500 : 400,
      }}
    >
      <Td>
        <span title={event.ts}>{formatTimestamp(event.ts)}</span>
      </Td>
      <Td>{event.tenantSlug}</Td>
      <Td>
        <TriggerPill trigger={event.triggeredBy} />
      </Td>
      <Td align="right">{formatNumber(event.consumptionCount)}</Td>
      <Td align="right">
        <span style={{ display: "inline-flex", gap: 4, alignItems: "baseline" }}>
          {formatNumber(event.quotaRemaining)}
          {exhausted ? <DenyBadge /> : null}
        </span>
      </Td>
      <Td>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            color: "var(--wb-color-hash-gray)",
          }}
        >
          {event.hashHex.slice(0, 10)}…
        </span>
      </Td>
    </tr>
  );
}

function TriggerFilter({
  active,
}: {
  active: QuotaTrigger | "all";
}): JSX.Element {
  return (
    <nav
      data-testid="tenant-quota-trigger-filter"
      style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}
    >
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          color: "var(--wb-color-hash-gray)",
          letterSpacing: "0.04em",
        }}
      >
        filter:
      </span>
      {TRIGGER_FILTERS.map((value) => {
        const isActive = value === active;
        const label = value === "all" ? "all" : TRIGGER_LABELS[value];
        const href =
          value === "all"
            ? "/governance/tenant-quota"
            : `/governance/tenant-quota?triggered_by=${encodeURIComponent(value)}`;
        return (
          <Link
            key={value}
            href={href}
            data-testid={`tenant-quota-filter-${value}`}
            data-active={isActive ? "true" : "false"}
            className="wb-mono"
            style={{
              fontSize: 11,
              padding: "2px 8px",
              border: "1px solid var(--wb-color-aged-ink)",
              background: isActive
                ? "var(--wb-color-aged-ink)"
                : "transparent",
              color: isActive
                ? "var(--wb-color-paper)"
                : "var(--wb-color-aged-ink)",
              textDecoration: "none",
              letterSpacing: "0.02em",
            }}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function TriggerPill({ trigger }: { trigger: QuotaTrigger }): JSX.Element {
  const style: React.CSSProperties = {
    display: "inline-block",
    padding: "1px 8px",
    border: "1px solid var(--wb-color-aged-ink)",
    background:
      trigger === "quota_exhausted"
        ? "rgba(180, 60, 60, 0.18)"
        : trigger === "time_threshold"
          ? "rgba(120, 100, 40, 0.12)"
          : "transparent",
    fontSize: 10,
    letterSpacing: "0.04em",
  };
  return (
    <span className="wb-mono" style={style}>
      {TRIGGER_LABELS[trigger]}
    </span>
  );
}

function bandBadge(band: ConsumptionBand): JSX.Element | null {
  if (band === "healthy") return null;
  const label = band === "critical" ? "≥90%" : "≥70%";
  const colors =
    band === "critical"
      ? { bg: "rgba(180, 60, 60, 0.18)", fg: "#7a2828" }
      : { bg: "rgba(190, 150, 30, 0.18)", fg: "#735a14" };
  return (
    <span
      data-testid={`tenant-quota-badge-${band}`}
      className="wb-mono"
      style={{
        display: "inline-block",
        padding: "0 6px",
        fontSize: 9,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        border: `1px solid ${colors.fg}`,
        background: colors.bg,
        color: colors.fg,
      }}
    >
      {band === "critical" ? "max" : "warn"} {label}
    </span>
  );
}

function DenyBadge(): JSX.Element {
  return (
    <span
      data-testid="tenant-quota-deny-badge"
      className="wb-mono"
      style={{
        display: "inline-block",
        padding: "0 6px",
        fontSize: 9,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        border: "1px solid #7a2828",
        background: "rgba(180, 60, 60, 0.22)",
        color: "#7a2828",
      }}
    >
      deny
    </span>
  );
}

function Th({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}): JSX.Element {
  return (
    <th
      style={{
        textAlign: align,
        padding: "8px 12px",
        fontFamily: "var(--wb-font-mono, ui-monospace, monospace)",
        fontSize: 10,
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        color: "var(--wb-color-hash-gray)",
        borderBottom: "1px solid var(--wb-color-aged-ink)",
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}): JSX.Element {
  return (
    <td
      style={{
        textAlign: align,
        padding: "8px 12px",
        verticalAlign: "top",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </td>
  );
}

function formatNumber(n: number): string {
  return Number.isFinite(n) ? n.toLocaleString("en-US") : String(n);
}

function formatTimestamp(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return iso;
  const yyyy = d.getUTCFullYear();
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mi = String(d.getUTCMinutes()).padStart(2, "0");
  const ss = String(d.getUTCSeconds()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`;
}

function normalizeTriggerFilter(
  raw: string | null,
): QuotaTrigger | "all" {
  if (raw === "count_threshold") return "count_threshold";
  if (raw === "time_threshold") return "time_threshold";
  if (raw === "quota_exhausted") return "quota_exhausted";
  return "all";
}

async function resolveIsAdmin(
  companyId: string,
  person: Awaited<ReturnType<typeof getCurrentPerson>>,
): Promise<boolean> {
  if (!person) return false;
  if (person.tenancyRole === "admin" || person.tenancyRole === "installer") {
    return true;
  }
  let grants: Awaited<ReturnType<typeof getRolesForPerson>> = [];
  try {
    grants = await getRolesForPerson(companyId, person.personId);
  } catch {
    grants = [];
  }
  const live = grants
    .filter((g) => g.facet === "tenancy" && g.revokedAt === null)
    .map((g) => g.role);
  return live.includes("admin") || live.includes("installer");
}

export const __test__ = {
  normalizeTriggerFilter,
  resolveIsAdmin,
};
