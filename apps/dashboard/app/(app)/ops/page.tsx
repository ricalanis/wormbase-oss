/**
 * /ops — observability tab (W2.A10).
 *
 * Surfaces the four production-critical health metrics:
 *
 *   1. Postgres reachability + latency
 *   2. Ledger throughput sparkline (last 10 minutes)
 *   3. MCP rate-limit status per tenant
 *   4. Agent loop status (worm-core / channel-adapter / projection-runner)
 *
 * Server component does an initial fetch for first-paint data; the client
 * `OpsLiveView` then polls /api/v1/ops/health every 5 seconds.
 *
 * Visibility per `lib/role-nav.ts`:
 *   - admin     — daily; full nav
 *   - observer  — weekly; readOnly chrome
 *   - installer — hidden (during onboarding)
 *   - member    — hidden (privacy: per-tenant rate limits surface other
 *                tenants' metadata)
 *
 * Polling cadence (5s) is documented inline in OpsLiveView.tsx.
 */

import { fetchOpsHealth } from "../../../lib/server/ops-health";
import { getTenantFromCookies } from "../../../lib/tenant-cookies";
import { OpsLiveView } from "../../../components/ops/OpsLiveView";
import { PageBoundary } from "../../../components/chrome/PageBoundary";

export const metadata = { title: "WormBase · Ops" };
export const dynamic = "force-dynamic";

export default async function OpsPage() {
  const tenant = await getTenantFromCookies();
  const initial = await fetchOpsHealth(tenant.slug);
  return (
    <PageBoundary surface="ops" traceQuery="?surface=ops">
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
          Pl. IX · Operational health · live
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
          Ops
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
          Postgres reachability, ledger throughput, MCP rate-limit
          headroom, and agent-loop liveness — all sourced from the
          worm-core process. Refreshes every five seconds; the panel
          renders the most recent good snapshot if a refresh fails.
        </p>
      </header>

      <OpsLiveView initial={initial} />
    </PageBoundary>
  );
}
